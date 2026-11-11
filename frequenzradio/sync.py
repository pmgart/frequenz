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


class _SyncCancelled(Exception):
    """Raised inside a worker when the caller cancelled the run."""


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
        if cancel is not None and cancel.is_set():
            raise _SyncCancelled
        return place_id, client.place_stations(place_id)

    def flush(batch: list[tuple[str, list[Station]]]) -> int:
        """Write one batch; on failure retry place by place so one bad row cannot lose 100."""
        try:
            return catalog.save_place_stations(batch)
        except Exception as exc:
            log.warning("batch write failed for %d places: %s", len(batch), exc)
        saved = 0
        for item in batch:
            try:
                saved += catalog.save_place_stations([item])
            except Exception as exc:
                report.places_failed += 1
                if len(report.failures) < 5:
                    report.failures.append(f"{item[0]}: {exc}")
                log.warning("place %s could not be stored: %s", item[0], exc)
        return saved

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
            except _SyncCancelled:
                report.cancelled = True
                break
            except Exception as exc:  # keep going; the place stays unsynced
                report.places_failed += 1
                if len(report.failures) < 5:
                    report.failures.append(f"{place_id}: {exc}")
                log.warning("place %s failed: %s", place_id, exc)
                continue
            pending.append((place_id, stations))
            report.places_done += 1
            if len(pending) >= batch_size:
                report.stations_saved += flush(pending)
                pending.clear()
            if progress is not None and report.places_done % 25 == 0:
                progress(report)
    finally:
        # Wait for in-flight requests (bounded by the client timeout) so a cancelled
        # sync cannot leave workers writing after the caller closed its catalog.
        pool.shutdown(wait=True, cancel_futures=True)
        if pending:
            try:
                report.stations_saved += flush(pending)
            except Exception as exc:  # never mask the original exception
                log.warning("final batch could not be stored: %s", exc)
    # The FTS triggers keep the search index current; no whole-index rebuild per run.
    if not report.cancelled and report.places_failed == 0:
        catalog.mark_synced()
    report.elapsed_s = time.monotonic() - started
    if progress is not None:
        progress(report)
    return report
