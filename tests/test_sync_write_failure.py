"""A failing batch write must not abort the whole sync (review finding C2)."""

import sqlite3

from frequenzradio.api import Station
from frequenzradio.sync import sync_stations


def _station(place_id: str) -> Station:
    return Station(id=f"s-{place_id}", slug="s", title="S", url="", place_id=place_id,
                   place_title=None, country=None, country_id=None, stream_host=None,
                   secure=False, preroll=False)


class FakeClient:
    def place_stations(self, place_id):
        return [_station(place_id)]


class FlakyCatalog:
    """Writes single places fine; refuses multi-place batches like a busy database."""

    def __init__(self, always_fail=False):
        self.saved = []
        self.marked = False
        self.always_fail = always_fail

    def places_to_sync(self, *, full=False, limit=None):
        return ["a", "b", "c"]

    def save_place_stations(self, batch):
        if self.always_fail or len(batch) > 1:
            raise sqlite3.OperationalError("database is locked")
        self.saved.extend(batch[0][1])
        return len(batch[0][1])

    def mark_synced(self):
        self.marked = True


def test_batch_failure_retries_place_by_place():
    catalog = FlakyCatalog()
    report = sync_stations(FakeClient(), catalog, workers=1, batch_size=2)
    assert report.stations_saved == 3
    assert report.places_failed == 0
    assert sorted(s.id for s in catalog.saved) == ["s-a", "s-b", "s-c"]
    assert catalog.marked is True


def test_persistent_write_failure_is_counted_not_raised():
    catalog = FlakyCatalog(always_fail=True)
    report = sync_stations(FakeClient(), catalog, workers=1, batch_size=1)
    assert report.places_failed == 3
    assert report.stations_saved == 0
    assert catalog.marked is False  # a failed run must not stamp last_sync_at
