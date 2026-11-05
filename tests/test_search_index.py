"""The search index must follow the station table as rows are written, not only after a sync."""

from frequenzradio.api import Station
from frequenzradio.catalog import Catalog


def make_station(station_id: str, title: str, place_title: str = "Paris", country: str = "France") -> Station:
    return Station(
        id=station_id, slug="slug", title=title, url=f"/listen/slug/{station_id}",
        place_id="p1", place_title=place_title, country=country, country_id="c1",
        stream_host=None, secure=True, preroll=False,
    )


def ids(rows) -> list[str]:
    return [row["id"] for row in rows]


def test_search_finds_stations_saved_before_any_rebuild(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    try:
        catalog.save_place_stations([("p1", [make_station("s1", "Jazz Radio Paris")])])
        # No rebuild_search_index(): a sync still in progress must already be searchable.
        assert ids(catalog.search("jazz")) == ["s1"]
        assert ids(catalog.search("paris")) == ["s1"]
    finally:
        catalog.close()


def test_resaving_a_station_replaces_its_search_entry(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    try:
        catalog.save_place_stations([("p1", [make_station("s1", "Old Name FM")])])
        catalog.save_place_stations([("p1", [make_station("s1", "New Name FM")])])
        assert ids(catalog.search("new")) == ["s1"]
        assert catalog.search("old") == []
        assert catalog.stats().search_rows == 1
    finally:
        catalog.close()


def test_search_index_matches_station_table_after_mixed_saves(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    try:
        batch = [make_station(f"s{i}", f"Station {i}") for i in range(50)]
        catalog.save_place_stations([("p1", batch)])
        catalog.save_place_stations([("p1", batch[:10])])  # partial re-save
        stats = catalog.stats()
        assert stats.stations == 50
        assert stats.search_rows == 50
        assert len(catalog.search("station", limit=1000)) == 50
    finally:
        catalog.close()


def test_deleting_a_station_removes_it_from_search(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    try:
        catalog.save_place_stations([("p1", [make_station("s1", "Gone Soon FM"), make_station("s2", "Stays FM")])])
        catalog.db.execute("DELETE FROM stations WHERE id = 's1'")
        catalog.db.commit()
        assert catalog.search("gone") == []
        assert ids(catalog.search("stays")) == ["s2"]
        assert catalog.stats().search_rows == 1
    finally:
        catalog.close()


def test_opening_a_version_1_catalog_repairs_its_search_index(tmp_path):
    path = tmp_path / "catalog.sqlite"
    catalog = Catalog(path)
    catalog.save_place_stations([("p1", [make_station("s1", "Legacy Radio")])])
    # Recreate a version 1 catalog: no triggers, and a station missing from the index.
    for trigger in ("stations_fts_insert", "stations_fts_update", "stations_fts_delete"):
        catalog.db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    catalog.db.execute("DELETE FROM stations_fts")
    catalog.set_meta("schema_version", "1")
    catalog.db.commit()
    catalog.close()

    reopened = Catalog(path)
    try:
        assert ids(reopened.search("legacy")) == ["s1"]
        assert reopened.get_meta("schema_version") == "3"
        assert reopened.stats().search_rows == 1
    finally:
        reopened.close()
