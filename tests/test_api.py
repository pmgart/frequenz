"""Parsing tests against synthetic API responses in tests/fixtures (no network)."""

import json
from pathlib import Path

from frequenzradio.api import parse_place_channels, parse_places, station_from_page

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_places_keeps_coordinates_and_skips_entries_without_geo():
    version, places = parse_places(load("places_sample.json"))
    assert version == "sample-1"
    assert len(places) == 40  # the 41st fixture entry has no coordinates
    first = places[0]
    assert first.id == "Qx7vLm2K"
    assert first.title == "Lake Demo"
    assert first.country == "Freedonia"
    assert abs(first.lng - 12.5) < 1e-9 and abs(first.lat - 48.25) < 1e-9
    assert first.size == 1 and first.boost is False
    assert all(-180 <= p.lng <= 180 and -90 <= p.lat <= 90 for p in places)


def test_parse_place_channels_extracts_station_fields():
    stations = parse_place_channels(load("place_channels_sample.json"))
    assert len(stations) == 1
    s = stations[0]
    assert s.id == "Km7d_Tq3"
    assert s.slug == "orbita-fm"
    assert s.title == "Orbita FM"
    assert s.place_id == "Qx7vLm2K" and s.place_title == "Lake Demo"
    assert s.country == "Freedonia" and s.country_id == "Fd0n1a9x"
    assert s.stream_host == "stream.example.test"
    assert s.secure is True and s.preroll is False
    assert s.listen_path == "/api/ara/content/listen/Km7d_Tq3/channel.mp3"


def test_preroll_flag_is_kept_so_the_app_can_see_ad_supported_streams():
    page = {"type": "channel", "url": "/listen/demo-radio-uno/pR3vQ8xE", "title": "Demo Radio Uno",
            "place": {"id": "p1", "title": "Demo City"}, "country": {"id": "c1", "title": "Freedonia"},
            "preroll": True, "stream": "zeno.fm", "secure": True}
    station = station_from_page(page)
    assert station is not None and station.preroll is True and station.id == "pR3vQ8xE"


def test_non_channel_or_malformed_urls_are_rejected():
    assert station_from_page({"url": "/visit/lake-demo/Qx7vLm2K", "type": "place"}) is None
    assert station_from_page({"url": "/listen/"}) is None
    assert station_from_page({"url": ""}) is None


def test_channel_detail_fixture_has_website_and_social_links():
    detail = load("channel_detail_sample.json")
    data = detail.get("data", detail)
    assert data["id"] == "Km7d_Tq3"
    assert data["website"].startswith("https://")
    assert isinstance(data["social"], list)
