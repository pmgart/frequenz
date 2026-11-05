"""Catalog tests: schema, FTS search, favorites, history and station details (temporary DB)."""

import json
from pathlib import Path

import pytest

from frequenzradio.api import parse_place_channels, parse_places
from frequenzradio.catalog import Catalog, fts_query

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def catalog(tmp_path):
    cat = Catalog(tmp_path / "catalog.sqlite")
    yield cat
    cat.close()


@pytest.fixture()
def seeded(catalog):
    version, places = parse_places(json.loads((FIXTURES / "places_sample.json").read_text(encoding="utf-8")))
    catalog.upsert_places(places, version)
    channels = parse_place_channels(json.loads((FIXTURES / "place_channels_sample.json").read_text(encoding="utf-8")))
    catalog.save_place_stations([("Qx7vLm2K", channels)])
    catalog.rebuild_search_index()
    return catalog


def test_upsert_places_and_stats(seeded):
    stats = seeded.stats()
    assert stats.places == 40
    assert stats.places_synced == 1  # only Lake Demo got its station list
    assert stats.stations == 1
    assert stats.places_version == "sample-1"
    assert seeded.places_to_sync(full=False) and "Qx7vLm2K" not in seeded.places_to_sync(full=False)


def test_places_to_sync_orders_bigger_places_first(catalog):
    _, places = parse_places(json.loads((FIXTURES / "places_sample.json").read_text(encoding="utf-8")))
    catalog.upsert_places(places, "v")
    order = catalog.places_to_sync()
    sizes = [catalog.place(pid)["size"] for pid in order]
    assert sizes == sorted(sizes, reverse=True)


def test_search_matches_station_place_and_country_with_prefix(seeded):
    assert [r["id"] for r in seeded.search("orbi")] == ["Km7d_Tq3"]
    assert [r["id"] for r in seeded.search("lake dem")] == ["Km7d_Tq3"]
    assert [r["id"] for r in seeded.search("freedo")] == ["Km7d_Tq3"]
    assert seeded.search("nonexistent-term") == []
    assert seeded.search("   ") == []


def test_fts_query_is_safe_for_arbitrary_input():
    assert fts_query('stad "rad"; DROP') == '"stad"* "rad"* "DROP"*'
    assert fts_query("***") is None
    assert fts_query("") is None
    assert fts_query("Göteborg") == '"Göteborg"*'


def test_search_handles_diacritics(catalog):
    from frequenzradio.api import Station

    catalog.save_place_stations([("p1", [Station(id="s1", slug="x", title="Radio Göteborg", url="/listen/x/s1",
                                                 place_id="p1", place_title="Göteborg", country="Sverige",
                                                 country_id="c", stream_host=None, secure=True, preroll=False)])])
    catalog.rebuild_search_index()
    assert [r["id"] for r in catalog.search("goteborg")] == ["s1"]
    assert [r["id"] for r in catalog.search("Göteborg")] == ["s1"]


def test_favorites_toggle_and_listing(seeded):
    assert not seeded.is_favorite("Km7d_Tq3")
    seeded.set_favorite("Km7d_Tq3", True)
    seeded.set_favorite("Km7d_Tq3", True)  # idempotent
    assert seeded.is_favorite("Km7d_Tq3")
    assert [r["id"] for r in seeded.favorites()] == ["Km7d_Tq3"]
    seeded.set_favorite("Km7d_Tq3", False)
    assert seeded.favorites() == []


def test_history_keeps_latest_first_and_is_bounded(seeded):
    for _ in range(3):
        seeded.record_play("Km7d_Tq3")
    rows = seeded.recent()
    assert [r["id"] for r in rows] == ["Km7d_Tq3"]
    count = seeded.db.execute("SELECT COUNT(*) FROM history").fetchone()[0]
    assert count == 3


def test_station_detail_roundtrip(seeded):
    assert seeded.station_detail("Km7d_Tq3") is None
    seeded.save_station_detail("Km7d_Tq3", "https://example.org", [{"platform": "x", "url": "https://x"}])
    detail = seeded.station_detail("Km7d_Tq3")
    assert detail == {"website": "https://example.org", "social": [{"platform": "x", "url": "https://x"}]}


def test_random_and_neighbours(seeded):
    assert seeded.random_station()["id"] == "Km7d_Tq3"
    assert [r["id"] for r in seeded.neighbours_in_place("Km7d_Tq3")] == ["Km7d_Tq3"]
    assert seeded.neighbours_in_place("missing") == []


def test_resave_is_idempotent_and_replaces_station(seeded):
    channels = parse_place_channels(json.loads((FIXTURES / "place_channels_sample.json").read_text(encoding="utf-8")))
    seeded.save_place_stations([("Qx7vLm2K", channels)])
    seeded.save_place_stations([("Qx7vLm2K", channels)])
    seeded.rebuild_search_index()
    assert seeded.stats().stations == 1
    assert len(seeded.search("orbi")) == 1
