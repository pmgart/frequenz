"""Remote payloads must never take the whole sync down (review finding C1)."""

import pytest

from frequenzradio.api import ApiError, RadioGardenClient, parse_places


def _payload(*entries):
    return {"data": {"version": "v1", "list": list(entries)}}


def test_one_malformed_entry_does_not_discard_the_others():
    payload = _payload(
        {"id": "bad-geo", "title": "Bad", "geo": ["n/a", 2.0], "size": 3},
        {"id": "good", "title": "Good", "geo": [18.07, 59.33], "size": "4"},
    )
    version, places = parse_places(payload)
    assert version == "v1"
    assert [p.id for p in places] == ["good"]
    assert places[0].lng == 18.07 and places[0].lat == 59.33
    assert places[0].size == 4


def test_out_of_range_coordinates_and_unsafe_ids_are_skipped():
    payload = _payload(
        {"id": "north", "title": "North", "geo": [10.0, 91.0], "size": 1},
        {"id": "south", "title": "South", "geo": [10.0, -91.0], "size": 1},
        {"id": "a/b", "title": "Slash", "geo": [10.0, 10.0], "size": 1},
        {"id": "ok", "title": "Ok", "geo": [10.0, 10.0], "size": -5},
    )
    _, places = parse_places(payload)
    assert [p.id for p in places] == ["ok"]
    assert places[0].size == 0


def test_non_dict_entries_are_ignored():
    _, places = parse_places(_payload("nope", None, {"id": "ok", "geo": [1, 2]}))
    assert [p.id for p in places] == ["ok"]


def test_get_json_reports_invalid_json_as_api_error(monkeypatch):
    client = RadioGardenClient(base_url="https://example.invalid")

    def fake_open(path, **kwargs):
        return 200, {}, b"<html>rate limited</html>"

    monkeypatch.setattr(client, "_open", fake_open)
    with pytest.raises(ApiError, match="invalid JSON"):
        client.get_json("/api/ara/content/places")


def test_get_json_rejects_non_object_payloads(monkeypatch):
    client = RadioGardenClient(base_url="https://example.invalid")
    monkeypatch.setattr(client, "_open", lambda path, **kwargs: (200, {}, b"[1, 2]"))
    with pytest.raises(ApiError, match="unexpected JSON"):
        client.get_json("/api/ara/content/places")


def test_stream_redirect_must_be_http(monkeypatch):
    client = RadioGardenClient(base_url="https://example.invalid")

    def fake_open(path, **kwargs):
        return 302, {"Location": "file:///etc/passwd"}, b""

    monkeypatch.setattr(client, "_open", fake_open)
    assert client.resolve_stream("abc") is None


def test_place_ids_are_quoted_in_request_paths(monkeypatch):
    client = RadioGardenClient(base_url="https://example.invalid")
    seen = []

    def fake_get_json(path):
        seen.append(path)
        return {"data": {"content": []}}

    monkeypatch.setattr(client, "get_json", fake_get_json)
    client.place_stations("a/b?c")
    assert seen == ["/api/ara/content/page/a%2Fb%3Fc/channels"]
