"""Opening a version 2 catalog cleans its stored metadata once and keeps search consistent."""

from frequenzradio.api import Place, Station
from frequenzradio.catalog import Catalog


def test_version_2_metadata_is_cleaned_on_open(tmp_path):
    path = tmp_path / "catalog.sqlite"
    catalog = Catalog(path)
    catalog.upsert_places([Place(id="p1", title="\u200bHsinchu City", country="Taiwan\u200e", lng=120.9,
                                 lat=24.8, size=3, boost=False, url="/visit/hsinchu/p1")], "v")
    catalog.save_place_stations([("p1", [Station(
        id="s1", slug="hot", title="Hot FM\u200b ", url="/listen/hot/s1", place_id="p1",
        place_title="\u200bHsinchu City", country="Taiwan\u200e", country_id="c1",
        stream_host=None, secure=True, preroll=False)])])
    # Simulate a catalog written by version 2, which stored the raw values.
    catalog.set_meta("schema_version", "2")
    catalog.db.commit()
    catalog.close()

    reopened = Catalog(path)
    try:
        assert reopened.place("p1")["title"] == "Hsinchu City"
        assert reopened.place("p1")["country"] == "Taiwan"
        station = reopened.station("s1")
        assert (station["title"], station["place_title"], station["country"]) == (
            "Hot FM", "Hsinchu City", "Taiwan")
        assert [row["id"] for row in reopened.search("hsinchu")] == ["s1"]
        assert reopened.get_meta("schema_version") == "3"
    finally:
        reopened.close()
