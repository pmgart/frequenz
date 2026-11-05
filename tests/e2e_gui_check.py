#!/usr/bin/env python3
"""End-to-end check of the running desktop app (manual; needs a display, network and the catalog).

It starts the real GTK application and drives the actual window: plays real streams,
pauses and resumes, moves to the next station, toggles a favorite, searches, plays a
random station and verifies that globe picking hits the place it projects to.
Screenshots are written to $FREQUENZ_E2E_OUT (default /tmp/frequenz-e2e).

    .venv/bin/python tests/e2e_gui_check.py

Live radio is unreliable: some stations take long to start or are offline. The script
therefore tries the first few stations of a place until one plays, and it checks
pause/resume on that verified station only.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gtk  # noqa: E402

from frequenzradio import geo  # noqa: E402
from frequenzradio.app import FrequenzApp  # noqa: E402

OUT = Path(os.environ.get("FREQUENZ_E2E_OUT", "/tmp/frequenz-e2e"))
OUT.mkdir(parents=True, exist_ok=True)
RESULTS: list[tuple[str, bool]] = []
PLAYING_STATES = ("playing", "buffering")

app = FrequenzApp()


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f" — {detail}" if detail else ""), flush=True)


def snapshot(window, name: str) -> None:
    paintable = Gtk.WidgetPaintable.new(window)
    snap = Gtk.Snapshot.new()
    paintable.snapshot(snap, window.get_width(), window.get_height())
    node = snap.to_node()
    if node is None:
        print(f"  snapshot {name} skipped: window had no render node yet", flush=True)
        return
    texture = window.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(str(OUT / name))
    print(f"  snapshot {OUT / name}", flush=True)


def lng_lat(win, index: int) -> tuple[float, float]:
    place = win.catalog.place(win.places.ids[index])
    return place["lng"], place["lat"]


def check_pick(win, index: int, label: str) -> None:
    """Picking must return a place whose projection lies within 4 px of the cursor.

    Clusters can contain several places within a few pixels; the picker prefers bigger places
    only within about 2 px, so an exact-index match is not required.
    """
    width, height = win.globe.get_width(), win.globe.get_height()
    screen, visible = geo.project(win.places.xyz[index:index + 1],
                                  geo.model_matrix(win.globe.yaw, win.globe.pitch),
                                  win.globe.dist, width, height)
    if not visible[0]:
        win.globe.focus_place(*lng_lat(win, index), zoom=3.3)
        return
    x, y = float(screen[0][0]), float(screen[0][1])
    picked = win.globe._pick(x, y)
    if picked is None:
        check(label, False, "nothing picked at the projected position")
        return
    screen2, _ = geo.project(win.places.xyz[picked:picked + 1], geo.model_matrix(win.globe.yaw, win.globe.pitch),
                             win.globe.dist, width, height)
    distance = float(((screen2[0][0] - x) ** 2 + (screen2[0][1] - y) ** 2) ** 0.5)
    check(label, distance <= 4.0, f"target {index}, picked {picked} at {distance:.1f}px")


def script(win):
    """Yield (delay_ms_after_step, callable) steps, executed one at a time."""
    catalog = win.catalog
    place_index = win.playing_index if win.playing_index is not None else 0
    place_id = win.places.ids[place_index]
    ids = [r["id"] for r in catalog.stations_in_place(place_id)][:10]
    check("place has stations", len(ids) >= 2, f"{len(ids)} stations at {win.places.titles[place_index]}")

    # Try the first few stations until one actually produces audio.
    started = None
    for position, candidate in enumerate(ids[:3]):
        yield 22000, (lambda c=candidate: win.play_station(c, queue=ids))
        if win.player.state in PLAYING_STATES and (win.player.position_seconds() or 0.0) > 1.0:
            started = position
            break
        print(f"  station {candidate} did not start (state={win.player.state}); trying the next one", flush=True)
    if started is None:
        check("one of the first stations starts playing", False, "none of the first three started")
        yield 300, win.player.stop
        app.quit()
        return
    ids = ids[started:]
    check("stream is playing", True, f"state={win.player.state} position={win.player.position_seconds():.1f}s "
          f"title={win.player.title!r}")
    check("play_station sets current station", win.current_row["id"] == ids[0])

    def playing_snapshot():
        snapshot(win, "1-playing.png")

    yield 400, playing_snapshot

    def pause():
        win.toggle_play()

    yield 1500, pause

    def paused_ok():
        check("pause stops playback state", win.player.state == "paused", f"state={win.player.state}")
        win.toggle_play()

    yield 22000, paused_ok

    def resumed_ok():
        pos = win.player.position_seconds() or 0.0
        check("resume plays again", win.player.state in PLAYING_STATES,
              f"state={win.player.state} position={pos:.1f}s")

    yield 500, resumed_ok

    def next_station():
        before = win.queue_index
        win.play_relative(1)
        expected_index = (before + 1) % len(win.queue)
        check("next moves the queue", win.queue_index == expected_index and win.current_row["id"] == ids[1],
              f"{before} -> {win.queue_index}")

    yield 800, next_station

    def favorite_roundtrip():
        before = catalog.is_favorite(ids[1])
        win.toggle_current_favorite()
        after_on = catalog.is_favorite(ids[1])
        win.toggle_current_favorite()
        after_off = catalog.is_favorite(ids[1])
        check("favorite toggles on and off", (before, after_on, after_off) == (False, True, False),
              f"{before}->{after_on}->{after_off}")

    yield 500, favorite_roundtrip

    def search_now():
        win.search.set_text("jazz")

    yield 1200, search_now

    def search_ok():
        rows = len(win._sidebar_rows)
        check("search fills the station list", win.sidebar_mode == "search" and rows > 0, f"{rows} results")
        snapshot(win, "2-search.png")
        win.search.set_text("")

    yield 800, search_ok

    def random_now():
        win.play_random()

    yield 7000, random_now

    def random_ok():
        check("random station plays", win.current_row is not None and win.player.uri is not None,
              win.current_row["title"] if win.current_row is not None else "")
        check("globe marks the playing place", win.globe.playing is not None)
        snapshot(win, "3-random.png")

    yield 500, random_ok

    def picking():
        idx = win.playing_index
        if idx is None:
            check("picking test has a playing place", False)
            return
        check_pick(win, idx, "globe picking")

    yield 2500, picking

    def picking_after_turn():
        idx = win.playing_index
        if idx is not None:
            check_pick(win, idx, "globe picking after turning")

    yield 800, picking_after_turn

    def select_place():
        idx = win.playing_index
        win._on_globe_select(idx)
        listed = len(win._sidebar_rows)
        check("selecting a place lists its stations", win.sidebar_mode == "place"
              and listed == len(catalog.stations_in_place(win.places.ids[idx])), f"{listed} listed")

    yield 800, select_place

    def place_snapshot():
        snapshot(win, "4-place.png")

    yield 500, place_snapshot

    def favorites_view():
        win.favorites_button.set_active(True)
        check("favorites view opens", win.sidebar_mode == "favorites")
        win.favorites_button.set_active(False)

    yield 500, favorites_view

    def finish():
        win.player.stop()
        failed = [name for name, ok in RESULTS if not ok]
        print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed", flush=True)
        app.quit()

    yield 300, finish


def start_when_ready() -> bool:
    if app.window is None:
        return GLib.SOURCE_CONTINUE
    steps = script(app.window)

    def advance() -> bool:
        try:
            delay, fn = next(steps)
        except StopIteration:
            return GLib.SOURCE_REMOVE
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - report and keep going
            check("step raised " + type(exc).__name__, False, str(exc))
        GLib.timeout_add(delay, advance)
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(800, advance)
    return GLib.SOURCE_REMOVE


GLib.timeout_add(500, start_when_ready)
rc = app.run([])
failed = [name for name, ok in RESULTS if not ok]
sys.exit(1 if failed or rc else 0)
