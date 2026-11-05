"""Local catalog: SQLite (WAL) with FTS5 search, favorites, history and station details.

The database lives in the user's data directory and is the only data source the
GUI reads from, so browsing, search and the globe work offline. Only playback
needs the network.

Search stays complete while a sync is still running. Triggers keep the FTS5 index
in step with the station table row by row, and stations are written with upserts,
so rowids stay stable and a re-saved station never leaves a stale search entry.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .api import Place, Station
from .text import clean_text

# Version 3: station and place metadata is cleaned with clean_text (invisible characters,
# spacing). Version 2: triggers keep the search index current. Version 1 rebuilt the index
# only after a completed sync. Each older version is repaired once when it is opened.
SCHEMA_VERSION = "3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS places (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    country         TEXT NOT NULL DEFAULT '',
    lng             REAL NOT NULL,
    lat             REAL NOT NULL,
    size            INTEGER NOT NULL DEFAULT 0,
    boost           INTEGER NOT NULL DEFAULT 0,
    url             TEXT NOT NULL DEFAULT '',
    channels_synced INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stations (
    id           TEXT PRIMARY KEY,
    slug         TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL,
    url          TEXT NOT NULL DEFAULT '',
    place_id     TEXT,
    place_title  TEXT,
    country      TEXT,
    country_id   TEXT,
    stream_host  TEXT,
    secure       INTEGER NOT NULL DEFAULT 0,
    preroll      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS stations_by_place ON stations(place_id);
CREATE INDEX IF NOT EXISTS stations_by_country ON stations(country);
CREATE VIRTUAL TABLE IF NOT EXISTS stations_fts USING fts5(
    title, place_title, country, tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS stations_fts_insert AFTER INSERT ON stations BEGIN
    INSERT INTO stations_fts(rowid, title, place_title, country)
    VALUES (new.rowid, new.title, COALESCE(new.place_title, ''), COALESCE(new.country, ''));
END;
CREATE TRIGGER IF NOT EXISTS stations_fts_update AFTER UPDATE ON stations BEGIN
    DELETE FROM stations_fts WHERE rowid = old.rowid;
    INSERT INTO stations_fts(rowid, title, place_title, country)
    VALUES (new.rowid, new.title, COALESCE(new.place_title, ''), COALESCE(new.country, ''));
END;
CREATE TRIGGER IF NOT EXISTS stations_fts_delete AFTER DELETE ON stations BEGIN
    DELETE FROM stations_fts WHERE rowid = old.rowid;
END;
CREATE TABLE IF NOT EXISTS favorites (
    station_id TEXT PRIMARY KEY,
    added_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    played_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS history_by_time ON history(played_at);
CREATE TABLE IF NOT EXISTS station_details (
    station_id  TEXT PRIMARY KEY,
    website     TEXT,
    social_json TEXT NOT NULL DEFAULT '[]',
    fetched_at  TEXT NOT NULL
);
"""

