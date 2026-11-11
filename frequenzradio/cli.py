"""Command line entry point: ``frequenz [gui|sync|stats|search|doctor]``."""

from __future__ import annotations

import argparse
import logging
import signal
import sqlite3
import sys
import threading
import time

from . import __version__
from .api import ApiError
from .paths import catalog_path


def _bounded_int(minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(
                f"must be between {minimum} and {maximum}"
            )
        return number
    return parse


def _bounded_float(minimum: float, maximum: float):
    def parse(value: str) -> float:
        try:
            number = float(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(
                f"must be between {minimum} and {maximum}"
            )
        return number
    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="frequenz",
        description="FREQUENZ: a native, local and ad-free radio globe for Linux.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command")

    sync = sub.add_parser("sync", help="download or refresh the station catalog")
    sync.add_argument("--workers", type=_bounded_int(1, 32), default=4,
                      help="parallel requests (default 4)")
    sync.add_argument(
        "--min-interval", type=_bounded_float(0.0, 60.0), default=0.05,
        help="minimum seconds between requests across all workers (default 0.05)",
    )
    sync.add_argument("--limit", type=_bounded_int(1, 1_000_000), default=None,
                      help="only sync the first N places")
    sync.add_argument("--full", action="store_true", help="re-fetch every place")
    sync.add_argument("--places-only", action="store_true", help="refresh the place list only")

    sub.add_parser("stats", help="show catalog statistics")

    search = sub.add_parser("search", help="search stations in the local catalog")
    search.add_argument("query")
    search.add_argument("--limit", type=_bounded_int(1, 1000), default=20)

    sub.add_parser("doctor", help="check GTK, GStreamer and OpenGL prerequisites")
    build_globe_parser = sub.add_parser(
        "build-globe", help="download Natural Earth data and build the globe's vector map (needs shapely)"
    )
    build_globe_parser.add_argument("--workers", type=_bounded_int(1, 8), default=None,
                                    help="parallel processes (default: up to 4)")
    sub.add_parser("gui", help="start the desktop app (default)")
    return parser


def _cmd_build_globe(args: argparse.Namespace) -> int:
    from .paths import globe_dir, naturalearth_dir

    try:
        from .globe_build import build_globe, fetch_sources
    except ImportError as exc:
        print(
            f"building the globe needs shapely ({exc}).\n"
            "  pip install 'frequenzradio[build]'\n"
            "  or the distribution package: sudo dnf install python3-shapely "
            "/ sudo apt install python3-shapely",
            file=sys.stderr,
        )
        return 1

    def log(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    fetch_sources(naturalearth_dir(), log=log)
    log(f"building the vector map into {globe_dir()}")
    manifest = build_globe(naturalearth_dir(), globe_dir(), workers=args.workers, log=log)
    log(f"done in {manifest['seconds']}s: {len(manifest['layers'])} layers")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    from .api import RadioGardenClient
    from .catalog import Catalog
    from .sync import SyncReport, sync_places, sync_stations

    client = RadioGardenClient(min_interval=args.min_interval)
    catalog = Catalog(catalog_path())
    cancel = threading.Event()

    def on_sigint(signum, frame):  # noqa: ARG001
        if not cancel.is_set():
            print("\nStopping after in-flight requests; progress is kept.", file=sys.stderr)
        cancel.set()

    signal.signal(signal.SIGINT, on_sigint)

    print(f"Catalog: {catalog.path}", file=sys.stderr)
    count = sync_places(client, catalog)
    print(f"Places in catalog: {count}", file=sys.stderr)
    if args.places_only:
        return 0

    def progress(report: SyncReport) -> None:
        rate = report.places_done / max(0.001, time.monotonic() - started)
        remaining = report.places_total - report.places_done - report.places_failed
        eta = remaining / rate if rate > 0 else 0
        print(
            f"  places {report.places_done + report.places_failed}/{report.places_total}"
            f"  stations saved {report.stations_saved}  failed {report.places_failed}"
            f"  {rate:.1f} places/s  ETA {eta / 60:.1f} min",
            file=sys.stderr,
            flush=True,
        )

    started = time.monotonic()
    report = sync_stations(
        client, catalog, workers=args.workers, limit=args.limit, full=args.full,
        progress=progress, cancel=cancel,
    )
    state = "cancelled" if report.cancelled else "done"
    print(
        f"Sync {state}: {report.places_done} places, {report.stations_saved} stations, "
        f"{report.places_failed} failed, {report.elapsed_s:.0f}s",
        file=sys.stderr,
    )
    for failure in report.failures:
        print(f"  failed: {failure}", file=sys.stderr)
    stats = catalog.stats()
    print(
        f"Catalog now: {stats.places_synced}/{stats.places} places synced, "
        f"{stats.stations} stations",
        file=sys.stderr,
    )
    catalog.close()
    if report.cancelled:
        return 130
    return 0 if not report.failures else 1


def _cmd_stats() -> int:
    from .catalog import Catalog

    catalog = Catalog(catalog_path())
    stats = catalog.stats()
    print(f"catalog:        {catalog.path}")
    print(f"places:         {stats.places} ({stats.places_synced} with stations synced)")
    print(f"stations:       {stats.stations}")
    print(f"searchable:     {stats.search_rows} (in the search index)")
    print(f"favorites:      {stats.favorites}")
    print(f"places version: {stats.places_version}")
    print(f"last sync:      {stats.last_sync_at}")
    catalog.close()
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    from .catalog import Catalog

    catalog = Catalog(catalog_path())
    rows = catalog.search(args.query, args.limit)
    for row in rows:
        place = row["place_title"] or ""
        country = row["country"] or ""
        print(f"{row['id']:<10} {row['title']:<40} {place} ({country})")
    if not rows:
        print("no matches")
    catalog.close()
    return 0


def _cmd_doctor() -> int:
    from .doctor import run_doctor

    return run_doctor()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.command == "sync":
            return _cmd_sync(args)
        if args.command == "stats":
            return _cmd_stats()
        if args.command == "search":
            return _cmd_search(args)
        if args.command == "doctor":
            return _cmd_doctor()
        if args.command == "build-globe":
            return _cmd_build_globe(args)
    except (ApiError, sqlite3.Error, OSError, ValueError) as exc:
        if args.verbose:
            logging.exception("command failed")
        print(f"frequenz: {exc}", file=sys.stderr)
        return 1
    from .app import run_gui

    return run_gui(["frequenz"])
