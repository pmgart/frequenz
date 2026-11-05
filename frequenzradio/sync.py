"""Populate the local catalog from the public API.

The sync is throttled (shared request interval across workers), resumable (a place
is only marked done after its stations are stored) and cancellable. Failed places
stay unsynced, so running the sync again retries exactly those places.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from .api import RadioGardenClient, Station
from .catalog import Catalog

log = logging.getLogger("frequenzradio.sync")


@dataclass
class SyncReport:
    places_total: int = 0
    places_done: int = 0
    places_failed: int = 0
    stations_saved: int = 0
    cancelled: bool = False
    elapsed_s: float = 0.0
    failures: list[str] = field(default_factory=list)


ProgressFn = Callable[[SyncReport], None]


def sync_places(client: RadioGardenClient, catalog: Catalog) -> int:
    """Refresh the place list (one request, ~1.9 MB)."""
    version, places = client.places()
    return catalog.upsert_places(places, version)


def sync_stations(
    client: RadioGardenClient,
    catalog: Catalog,
    *,
    workers: int = 4,
    limit: int | None = None,
    full: bool = False,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
    batch_size: int = 100,
) -> SyncReport:
    """Fetch the stations of every place that still needs them."""
    targets = catalog.places_to_sync(full=full, limit=limit)
    report = SyncReport(places_total=len(targets))
    started = time.monotonic()
    if not targets:
        report.elapsed_s = time.monotonic() - started
        return report

    def fetch(place_id: str) -> tuple[str, list[Station]]:
        return place_id, client.place_stations(place_id)

    pending: list[tuple[str, list[Station]]] = []
    pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="rg-sync")
    try:
        futures = {pool.submit(fetch, pid): pid for pid in targets}
        for future in as_completed(futures):
            if cancel is not None and cancel.is_set():
                report.cancelled = True
                break
            place_id = futures[future]
            try:
                _, stations = future.result()
            except Exception as exc:  # keep going; the place stays unsynced
                report.places_failed += 1
                if len(report.failures) < 5:
                    report.failures.append(f"{place_id}: {exc}")
                log.warning("place %s failed: %s", place_id, exc)
                continue
            pending.append((place_id, stations))
            report.places_done += 1
            if len(pending) >= batch_size:
                report.stations_saved += catalog.save_place_stations(pending)
                pending.clear()
            if progress is not None and report.places_done % 25 == 0:
                progress(report)
    finally:
        pool.shutdown(wait=not report.cancelled, cancel_futures=True)
        if pending:
            report.stations_saved += catalog.save_place_stations(pending)
    catalog.rebuild_search_index()
    if not report.cancelled:
        catalog.mark_synced()
    report.elapsed_s = time.monotonic() - started
    if progress is not None:
        progress(report)
    return report
