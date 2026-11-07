#!/usr/bin/env python3
"""Visual, behaviour and performance check of the globe's zoom levels (manual; needs a display).

It starts the real desktop app, flies through every zoom level, takes a screenshot at each and
reports the detail level, the zoom readout, the zoom-step controls, GL errors and render times.
Screenshots go to $FREQUENZ_GLOBE_OUT (default /tmp/frequenz-globe).

    .venv/bin/python tests/globe_zoom_check.py
"""

from __future__ import annotations

import math
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk  # noqa: E402
from OpenGL import GL as gl  # noqa: E402

from frequenzradio import geo  # noqa: E402
from frequenzradio.app import FrequenzApp  # noqa: E402
from frequenzradio.globe import GlobeView  # noqa: E402

OUT = Path(os.environ.get("FREQUENZ_GLOBE_OUT", "/tmp/frequenz-globe"))
OUT.mkdir(parents=True, exist_ok=True)
RESULTS: list[tuple[str, bool]] = []
RENDER_MS: list[tuple[int, float]] = []  # (detail level, render time in ms incl. glFinish)
GL_ERRORS: list[int] = []

# Time every render (including the GPU work, via glFinish) and record GL errors.
_original_render = GlobeView._on_render


def _timed_render(self, area, context):
    started = time.perf_counter()
    result = _original_render(self, area, context)
    gl.glFinish()
    RENDER_MS.append((geo.level_of_detail(self.dist), (time.perf_counter() - started) * 1000.0))
    error = gl.glGetError()
    if error:
        GL_ERRORS.append(int(error))
    return result


GlobeView._on_render = _timed_render

app = FrequenzApp()


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def snapshot(window, name: str) -> None:
    paintable = Gtk.WidgetPaintable.new(window)
    snap = Gtk.Snapshot.new()
    paintable.snapshot(snap, window.get_width(), window.get_height())
    node = snap.to_node()
    if node is None:
        print(f"  snapshot {name} skipped: no render node", flush=True)
        return
    texture = window.get_native().get_renderer().render_texture(node, None)
    texture.save_to_png(str(OUT / name))
    print(f"  snapshot {OUT / name}", flush=True)


def render_report(label: str, lod: int) -> str:
    samples = [ms for level, ms in RENDER_MS[-120:] if level == lod]
    if not samples:
        return f"no renders at detail {lod}"
    return f"detail {lod}: median {statistics.median(samples):.2f} ms, worst {max(samples):.2f} ms over {len(samples)} frames"


def script(window):
    """Yield (wait_ms, callable) steps; each step runs after the previous wait."""
    globe = window.globe
    close_level = geo.ZOOM_LEVELS[2].distance
    region, country, city = (geo.ZOOM_LEVELS[i].distance for i in (3, 4, 5))
    stockholm = (18.07, 59.33)

    def vector_map_ready():
        check("vector map is loaded for the globe", globe.vector_map_ready)
        check("GL context is ready", globe._gl_ready)

    yield 2500, vector_map_ready

    def overview():
        globe.reset_view()

    yield 3000, overview

    def overview_done():
        snapshot(window, "1-globe-greenwich.png")
        check("globe level shows the full map", geo.level_of_detail(globe.dist) == 0, f"dist {globe.dist:.2f}")
        print("  " + render_report("globe", 0), flush=True)
        print(f"  zoom slider: {window.zoom_scale.get_value():.3f}", flush=True)

    yield 200, overview_done

    def pacific_day():
        globe.focus_place(-143.0, -15.0, zoom=geo.DEFAULT_DISTANCE)  # the sun is over the Pacific now

    yield 3000, pacific_day

    def pacific_done():
        snapshot(window, "2-globe-daylight-pacific.png")

    yield 200, pacific_done

    def close_globe():
        globe.focus_place(*stockholm, zoom=close_level)

    yield 3000, close_globe

    def close_done():
        snapshot(window, "3-close-globe-stockholm.png")
        check("close globe uses the 50 km data", geo.level_of_detail(globe.dist) == 1, f"dist {globe.dist:.3f}")
        print("  " + render_report("close globe", 1), flush=True)

    yield 200, close_done

    def region_level():
        globe.focus_place(*stockholm, zoom=region)

    yield 3000, region_level

    def region_done():
        snapshot(window, "4-region-stockholm.png")
        check("region level uses the full 10 m data", geo.level_of_detail(globe.dist) == 2, f"dist {globe.dist:.3f}")
        print("  " + render_report("region", 2), flush=True)
        print(f"  zoom slider: {window.zoom_scale.get_value():.3f}", flush=True)

    yield 200, region_done

    def country_level():
        globe.focus_place(*stockholm, zoom=country)

    yield 3000, country_level

    def country_done():
        snapshot(window, "5-country-stockholm.png")
        print("  " + render_report("country", 2), flush=True)

    yield 200, country_done

    def city_level():
        globe.focus_place(*stockholm, zoom=city)

    yield 3000, city_level

    def city_done():
        snapshot(window, "6-city-stockholm.png")
        check("city level reaches 100 km altitude", abs(geo.altitude_km(globe.dist) - 100.0) < 1.0,
              f"altitude {geo.altitude_km(globe.dist):.1f} km")
        print("  " + render_report("city", 2), flush=True)
        print(f"  zoom slider: {window.zoom_scale.get_value():.3f}", flush=True)

    yield 200, city_done

    def step_out():
        globe.zoom_step(-1)

    yield 2500, step_out

    def step_out_done():
        check("minus steps one level out (City -> Country)", abs(globe.dist - country) < 1e-3, f"dist {globe.dist:.4f}")

    yield 200, step_out_done

    def step_in():
        globe.zoom_step(1)

    yield 2500, step_in

    def step_in_done():
        check("plus steps one level in (Country -> City)", abs(globe.dist - city) < 1e-3, f"dist {globe.dist:.4f}")

    yield 200, step_in_done

    def scroll_out():
        globe.zoom_by(math.exp(0.09 * 4))  # a continuous scroll, not a level step

    yield 1500, scroll_out

    def scroll_done():
        expected = geo.clamp_distance(city * math.exp(0.09 * 4))
        check("wheel zoom is continuous (not stepped)", abs(globe.dist - expected) < 1e-6,
              f"dist {globe.dist:.4f}")
        check("GL reported no errors", not GL_ERRORS, f"errors {GL_ERRORS[:5]}")
        print(f"  {len(RENDER_MS)} frames rendered in total", flush=True)

    yield 200, scroll_done

    def finish():
        failed = [name for name, ok in RESULTS if not ok]
        print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed", flush=True)
        if failed:
            print("failed: " + ", ".join(failed), flush=True)
        app.quit()

    yield 100, finish


def _run_steps(window) -> None:
    steps = script(window)

    def advance():
        try:
            wait, action = next(steps)
        except StopIteration:
            return False
        action()
        GLib.timeout_add(wait, advance_later)
        return False

    def advance_later():
        try:
            wait, action = next(steps)
        except StopIteration:
            return False
        action()
        GLib.timeout_add(wait, advance_later)
        return False

    GLib.timeout_add(1000, advance)


def main() -> int:
    original_activate = app._on_activate

    def activate_and_script(application):
        original_activate(application)
        _run_steps(app.window)

    app.disconnect_by_func(app._on_activate)
    app.connect("activate", activate_and_script)
    code = app.run(["frequenz-globe-check"])
    failed = [name for name, ok in RESULTS if not ok]
    return 1 if failed or GL_ERRORS else code


if __name__ == "__main__":
    raise SystemExit(main())
