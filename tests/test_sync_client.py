"""HTTP client and sync tests against a local fake Radio Garden server (no internet needed)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from frequenzradio.api import ApiError, RadioGardenClient, parse_place_channels
from frequenzradio.catalog import Catalog
from frequenzradio.sync import sync_places, sync_stations

FIXTURES = Path(__file__).parent / "fixtures"
PLACES = json.loads((FIXTURES / "places_sample.json").read_text(encoding="utf-8"))["data"]["list"]
VILLA = "Qx7vLm2K"  # has one station in the fixtures
FAIL_ID = PLACES[1]["id"]  # always answers 500 until the test heals it
RETRY_ID = PLACES[2]["id"]  # answers 429 once, then succeeds


class FakeRadioGarden(BaseHTTPRequestHandler):
    server_version = "FakeRadioGarden/1"

    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, code, body=b"", headers=None, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server API
        srv = self.server
        srv.hits.append((self.path, self.headers.get("User-Agent", "")))
        if self.path == "/api/ara/content/places":
            return self._send(200, (FIXTURES / "places_sample.json").read_bytes())
        if self.path.startswith("/api/ara/content/page/") and self.path.endswith("/channels"):
            place = self.path.split("/")[5]
            if place in srv.failing:
                return self._send(500, b'{"error":"boom"}')
            if place == RETRY_ID and srv.throttled_once:
                srv.throttled_once = False
                return self._send(429, b'{"error":"slow down"}')
            if place == VILLA:
                return self._send(200, (FIXTURES / "place_channels_sample.json").read_bytes())
            return self._send(200, json.dumps({"data": {"content": []}}).encode())
        if self.path.startswith("/api/ara/content/listen/"):
            target = f"http://127.0.0.1:{srv.server_port}/stream/live.mp3"
            return self._send(302, b"", {"Location": target}, content_type="text/plain")
        if self.path.startswith("/api/ara/content/channel/"):
            return self._send(200, (FIXTURES / "channel_detail_sample.json").read_bytes())
        return self._send(404, b'{"error":"not found"}')


@pytest.fixture()
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeRadioGarden)
    httpd.hits = []
    httpd.failing = {FAIL_ID}
    httpd.throttled_once = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def make_client(base: str, **kwargs) -> RadioGardenClient:
    return RadioGardenClient(base_url=base, min_interval=0.0, max_retries=3, retry_delay=0.001, **kwargs)


def test_places_request_sends_identifying_user_agent(server):
    httpd, base = server
    version, places = make_client(base).places()
    assert version == "sample-1"
    assert len(places) == 40
    assert any("Frequenz" in ua for path, ua in httpd.hits if path.endswith("/places"))


def test_429_is_retried_and_then_succeeds(server):
    httpd, base = server
    client = make_client(base)
    httpd.throttled_once = True
    result = client.place_stations(RETRY_ID)
    assert result == []  # empty but successful after one retry
    attempts = [p for p, _ in httpd.hits if p.endswith(f"/page/{RETRY_ID}/channels")]
    assert len(attempts) == 2


def test_persistent_server_error_raises_after_retries(server):
    _, base = server
    with pytest.raises(ApiError):
        make_client(base).place_stations(FAIL_ID)


def test_resolve_stream_returns_the_redirect_target(server):
    _, base = server
    station = parse_place_channels(json.loads((FIXTURES / "place_channels_sample.json").read_text()))[0]
    target = make_client(base).resolve_stream(station.id)
    assert target.startswith("http://127.0.0.1:") and target.endswith("/stream/live.mp3")


def test_station_detail_is_read_from_the_channel_endpoint(server):
    _, base = server
    detail = make_client(base).station_detail("Km7d_Tq3")
    assert detail["website"] == "https://www.example.com/orbita-fm"


def test_sync_is_resumable_and_isolates_failures(server, tmp_path):
    httpd, base = server
    client = make_client(base)
    catalog = Catalog(tmp_path / "catalog.sqlite")
    try:
        assert sync_places(client, catalog) == 40  # the entry without coordinates is skipped

        report = sync_stations(client, catalog, workers=4)
        assert report.places_total == 40
        assert report.places_failed == 1
        assert report.places_done == 39
        assert report.stations_saved == 1
        assert catalog.stats().places_synced == 39
        assert FAIL_ID in catalog.places_to_sync(full=False)  # failed place stays queued

        httpd.failing.clear()  # the server recovers; a second run picks up only the missing place
        report2 = sync_stations(client, catalog, workers=2)
        assert report2.places_total == 1
        assert report2.places_failed == 0
        assert catalog.stats().places_synced == 40
        assert [r["id"] for r in catalog.search("orbi")] == ["Km7d_Tq3"]
    finally:
        catalog.close()


def test_sync_can_be_cancelled_before_all_places_finish(server, tmp_path):
    _, base = server
    client = make_client(base)
    catalog = Catalog(tmp_path / "catalog.sqlite")
    try:
        sync_places(client, catalog)
        cancel = threading.Event()
        cancel.set()
        report = sync_stations(client, catalog, workers=2, cancel=cancel)
        assert report.cancelled is True
        assert report.places_done + report.places_failed < report.places_total
    finally:
        catalog.close()
