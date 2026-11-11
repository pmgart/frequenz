"""Incremental sync must notice places whose station list changed (review finding C4)."""

from frequenzradio.api import Place, Station
from frequenzradio.catalog import Catalog


def _place(place_id: str, size: int) -> Place:
    return Place(id=place_id, title=place_id.title(), country="X", lng=1.0, lat=2.0,
                 size=size, boost=False, url="")


def _station(station_id: str, place_id: str) -> Station:
    return Station(id=station_id, slug=station_id, title=station_id, url="",
                   place_id=place_id, place_title=None, country=None, country_id=None,
                   stream_host=None, secure=False, preroll=False)


def test_size_change_requeues_the_place(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    try:
        catalog.upsert_places([_place("p1", 2)], "v1")
        catalog.save_place_stations([("p1", [_station("s1", "p1"), _station("s2", "p1")])])
        assert catalog.stats().places_synced == 1
        assert catalog.places_to_sync() == []

        # A station was added upstream: the place must be fetched again.
        catalog.upsert_places([_place("p1", 3)], "v1")
        assert catalog.places_to_sync() == ["p1"]
    finally:
        catalog.close()


def test_version_change_requeues_every_place(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    try:
        catalog.upsert_places([_place("p1", 1), _place("p2", 1)], "v1")
        catalog.save_place_stations([
            ("p1", [_station("s1", "p1")]),
            ("p2", [_station("s2", "p2")]),
        ])
        assert catalog.stats().places_synced == 2

        catalog.upsert_places([_place("p1", 1), _place("p2", 1)], "v2")
        assert sorted(catalog.places_to_sync()) == ["p1", "p2"]
    finally:
        catalog.close()


def test_unchanged_places_stay_synced(tmp_path):
    catalog = Catalog(tmp_path / "catalog.sqlite")
    try:
        catalog.upsert_places([_place("p1", 1)], "v1")
        catalog.save_place_stations([("p1", [_station("s1", "p1")])])
        catalog.upsert_places([_place("p1", 1)], "v1")
        assert catalog.stats().places_synced == 1
    finally:
        catalog.close()
