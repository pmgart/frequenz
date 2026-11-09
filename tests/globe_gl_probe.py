#!/usr/bin/env python3
"""Manual check of the globe's OpenGL context and frame time: run it in a desktop session.

usage: .venv/bin/python tests/globe_gl_probe.py [seconds]   (default 12)

Prints the GL strings, the point size range and the render-callback timing, then quits.
The globe map must be built first (frequenz build-globe). For a window snapshot, use the app's
own hook: FREQUENZ_SNAPSHOT=/tmp/x.png FREQUENZ_SNAPSHOT_AFTER=<seconds below the probe time>.
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import the globe first: it sets PyOpenGL's platform (EGL on Wayland) before OpenGL loads.
from frequenzradio.globe import GlobeView  # noqa: E402
from frequenzradio.app import FrequenzApp  # noqa: E402
from OpenGL import GL as gl  # noqa: E402
from gi.repository import GLib  # noqa: E402

SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
info: dict[str, str] = {}
frame_times: list[float] = []
_original_render = GlobeView._on_render


def _text(enum: int) -> str:
    raw = gl.glGetString(enum)
    return raw.decode() if raw else "n/a"


def _read_context() -> None:
    info["GL_VERSION"] = _text(gl.GL_VERSION)
    info["GLSL"] = _text(gl.GL_SHADING_LANGUAGE_VERSION)
    info["renderer"] = _text(gl.GL_RENDERER)
    try:
        low, high = gl.glGetFloatv(gl.GL_POINT_SIZE_RANGE)
        info["point size range"] = f"{low:g} to {high:g}"
    except Exception as exc:  # noqa: BLE001 - GLES may not expose this query
        info["point size range"] = f"n/a ({type(exc).__name__})"


def _probed_render(self, area, context) -> bool:
    first = not info
    started = time.perf_counter()
    result = _original_render(self, area, context)
    if first:
        _read_context()  # the context is current inside the render callback
    frame_times.append(time.perf_counter() - started)
    return result


def _finish(app) -> bool:
    for key, value in info.items():
        print(f"{key}: {value}")
    if frame_times:
        ms = sorted(t * 1000 for t in frame_times)
        p95 = ms[min(len(ms) - 1, int(0.95 * len(ms)))]
        print(f"frames timed: {len(ms)}")
        print(f"globe render callback: median {statistics.median(ms):.2f} ms, 95th percentile {p95:.2f} ms")
    else:
        print("frames timed: 0 (the globe drew no frames; look for '3D globe disabled' in the log)")
    app.quit()
    return False


def _on_activate(app) -> None:
    app.window.set_auto_rotate(True)  # the globe draws frames while it animates
    GLib.timeout_add_seconds(SECONDS, _finish, app)


GlobeView._on_render = _probed_render
app = FrequenzApp()
app.connect("activate", _on_activate)
sys.exit(app.run(["frequenz"]))
