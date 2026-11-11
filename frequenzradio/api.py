"""Read-only client for the public Radio Garden endpoints used by the web app.

Endpoints verified against the live service (see docs/REVERSE_ENGINEERING.md):

* ``/api/ara/content/places``                 all places with ``geo=[lng, lat]`` and ``size``
* ``/api/ara/content/page/{place}/channels``  stations (channels) of one place
* ``/api/ara/content/channel/{station}``      station detail (website, social links)
* ``/api/ara/content/listen/{station}/channel.mp3``  302 redirect to the live stream

Only the data needed for a local catalog is requested. No ad, consent or account
endpoints are used.
"""

from __future__ import annotations

import json
import random
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from . import __version__
from .text import clean_text

BASE_URL = "https://radio.garden"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/124.0 Safari/537.36 Frequenz/{__version__}"
)
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
# The /places body is about 2 MB. Cap reads so a broken upstream cannot exhaust memory.
MAX_BODY = 16 * 1024 * 1024


class ApiError(RuntimeError):
    """An endpoint could not be fetched after the configured retries."""


def _retry_after_seconds(value: str | None) -> float:
    """Parse ``Retry-After`` (delta-seconds or HTTP-date), clamped to one minute."""
    if not value:
        return 0.0
    value = value.strip()
    if value.isdigit():
        return min(float(value), 60.0)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return 0.0
    if when is None:
        return 0.0
    return max(0.0, min(when.timestamp() - time.time(), 60.0))


def _read_body(response, path: str) -> bytes:
    """Read a response body, refusing anything above MAX_BODY."""
    length = response.headers.get("Content-Length")
    if length and length.isdigit() and int(length) > MAX_BODY:
        raise ApiError(f"response too large for {path}: {length} bytes")
    body = response.read(MAX_BODY + 1)
    if len(body) > MAX_BODY:
        raise ApiError(f"response too large for {path} (above {MAX_BODY} bytes)")
    return body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return redirects to the caller instead of following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


@dataclass(frozen=True)
class Place:
    id: str
    title: str
    country: str
    lng: float
    lat: float
    size: int  # number of stations Radio Garden lists for this place
    boost: bool
    url: str


@dataclass(frozen=True)
class Station:
    id: str
    slug: str
    title: str
    url: str
    place_id: str | None
    place_title: str | None
    country: str | None
    country_id: str | None
    stream_host: str | None
    secure: bool
    preroll: bool  # flagged by the API; the web player plays an ad first (inferred); this app never does

    @property
    def listen_path(self) -> str:
        return f"/api/ara/content/listen/{self.id}/channel.mp3"


def parse_places(payload: dict) -> tuple[str | None, list[Place]]:
    """Parse the ``/places`` payload. Malformed entries are skipped, not fatal."""
    data = payload.get("data", payload)
    version = data.get("version")
    places: list[Place] = []
    for raw in data.get("list", []) or []:
        if not isinstance(raw, dict):
            continue
        try:
            geo = raw.get("geo") or []
            if len(geo) < 2 or geo[0] is None or geo[1] is None or not raw.get("id"):
                continue
            lng = float(geo[0])
            lat = float(geo[1])
            if not (-180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0):
                continue
            place_id = str(raw["id"])
            if any(ch in place_id for ch in "/?#"):
                continue
            size = int(raw.get("size") or 0)
            places.append(
                Place(
                    id=place_id,
                    title=clean_text(raw.get("title")),
                    country=clean_text(raw.get("country")),
                    lng=lng,
                    lat=lat,
                    size=max(0, size),
                    boost=bool(raw.get("boost")),
                    url=str(raw.get("url") or ""),
                )
            )
        except (TypeError, ValueError):
            # One bad row must not discard the other ~2000 places.
            continue
    return version, places


def station_from_page(page: dict) -> Station | None:
    """Build a Station from a ``content.items[].page`` object of type ``channel``."""
    url = page.get("url") or ""
    parts = [p for p in urllib.parse.urlsplit(url).path.split("/") if p]
    # Expected shape: /listen/{slug}/{station-id}
    if len(parts) < 2 or parts[0] != "listen":
        return None
    station_id = urllib.parse.unquote(parts[-1])
    if not station_id or any(ch in station_id for ch in "/?#"):
        return None
    slug = parts[1] if len(parts) >= 3 else ""
    place = page.get("place") or {}
    country = page.get("country") or {}
    return Station(
        id=station_id,
        slug=slug,
        title=clean_text(page.get("title")) or station_id,
        url=url,
        place_id=place.get("id"),
        place_title=clean_text(place.get("title")) or None,
        country=clean_text(country.get("title")) or None,
        country_id=country.get("id"),
        stream_host=page.get("stream"),
        secure=bool(page.get("secure")),
        preroll=bool(page.get("preroll")),
    )