HISTORY_LIMIT = 500


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fts_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 prefix query: ``stad rad`` -> ``"stad"* "rad"*``."""
    tokens = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
    if not tokens:
        return None
    return " ".join(f'"{token}"*' for token in tokens)


@dataclass(frozen=True)
class CatalogStats:
    places: int
    places_synced: int
    stations: int
    search_rows: int
    favorites: int
    last_sync_at: str | None
    places_version: str | None


class Catalog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=OFF")
        self.db.executescript(SCHEMA)  # creates missing tables and triggers
        previous = self.get_meta("schema_version")
        self.set_meta("schema_version", SCHEMA_VERSION)
        self.db.commit()
        if previous != SCHEMA_VERSION:
            self._clean_existing_metadata()
            # Version 1 catalogs can miss stations saved after their last completed sync.
            self.rebuild_search_index()

    def close(self) -> None:
        self.db.close()

    # -- meta --------------------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    # -- sync writes -------------------------------------------------------------
    def upsert_places(self, places: Iterable[Place], version: str | None) -> int:
        count = 0
        with self.db:
            for p in places:
                self.db.execute(
                    """
                    INSERT INTO places(id, title, country, lng, lat, size, boost, url)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        title = excluded.title, country = excluded.country,
                        lng = excluded.lng, lat = excluded.lat, size = excluded.size,
                        boost = excluded.boost, url = excluded.url
                    """,
                    (p.id, p.title, p.country, p.lng, p.lat, p.size, int(p.boost), p.url),
                )
                count += 1
            if version:
                self.set_meta("places_version", version)
        return count

    def places_to_sync(self, *, full: bool = False, limit: int | None = None) -> list[str]:
        where = "" if full else "WHERE channels_synced = 0"
        sql = f"SELECT id FROM places {where} ORDER BY size DESC, title COLLATE NOCASE"
        params: tuple = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (int(limit),)
        return [row["id"] for row in self.db.execute(sql, params)]

    def save_place_stations(self, batch: Sequence[tuple[str, Sequence[Station]]]) -> int:
        saved = 0
        with self.db:
            for place_id, stations in batch:
                for s in stations:
                    # Upsert, not INSERT OR REPLACE: a replace would give the station a new
                    # rowid and leave its search entry pointing at the old one.
                    self.db.execute(
                        """
                        INSERT INTO stations(
                            id, slug, title, url, place_id, place_title, country,
                            country_id, stream_host, secure, preroll)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            slug = excluded.slug, title = excluded.title, url = excluded.url,
                            place_id = excluded.place_id, place_title = excluded.place_title,
                            country = excluded.country, country_id = excluded.country_id,
                            stream_host = excluded.stream_host, secure = excluded.secure,
                            preroll = excluded.preroll
                        """,
                        (
                            s.id, s.slug, s.title, s.url,
                            s.place_id or place_id, s.place_title, s.country,
                            s.country_id, s.stream_host, int(s.secure), int(s.preroll),
                        ),
                    )
                    saved += 1
                self.db.execute(
                    "UPDATE places SET channels_synced = 1 WHERE id = ?", (place_id,)
                )
        return saved

    def _clean_existing_metadata(self) -> None:
        """Apply clean_text to metadata stored by earlier versions (once, on open)."""
        places = []
        for row in self.db.execute("SELECT id, title, country FROM places"):
            title, country = clean_text(row["title"]), clean_text(row["country"])
            if (title, country) != (row["title"], row["country"]):
                places.append((title, country, row["id"]))
        stations = []
        for row in self.db.execute("SELECT id, title, place_title, country FROM stations"):
            title = clean_text(row["title"]) or row["id"]
            place_title = clean_text(row["place_title"]) or None
            country = clean_text(row["country"]) or None
            if (title, place_title, country) != (row["title"], row["place_title"], row["country"]):
                stations.append((title, place_title, country, row["id"]))
        with self.db:  # the search index follows these updates through its triggers
            self.db.executemany("UPDATE places SET title = ?, country = ? WHERE id = ?", places)
            self.db.executemany(
                "UPDATE stations SET title = ?, place_title = ?, country = ? WHERE id = ?", stations
            )

    def rebuild_search_index(self) -> None:
        """Rebuild the whole search index. A repair tool: the triggers keep it current."""
        with self.db:
            self.db.execute("DELETE FROM stations_fts")
            self.db.execute(
                """
                INSERT INTO stations_fts(rowid, title, place_title, country)
                SELECT rowid, title, COALESCE(place_title, ''), COALESCE(country, '')
                FROM stations
                """
            )

    def mark_synced(self) -> None:
        """Record that a sync run finished without being cancelled."""
        with self.db:
            self.set_meta("last_sync_at", utc_now())

    # -- reads -------------------------------------------------------------------
    def stats(self) -> CatalogStats:
        def scalar(sql: str) -> int:
            return int(self.db.execute(sql).fetchone()[0])

        return CatalogStats(
            places=scalar("SELECT COUNT(*) FROM places"),
            places_synced=scalar("SELECT COUNT(*) FROM places WHERE channels_synced = 1"),
            stations=scalar("SELECT COUNT(*) FROM stations"),
            search_rows=scalar("SELECT COUNT(*) FROM stations_fts"),
            favorites=scalar("SELECT COUNT(*) FROM favorites"),
            last_sync_at=self.get_meta("last_sync_at"),
            places_version=self.get_meta("places_version"),
        )

    def places(self) -> list[sqlite3.Row]:
        """All places with coordinates; used once to build the globe's point buffer."""
        return list(
            self.db.execute(
                "SELECT id, title, country, lng, lat, size, boost FROM places ORDER BY id"
            )
        )

    def place(self, place_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()

    def stations_in_place(self, place_id: str) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                "SELECT * FROM stations WHERE place_id = ? ORDER BY title COLLATE NOCASE",
                (place_id,),
            )
        )

    def station(self, station_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM stations WHERE id = ?", (station_id,)).fetchone()

    def search(self, text: str, limit: int = 100) -> list[sqlite3.Row]:
        query = fts_query(text)
        if not query:
            return []
        return list(
            self.db.execute(
                """
                SELECT s.*, bm25(stations_fts) AS score
                FROM stations_fts
                JOIN stations AS s ON s.rowid = stations_fts.rowid
                WHERE stations_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (query, int(limit)),
            )
        )

    def random_station(self) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM stations ORDER BY RANDOM() LIMIT 1"
        ).fetchone()

    def neighbours_in_place(self, station_id: str) -> list[sqlite3.Row]:
        row = self.station(station_id)
        if row is None or row["place_id"] is None:
            return [] if row is None else [row]
        return self.stations_in_place(row["place_id"])

    # -- favorites & history -----------------------------------------------------
    def favorites(self) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                """
                SELECT s.* FROM favorites AS f
                JOIN stations AS s ON s.id = f.station_id
                ORDER BY f.added_at DESC
                """
            )
        )

    def is_favorite(self, station_id: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM favorites WHERE station_id = ?", (station_id,)
        ).fetchone() is not None

    def set_favorite(self, station_id: str, value: bool) -> None:
        with self.db:
            if value:
                self.db.execute(
                    "INSERT OR IGNORE INTO favorites(station_id, added_at) VALUES(?, ?)",
                    (station_id, utc_now()),
                )
            else:
                self.db.execute("DELETE FROM favorites WHERE station_id = ?", (station_id,))

    def record_play(self, station_id: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO history(station_id, played_at) VALUES(?, ?)",
                (station_id, utc_now()),
            )
            self.db.execute(
                """
                DELETE FROM history WHERE id NOT IN (
                    SELECT id FROM history ORDER BY id DESC LIMIT ?)
                """,
                (HISTORY_LIMIT,),
            )

    def recent(self, limit: int = 30) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                """
                SELECT s.*, MAX(h.id) AS last_id FROM history AS h
                JOIN stations AS s ON s.id = h.station_id
                GROUP BY s.id ORDER BY last_id DESC LIMIT ?
                """,
                (int(limit),),
            )
        )

    # -- station details (fetched lazily, cached) --------------------------------
    def station_detail(self, station_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT website, social_json FROM station_details WHERE station_id = ?",
            (station_id,),
        ).fetchone()
        if row is None:
            return None
        return {"website": row["website"], "social": json.loads(row["social_json"])}

    def save_station_detail(self, station_id: str, website: str | None, social: list) -> None:
        with self.db:
            self.db.execute(
                """
                INSERT INTO station_details(station_id, website, social_json, fetched_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(station_id) DO UPDATE SET
                    website = excluded.website,
                    social_json = excluded.social_json,
                    fetched_at = excluded.fetched_at
                """,
                (station_id, website, json.dumps(social, ensure_ascii=False), utc_now()),
            )