def parse_place_channels(payload: dict) -> list[Station]:
    """Parse ``/page/{place}/channels`` into unique stations (order preserved)."""
    data = payload.get("data", payload)
    seen: set[str] = set()
    stations: list[Station] = []
    for block in data.get("content", []) or []:
        for item in block.get("items", []) or []:
            page = item.get("page") or {}
            if page.get("type") != "channel":
                continue
            station = station_from_page(page)
            if station is not None and station.id not in seen:
                seen.add(station.id)
                stations.append(station)
    return stations


class RadioGardenClient:
    """Small urllib-based client with throttling and bounded retries.

    Thread-safe: the throttle is shared by all threads, so the request rate stays
    polite even when a sync uses several workers.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        user_agent: str = USER_AGENT,
        timeout: float = 20.0,
        min_interval: float = 0.0,
        max_retries: int = 4,
        retry_delay: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._throttle_lock = threading.Lock()
        self._last_request = 0.0
        self._follow = urllib.request.build_opener()
        self._no_follow = urllib.request.build_opener(_NoRedirect)

    # -- transport ---------------------------------------------------------------
    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        with self._throttle_lock:
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def _open(self, path: str, *, follow: bool = True, accept: str = "application/json"):
        url = path if path.startswith("http") else self.base_url + path
        opener = self._follow if follow else self._no_follow
        attempt = 0
        while True:
            self._throttle()
            request = urllib.request.Request(
                url, headers={"User-Agent": self.user_agent, "Accept": accept}
            )
            retry_after = 0.0
            try:
                with opener.open(request, timeout=self.timeout) as response:
                    return response.status, dict(response.headers), _read_body(response, path)
            except urllib.error.HTTPError as exc:
                if not follow and exc.code in REDIRECT_STATUS:
                    return exc.code, dict(exc.headers), b""
                retry_after = _retry_after_seconds(exc.headers.get("Retry-After"))
                if exc.code not in RETRYABLE_STATUS or attempt >= self.max_retries:
                    raise ApiError(f"HTTP {exc.code} for {path}") from exc
            except (urllib.error.URLError, OSError) as exc:  # includes timeouts
                if attempt >= self.max_retries:
                    raise ApiError(f"{type(exc).__name__} for {path}: {exc}") from exc
            attempt += 1
            # Exponential backoff with jitter; never a tight retry loop. Honour Retry-After.
            backoff = min(30.0, self.retry_delay * 2.0**attempt) * (0.5 + random.random() / 2)
            time.sleep(max(backoff, retry_after))

    def get_json(self, path: str) -> dict:
        _, _, body = self._open(path)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(f"invalid JSON from {path}") from exc
        if not isinstance(payload, dict):
            raise ApiError(f"unexpected JSON from {path}: {type(payload).__name__}")
        return payload

    # -- endpoints ---------------------------------------------------------------
    def places(self) -> tuple[str | None, list[Place]]:
        return parse_places(self.get_json("/api/ara/content/places"))

    def place_stations(self, place_id: str) -> list[Station]:
        quoted = urllib.parse.quote(str(place_id), safe="")
        return parse_place_channels(self.get_json(f"/api/ara/content/page/{quoted}/channels"))

    def station_detail(self, station_id: str) -> dict:
        quoted = urllib.parse.quote(str(station_id), safe="")
        data = self.get_json(f"/api/ara/content/channel/{quoted}")
        return data.get("data", data)

    def resolve_stream(self, station_id: str) -> str | None:
        """Return the direct stream URL behind a station's ``listen`` redirect."""
        quoted = urllib.parse.quote(str(station_id), safe="")
        path = f"/api/ara/content/listen/{quoted}/channel.mp3"
        status, headers, _ = self._open(path, follow=False, accept="*/*")
        if status in REDIRECT_STATUS:
            location = headers.get("Location") or headers.get("location")
            if location:
                joined = urllib.parse.urljoin(self.base_url + path, location)
                parsed = urllib.parse.urlsplit(joined)
                if parsed.scheme in ("http", "https") and parsed.hostname:
                    return joined
        return None
