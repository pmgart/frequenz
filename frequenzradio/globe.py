"""The globe: an OpenGL 3.3 view inside a Gtk.GLArea, drawn from vector map data.

Rendering (painter's order, no depth buffer: back-face culling removes the hidden side):
* the atmosphere glow is a screen-space gradient behind the globe,
* the ocean is one colour on a base ellipsoid (the depth bands are not drawn, see geodata.SOURCES),
* land, lakes and glaciers are triangulated Natural Earth polygons,
* country borders and rivers are lines, shown when zoomed in,
* places are GPU point sprites; size classes mirror Radio Garden's web globe,
* lighting follows the real sun for the current time (day and night side).

Interaction: drag to turn (with inertia), wheel for smooth zoom, +/- to step through the zoom
levels, click to select, double-click to focus, hover for a label. Picking runs on the CPU.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from .osinfo import desktop_gl_version, is_macos  # noqa: E402

# PyOpenGL must pick the same platform as GTK's GL context (EGL on Wayland). macOS always uses CGL.
if not is_macos() and os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

from OpenGL import GL as gl  # noqa: E402
from OpenGL.GL import shaders as gl_shaders  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

from . import geo, geodata  # noqa: E402

# Size classes and boost factor taken from the Radio Garden web globe bundle
# (smallPlaceScale/mediumPlaceScale/largePlaceScale, thresholds 5 and 20, boostScale 1.5).
SMALL_SCALE, MEDIUM_SCALE, LARGE_SCALE = 0.14, 0.27, 0.42
MEDIUM_THRESHOLD, LARGE_THRESHOLD = 5, 20
BOOST_SCALE = 1.5
FOCUS_DISTANCE = 3.3  # zoom used when turning to a place: the whole sphere stays in view
STATE_NORMAL, STATE_HOVER, STATE_SELECTED, STATE_PLAYING = 0.0, 1.0, 2.0, 3.0
SUN_REFRESH_S = 60.0

from .globe_palette import DEFAULT_PALETTE, LIGHT_BACKDROP, get_palette  # noqa: E402

# Colours come from the active palette (globe_palette.py): lime by default, or the classic blue
# ocean and olive land. AMBIENT is the same in both palettes.
AMBIENT = 0.22  # brightness of the night side: keeps coasts readable without hiding the terminator

# Painter's order. Each entry: (layer, palette field, specular strength, land mottling).
SURFACE_DRAWS = (
    ("base", "ocean", 0.35, 0.0),
    ("land", "land", 0.0, 0.14),
    ("lakes", "lake", 0.5, 0.0),
    ("ice", "ice", 0.25, 0.0),
)
LINE_DRAWS = (("borders", "border"), ("rivers", "river"))

SHADER_CONSTANTS = {"__INV_POLE_SQ__": f"{geo.INV_POLE_SCALE_SQ:.9f}"}
# GLSL 330 and GLES use explicit attribute locations; the GLSL 150 variant binds them by name instead.
_LAYOUT_LOCATION = re.compile(r"layout\(location = \d+\) ")

SURFACE_VS = """
#version 330 core
layout(location = 0) in vec3 a_pos;
uniform mat4 u_mvp;
out vec3 v_pos;
void main() {
    v_pos = a_pos;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

SURFACE_FS = """
#version 330 core
in vec3 v_pos;
uniform vec3 u_color;
uniform vec3 u_sun;
uniform vec3 u_eye;
uniform float u_ambient;
uniform float u_gloss;
uniform float u_mottle;
uniform vec3 u_rim;
out vec4 frag;

float hash3(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}

float value_noise(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float n000 = hash3(i);
    float n100 = hash3(i + vec3(1.0, 0.0, 0.0));
    float n010 = hash3(i + vec3(0.0, 1.0, 0.0));
    float n110 = hash3(i + vec3(1.0, 1.0, 0.0));
    float n001 = hash3(i + vec3(0.0, 0.0, 1.0));
    float n101 = hash3(i + vec3(1.0, 0.0, 1.0));
    float n011 = hash3(i + vec3(0.0, 1.0, 1.0));
    float n111 = hash3(i + vec3(1.0, 1.0, 1.0));
    return mix(mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
               mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y), f.z);
}

void main() {
    vec3 n = normalize(vec3(v_pos.x, v_pos.y * __INV_POLE_SQ__, v_pos.z));
    vec3 v = normalize(u_eye - v_pos);
    float ndl = dot(n, u_sun);
    float day = smoothstep(-0.12, 0.30, ndl);
    float light = u_ambient + (1.0 - u_ambient) * day;
    vec3 col = u_color;
    if (u_mottle > 0.0) {
        float m = 0.6 * value_noise(v_pos * 24.0) + 0.4 * value_noise(v_pos * 70.0);
        col *= 1.0 + u_mottle * (m - 0.5) * 2.0;
    }
    vec3 c = col * light;
    float rim = pow(1.0 - max(dot(n, v), 0.0), 3.0);
    c += rim * day * 0.25 * u_rim;
    if (u_gloss > 0.0) {
        vec3 h = normalize(u_sun + v);
        float spec = pow(max(dot(n, h), 0.0), 420.0);
        c += u_gloss * spec * day * vec3(0.85, 0.93, 1.0);
    }
    frag = vec4(c, 1.0);
}
"""

LINE_VS = """
#version 330 core
layout(location = 0) in vec3 a_pos;
uniform mat4 u_mvp;
out vec3 v_pos;
void main() {
    v_pos = a_pos;
    gl_Position = u_mvp * vec4(a_pos, 1.0);
}
"""

LINE_FS = """
#version 330 core
in vec3 v_pos;
uniform vec3 u_eye;
uniform vec4 u_color;
out vec4 frag;
void main() {
    vec3 n = normalize(vec3(v_pos.x, v_pos.y * __INV_POLE_SQ__, v_pos.z));
    if (dot(n, u_eye - v_pos) <= 0.0) discard;  // the far side of the globe
    frag = u_color;
}
"""

HALO_VS = """
#version 330 core
void main() {
    vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
"""

HALO_FS = """
#version 330 core
uniform vec2 u_center;
uniform float u_radius;
uniform vec2 u_sun_dir;
uniform vec3 u_bg;
uniform vec3 u_atmo;
out vec4 frag;
void main() {
    vec2 d = gl_FragCoord.xy - u_center;
    float r = length(d);
    float x = max(0.0, (r - u_radius) / max(u_radius, 1.0));
    float side = 0.5 + 0.5 * dot(d / max(r, 1e-3), u_sun_dir);
    float glow = (exp(-x * 14.0) * 0.6 + exp(-x * 3.0) * 0.18) * (0.25 + 0.75 * side);
    frag = vec4(u_bg + u_atmo * glow, 1.0);
}
"""

POINTS_VS = """
#version 330 core
layout(location = 0) in vec3 a_pos;
layout(location = 1) in float a_scale;
layout(location = 2) in float a_state;
uniform mat4 u_mvp;
uniform vec3 u_eye;
uniform float u_px;
uniform float u_marked_pass;
out float v_alpha;
out float v_state;
void main() {
    // Pass 0 draws the places that are neither selected nor playing; pass 1 draws only those two.
    // Drawing the marked places last keeps a dense neighbourhood (London) from covering the marker.
    if ((a_state >= 2.0) != (u_marked_pass > 0.5)) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        gl_PointSize = 0.0;
        v_alpha = 0.0;
        v_state = 0.0;
        return;
    }
    vec3 n = normalize(vec3(a_pos.x, a_pos.y * __INV_POLE_SQ__, a_pos.z));
    float facing = dot(n, normalize(u_eye - a_pos));
    if (facing <= 0.0) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        gl_PointSize = 0.0;
        v_alpha = 0.0;
        v_state = 0.0;
        return;
    }
    gl_Position = u_mvp * vec4(a_pos, 1.0);
    float grow = (a_state == 1.0) ? 1.6 : ((a_state >= 2.0) ? 1.9 : 1.0);
    gl_PointSize = u_px * a_scale * grow;
    // The station being played keeps a visible size at every zoom level: a 2 px dot is not a marker.
    if (a_state >= 3.0) gl_PointSize = max(gl_PointSize, 4.5 * u_px);
    v_alpha = smoothstep(0.0, 0.2, facing);
    v_state = a_state;
}
"""

POINTS_FS = """
#version 330 core
in float v_alpha;
in float v_state;
uniform vec4 u_dot;
uniform vec4 u_accent;
uniform vec4 u_playing;
uniform float u_time;
out vec4 frag;
void main() {
    vec2 c = gl_PointCoord * 2.0 - 1.0;
    float r2 = dot(c, c);
    if (r2 > 1.0) discard;
    float r = sqrt(r2);
    float edge = smoothstep(1.0, 0.45, r);
    vec4 col = u_dot;
    float alpha = edge;
    if (v_state >= 2.0) {
        col = u_accent;
        if (v_state >= 3.0) {
            col = u_playing;
            float pulse = 0.55 + 0.35 * sin(u_time * 5.0);
            float ring = smoothstep(0.12, 0.0, abs(r - pulse));
            alpha = max(edge * 0.9, ring);
        }
    }
    frag = vec4(col.rgb, col.a * alpha * v_alpha);
}
"""


@dataclass
class PlaceSet:
    """Places in the order they are drawn; index i is the GL instance index."""

    ids: list[str]
    titles: list[str]
    countries: list[str]
    counts: np.ndarray  # stations per place (API ``size``)
    boosts: np.ndarray  # bool
    xyz: np.ndarray  # (N, 3) float32 on the ellipsoid
    lnglat: np.ndarray  # (N, 2) float64 degrees
    index_by_id: dict[str, int]

    @classmethod
    def from_rows(cls, rows) -> "PlaceSet":
        ids, titles, countries, counts, boosts, lngs, lats = [], [], [], [], [], [], []
        for row in rows:
            ids.append(row["id"])
            titles.append(row["title"])
            countries.append(row["country"] or "")
            counts.append(int(row["size"]))
            boosts.append(bool(row["boost"]))
            lngs.append(float(row["lng"]))
            lats.append(float(row["lat"]))
        xyz = geo.lonlat_to_xyz(np.array(lngs), np.array(lats)) if lngs else np.zeros((0, 3), np.float32)
        return cls(
            ids=ids,
            titles=titles,
            countries=countries,
            counts=np.array(counts, dtype=np.int32),
            boosts=np.array(boosts, dtype=bool),
            xyz=xyz.astype(np.float32),
            lnglat=np.column_stack([np.array(lngs, dtype=np.float64), np.array(lats, dtype=np.float64)]),
            index_by_id={pid: i for i, pid in enumerate(ids)},
        )

    def scale_classes(self) -> np.ndarray:
        scale = np.full(len(self.ids), SMALL_SCALE, dtype=np.float32)
        scale[self.counts > MEDIUM_THRESHOLD] = MEDIUM_SCALE
        scale[self.counts > LARGE_THRESHOLD] = LARGE_SCALE
        scale[self.boosts] *= BOOST_SCALE
        return scale / SMALL_SCALE  # 1.0 == smallest dot


@dataclass(frozen=True)
class _Mesh:
    vao: int
    count: int  # indices (indexed meshes) or vertices (lines)
    indexed: bool


def _shader_source(source: str, es: bool, glsl: int = 330) -> str:
    """Return the GLES (GLSL ES 300), desktop GLSL 330 or desktop GLSL 150 variant of a shader."""
    for token, value in SHADER_CONSTANTS.items():
        source = source.replace(token, value)
    lines = source.strip().split("\n")
    body = "\n".join(lines[1:])  # drop the '#version' line
    if es:
        return "#version 300 es\nprecision highp float;\nprecision highp int;\n" + body
    if glsl == 150:  # OpenGL 3.2 core: the profile GTK uses on macOS
        return "#version 150 core\n" + _LAYOUT_LOCATION.sub("", body)
    return "#version 330 core\n" + body


def _compile(vs: str, fs: str, es: bool, glsl: int = 330, attributes: tuple = ()) -> int:
    """Compile and link a program. Attributes are bound by name, so the GLSL 150 variant (which has no
    layout(location)) gets the same attribute indices as the GLSL 330 and GLES variants."""
    shaders = [
        gl_shaders.compileShader(_shader_source(vs, es, glsl), gl.GL_VERTEX_SHADER),
        gl_shaders.compileShader(_shader_source(fs, es, glsl), gl.GL_FRAGMENT_SHADER),
    ]
    program = gl.glCreateProgram()
    for shader in shaders:
        gl.glAttachShader(program, shader)
    for index, name in attributes:
        gl.glBindAttribLocation(program, index, name)
    gl.glLinkProgram(program)
    if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
        log_text = gl.glGetProgramInfoLog(program)
        if isinstance(log_text, bytes):
            log_text = log_text.decode(errors="replace")
        raise RuntimeError(f"shader link failed: {log_text.strip()}")
    for shader in shaders:
        gl.glDeleteShader(shader)
    return program


def _gl_int(pname: int) -> int:
    """Read one integer GL state value. PyOpenGL returns a 1-element array or a scalar, depending on the query."""
    return int(np.ravel(gl.glGetIntegerv(pname))[0])


def _uniform_locations(program: int, names: tuple[str, ...]) -> dict[str, int]:
    return {name: gl.glGetUniformLocation(program, name) for name in names}


log = logging.getLogger("frequenzradio.globe")


class GlobeView(Gtk.GLArea):
    __gtype_name__ = "RGGlobeView"

    def __init__(
        self,
        globe_dir: Path | None,
        *,
        on_select: Callable[[int], None] | None = None,
        on_hover: Callable[[int | None, float, float], None] | None = None,
        on_focus: Callable[[int], None] | None = None,
        on_zoom: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__()
        self.set_has_depth_buffer(False)  # painter's order: no depth test is needed
        self.set_auto_render(False)
        self.set_required_version(*desktop_gl_version())  # GLES 3.0 on Linux; desktop 3.2 core on macOS
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(False)

        self._globe_dir = Path(globe_dir) if globe_dir is not None else None
        self.vector_map_ready = self._globe_dir is not None and geodata.is_built(self._globe_dir)
        self._on_select = on_select
        self._on_hover = on_hover
        self._on_focus = on_focus
        self._on_zoom = on_zoom
        self.gl_error: str | None = None  # why the OpenGL view could not start, or None
        self.places: PlaceSet | None = None
        self._scales: np.ndarray | None = None

        self.yaw = 0.0
        self.pitch = 0.35
        self.dist = geo.DEFAULT_DISTANCE
        self._vel_yaw = 0.0
        self._vel_pitch = 0.0
        self._drag_origin = (0.0, 0.0)
        self._dragging = False
        self._moved = False
        self._last_interaction = time.monotonic()
        self._target: tuple[float, float, float] | None = None
        self.auto_rotate = True
        self._palette = get_palette(DEFAULT_PALETTE)
        self._light_theme = False
        self.hovered: int | None = None
        self.selected: int | None = None
        self.playing: int | None = None
        self._state_dirty = True
        self._last_frame_time: float | None = None
        self._started = time.monotonic()
        self._gl_ready = False
        self._needs_upload = False
        self._es = False
        self._sun = geo.sun_direction(datetime.now(timezone.utc))
        self._sun_time = time.monotonic()
        self._zoom_reported: float | None = None
        self._meshes: dict[tuple[str, int], _Mesh] = {}
        self._missing: set[tuple[str, int]] = set()
        self._prefetch_queue: list[tuple[str, int]] = []

        self.connect("realize", self._on_realize)
        self.connect("unrealize", self._on_unrealize)
        self.connect("render", self._on_render)
        self.add_tick_callback(self._on_tick)
        self._install_controllers()

    # -- public API --------------------------------------------------------------
    def set_places(self, places: PlaceSet) -> None:
        self.places = places
        self._scales = places.scale_classes().astype(np.float32)
        self._needs_upload = True
        self._state_dirty = True
        self.queue_render()

    @property
    def palette_name(self) -> str:
        return self._palette.name

    def set_palette(self, name: str) -> None:
        """Switch the globe colours (lime or classic). Colours are uniforms, so nothing is rebuilt."""
        self._palette = get_palette(name)
        self.queue_render()

    def set_light_theme(self, light: bool) -> None:
        """The backdrop behind the globe follows the window theme; the sphere stays dark."""
        self._light_theme = bool(light)
        self.queue_render()

    def _current_backdrop(self) -> tuple:
        return LIGHT_BACKDROP if self._light_theme else self._palette.background

    def set_states(self, *, hovered: int | None = None, selected: int | None = None, playing: int | None = None) -> None:
        self.hovered = hovered
        self.selected = selected
        self.playing = playing
        self._state_dirty = True
        self.queue_render()

    def focus_place(self, lng: float, lat: float, zoom: float | None = FOCUS_DISTANCE) -> None:
        yaw, pitch = geo.camera_angles_for(lng, lat)
        self.auto_rotate = False
        self._target = (yaw, pitch, zoom if zoom is not None else self.dist)
        self._last_interaction = time.monotonic()

    def reset_view(self) -> None:
        self._target = (0.0, 0.35, geo.DEFAULT_DISTANCE)
        self._last_interaction = time.monotonic()

    def zoom_by(self, factor: float) -> None:
        """Continuous zoom (wheel): multiplies the camera distance."""
        self.dist = geo.clamp_distance(self.dist * factor)
        self._target = None
        self._last_interaction = time.monotonic()
        self.queue_render()

    def zoom_step(self, direction: int) -> None:
        """Move one zoom level closer (direction > 0) or farther (direction < 0), animated."""
        self._target = (self.yaw, self.pitch, geo.next_zoom_distance(self.dist, direction))
        self._last_interaction = time.monotonic()
        self.queue_render()

    def zoom_to(self, distance: float) -> None:
        """Animate to a camera distance (the zoom slider). The view keeps its angles."""
        self._target = (self.yaw, self.pitch, geo.clamp_distance(distance))
        self._last_interaction = time.monotonic()
        self.queue_render()

    # -- GTK controllers ---------------------------------------------------------
    def _install_controllers(self) -> None:
        drag = Gtk.GestureDrag.new()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        click = Gtk.GestureClick.new()
        click.set_button(1)
        click.connect("released", self._on_click)
        self.add_controller(click)

        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        motion = Gtk.EventControllerMotion.new()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def _on_drag_begin(self, gesture, x, y) -> None:
        self._dragging = True
        self._moved = False
        self._target = None
        self._drag_origin = (self.yaw, self.pitch)
        self._vel_yaw = self._vel_pitch = 0.0
        self._last_interaction = time.monotonic()

    def _on_drag_update(self, gesture, offset_x, offset_y) -> None:
        if math.hypot(offset_x, offset_y) > 4:
            self._moved = True
        k = 0.0042 * (self.dist / geo.DEFAULT_DISTANCE)
        origin_yaw, origin_pitch = self._drag_origin
        new_yaw = origin_yaw + offset_x * k
        new_pitch = max(-geo.MAX_PITCH, min(geo.MAX_PITCH, origin_pitch + offset_y * k))
        self._vel_yaw = (new_yaw - self.yaw) * 60.0
        self._vel_pitch = (new_pitch - self.pitch) * 60.0
        self.yaw, self.pitch = new_yaw, new_pitch
        self.queue_render()

    def _on_drag_end(self, gesture, offset_x, offset_y) -> None:
        self._dragging = False
        self._last_interaction = time.monotonic()

    def _on_click(self, gesture, n_press, x, y) -> None:
        if self._moved:
            return
        index = self._pick(x, y)
        if index is None:
            if self._on_select:
                self._on_select(-1)
            return
        if n_press >= 2:
            self._zoom_to_index(index)
            if self._on_focus:
                self._on_focus(index)
        elif self._on_select:
            self._on_select(index)

    def _on_scroll(self, controller, dx, dy) -> bool:
        self.zoom_by(math.exp(dy * 0.09))
        return True

    def _on_motion(self, controller, x, y) -> None:
        index = self._pick(x, y)
        if index != self.hovered and self._on_hover is not None:
            self._on_hover(index, x, y)
        elif self._on_hover is not None and index is not None:
            self._on_hover(index, x, y)
        self.hovered = index
        self._state_dirty = True
        self.queue_render()

    def _on_leave(self, controller) -> None:
        self.hovered = None
        self._state_dirty = True
        if self._on_hover is not None:
            self._on_hover(None, 0.0, 0.0)
        self.queue_render()

    def _pick(self, x: float, y: float) -> int | None:
        if self.places is None or len(self.places.ids) == 0:
            return None
        width, height = self.get_width(), self.get_height()
        if width <= 0 or height <= 0:
            return None
        return geo.pick_nearest(
            self.places.xyz,
            geo.model_matrix(self.yaw, self.pitch),
            self.dist,
            width,
            height,
            x,
            y,
            radius_px=12.0,
            weights=self.places.counts.astype(np.float64),
        )

    def _zoom_to_index(self, index: int) -> None:
        if self.places is None:
            return
        lng, lat = self.places.lnglat[index]
        self.focus_place(float(lng), float(lat), FOCUS_DISTANCE)

    # -- frame clock -------------------------------------------------------------
    def _on_tick(self, widget, frame_clock) -> bool:
        now = frame_clock.get_frame_time() / 1_000_000.0
        if self._last_frame_time is None:
            self._last_frame_time = now
        dt = min(0.1, max(0.0, now - self._last_frame_time))
        self._last_frame_time = now
        idle = time.monotonic() - self._last_interaction
        changed = False

        if not self._dragging:
            if abs(self._vel_yaw) > 1e-4 or abs(self._vel_pitch) > 1e-4:
                self.yaw += self._vel_yaw * dt
                self.pitch = max(-geo.MAX_PITCH, min(geo.MAX_PITCH, self.pitch + self._vel_pitch * dt))
                decay = math.exp(-4.0 * dt)
                self._vel_yaw *= decay
                self._vel_pitch *= decay
                changed = True
            if self._target is not None:
                ty, tp, td = self._target
                blend = 1.0 - math.exp(-5.0 * dt)
                diff = (ty - self.yaw + math.pi) % (2 * math.pi) - math.pi
                self.yaw += diff * blend
                self.pitch += (tp - self.pitch) * blend
                self.dist += (td - self.dist) * blend
                if abs(diff) < 1e-4 and abs(tp - self.pitch) < 1e-4 and abs(td - self.dist) < 1e-3:
                    self.yaw, self.pitch, self.dist = ty, tp, td
                    self._target = None
                changed = True
            elif self.auto_rotate and idle > 6.0:
                self.yaw += 0.05 * dt
                changed = True

        if time.monotonic() - self._sun_time > SUN_REFRESH_S:
            self._sun_time = time.monotonic()
            self._sun = geo.sun_direction(datetime.now(timezone.utc))
            changed = True
        if self._on_zoom is not None and self._zoom_reported != self.dist:
            self._zoom_reported = self.dist
            self._on_zoom(self.dist)

        pulsing = self.playing is not None and self.playing >= 0
        if changed or pulsing or self._state_dirty or self._needs_upload:
            self.queue_render()
        return GLib.SOURCE_CONTINUE

    # -- GL lifecycle ------------------------------------------------------------
    def _on_realize(self, area) -> None:
        self.gl_error = None
        try:
            area.make_current()
            if area.get_error() is not None:
                raise RuntimeError(area.get_error().message)
            self._setup_gl(area)
        except Exception as exc:  # no usable OpenGL context, e.g. a VM without 3D acceleration
            self._gl_ready = False
            self.gl_error = str(exc) or type(exc).__name__
            log.warning("3D globe disabled: %s", self.gl_error)
            if self._on_zoom is not None:  # let the window explain why the globe is empty
                self._on_zoom(self.dist)
            self.queue_render()

    def _setup_gl(self, area) -> None:
        es = bool(area.get_context().get_use_es())
        self._es = es
        # Desktop GL: GLSL 330 for a 3.3 or newer context, otherwise GLSL 150 (GTK's 3.2 core on macOS).
        glsl = 330
        if not es:
            major, minor = _gl_int(gl.GL_MAJOR_VERSION), _gl_int(gl.GL_MINOR_VERSION)
            glsl = 330 if (major, minor) >= (3, 3) else 150
        gl.glDisable(gl.GL_DEPTH_TEST)
        if not es:  # GLES always uses gl_PointSize; the enum does not exist there
            gl.glEnable(gl.GL_PROGRAM_POINT_SIZE)

        pos = ((0, "a_pos"),)
        self._surface_program = _compile(SURFACE_VS, SURFACE_FS, es, glsl, pos)
        self._line_program = _compile(LINE_VS, LINE_FS, es, glsl, pos)
        self._halo_program = _compile(HALO_VS, HALO_FS, es, glsl)
        self._points_program = _compile(POINTS_VS, POINTS_FS, es, glsl,
                                        ((0, "a_pos"), (1, "a_scale"), (2, "a_state")))
        self._uniforms = {
            "surface": _uniform_locations(self._surface_program,
                                          ("u_mvp", "u_color", "u_gloss", "u_mottle", "u_sun", "u_eye", "u_ambient", "u_rim")),
            "line": _uniform_locations(self._line_program, ("u_mvp", "u_color", "u_eye")),
            "halo": _uniform_locations(self._halo_program, ("u_center", "u_radius", "u_sun_dir", "u_bg", "u_atmo")),
            "points": _uniform_locations(self._points_program,
                                         ("u_mvp", "u_eye", "u_px", "u_dot", "u_accent", "u_playing", "u_time", "u_marked_pass")),
        }
        self._empty_vao = gl.glGenVertexArrays(1)  # the halo is generated from gl_VertexID
        self._meshes = {}
        self._missing = set()
        positions, indices = geo.globe_mesh()
        self._base = self._upload_triangles(positions, indices)
        self._points_vao = gl.glGenVertexArrays(1)
        self._points_vbo = gl.glGenBuffers(1)
        self._scale_vbo = gl.glGenBuffers(1)
        self._state_vbo = gl.glGenBuffers(1)
        self._gl_ready = True
        self._needs_upload = True

        # Upload the close-in detail in the background so zooming in does not stall.
        self._prefetch_queue = []
        if self.vector_map_ready:
            for lod in (1, 2):
                for layer, *_ in SURFACE_DRAWS:
                    if layer != "base":
                        self._prefetch_queue.append((layer, lod))
                for layer, _colour in LINE_DRAWS:
                    if lod in geodata.LINE_LODS.get(layer, ()):
                        self._prefetch_queue.append((layer, lod))
            GLib.idle_add(self._prefetch_step)
        self.queue_render()

    def _on_unrealize(self, area) -> None:
        self._gl_ready = False
        self._meshes = {}
        self._missing = set()
        self._prefetch_queue = []

    def _prefetch_step(self) -> bool:
        if not self._gl_ready or not self._prefetch_queue:
            return False
        layer, lod = self._prefetch_queue.pop(0)
        self.make_current()
        self._mesh(layer, lod)
        return bool(self._prefetch_queue)

    def _mesh(self, layer: str, lod: int) -> _Mesh | None:
        if layer == "base":
            return self._base
        key = (layer, lod)
        mesh = self._meshes.get(key)
        if mesh is None and key not in self._missing:
            arrays = geodata.load_layer(self._globe_dir, layer, lod) if self._globe_dir is not None else None
            if arrays is None:
                self._missing.add(key)
                return None
            mesh = self._upload_arrays(arrays)
            self._meshes[key] = mesh
        return mesh

    def _upload_arrays(self, arrays: dict[str, np.ndarray]) -> _Mesh:
        if "segments" in arrays:
            return self._upload_triangles(arrays["segments"].reshape(-1, 3), None)
        return self._upload_triangles(arrays["vertices"], arrays["indices"].reshape(-1))

    def _upload_triangles(self, vertices: np.ndarray, indices: np.ndarray | None) -> _Mesh:
        vertices = np.ascontiguousarray(vertices, dtype=np.float32)
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        if indices is None:  # line segments are drawn with glDrawArrays
            gl.glBindVertexArray(0)
            return _Mesh(vao, int(vertices.shape[0]), indexed=False)
        indices = np.ascontiguousarray(indices, dtype=np.uint32)
        ebo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, ebo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, gl.GL_STATIC_DRAW)
        gl.glBindVertexArray(0)
        return _Mesh(vao, int(indices.size), indexed=True)

    def _upload_places(self) -> None:
        places = self.places
        gl.glBindVertexArray(self._points_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._points_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, places.xyz.nbytes, places.xyz, gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._scale_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, self._scales.nbytes, self._scales, gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(1, 1, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._state_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, places.xyz.shape[0] * 4, None, gl.GL_DYNAMIC_DRAW)
        gl.glEnableVertexAttribArray(2)
        gl.glVertexAttribPointer(2, 1, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        self._needs_upload = False
        self._state_dirty = True

    def _upload_states(self) -> None:
        count = self.places.xyz.shape[0]
        states = np.zeros(count, dtype=np.float32)
        if self.hovered is not None and 0 <= self.hovered < count:
            states[self.hovered] = STATE_HOVER
        if self.selected is not None and 0 <= self.selected < count:
            states[self.selected] = STATE_SELECTED
        if self.playing is not None and 0 <= self.playing < count:
            states[self.playing] = STATE_PLAYING
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._state_vbo)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, states.nbytes, states)
        self._state_dirty = False

    def _on_render(self, area, context) -> bool:
        if not self._gl_ready:
            return True
        width = self.get_width()
        height = self.get_height()
        scale = self.get_scale_factor()
        device_w = max(1, int(round(width * scale)))
        device_h = max(1, int(round(height * scale)))
        gl.glViewport(0, 0, device_w, device_h)
        backdrop = self._current_backdrop()
        gl.glClearColor(backdrop[0], backdrop[1], backdrop[2], 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        model = geo.model_matrix(self.yaw, self.pitch)
        rot = model[:3, :3]
        near, far = geo.clip_planes(self.dist)
        proj = geo.perspective(geo.FOVY_DEG, width / max(height, 1), near, far)
        mvp = np.ascontiguousarray(proj @ geo.view_matrix(self.dist) @ model, dtype=np.float32)
        eye = np.ascontiguousarray(rot.T @ np.array([0.0, 0.0, self.dist]), dtype=np.float32)
        sun = np.ascontiguousarray(self._sun, dtype=np.float32)
        lod = geo.level_of_detail(self.dist)

        self._draw_halo(device_w, device_h, rot)

        gl.glEnable(gl.GL_CULL_FACE)
        gl.glCullFace(gl.GL_BACK)
        gl.glFrontFace(gl.GL_CCW)
        gl.glDisable(gl.GL_BLEND)
        palette = self._palette
        for layer, field, gloss, mottle in SURFACE_DRAWS:
            mesh = self._mesh(layer, lod)
            if mesh is not None:
                self._draw_surface(mesh, mvp, getattr(palette, field), gloss, mottle, eye, sun)

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        for layer, field in LINE_DRAWS:
            if lod in geodata.LINE_LODS.get(layer, ()):
                mesh = self._mesh(layer, lod)
                if mesh is not None:
                    self._draw_lines(mesh, mvp, getattr(palette, field), eye)

        if self.places is not None and len(self.places.ids):
            if self._needs_upload:
                self._upload_places()
            if self._state_dirty:
                self._upload_states()
            gl.glUseProgram(self._points_program)
            u = self._uniforms["points"]
            gl.glUniformMatrix4fv(u["u_mvp"], 1, gl.GL_TRUE, mvp)
            gl.glUniform3f(u["u_eye"], float(eye[0]), float(eye[1]), float(eye[2]))
            base_px = 2.6 * scale * min(2.0, (geo.DEFAULT_DISTANCE / self.dist) ** 0.5)
            gl.glUniform1f(u["u_px"], base_px)
            gl.glUniform4f(u["u_dot"], *palette.dot)
            gl.glUniform4f(u["u_accent"], *palette.selected)
            gl.glUniform4f(u["u_playing"], *palette.playing)
            gl.glUniform1f(u["u_time"], time.monotonic() - self._started)
            gl.glBindVertexArray(self._points_vao)
            count = self.places.xyz.shape[0]
            gl.glUniform1f(u["u_marked_pass"], 0.0)
            gl.glDrawArrays(gl.GL_POINTS, 0, count)
            gl.glUniform1f(u["u_marked_pass"], 1.0)
            gl.glDrawArrays(gl.GL_POINTS, 0, count)
        gl.glBindVertexArray(0)
        return True

    def _draw_halo(self, device_w: int, device_h: int, rot: np.ndarray) -> None:
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(self._halo_program)
        u = self._uniforms["halo"]
        tan_limb = 1.0 / math.sqrt(max(self.dist * self.dist - 1.0, 1e-9))
        radius = 0.5 * device_h * tan_limb / math.tan(math.radians(geo.FOVY_DEG) / 2.0)
        sun_view = rot @ self._sun
        planar = sun_view[:2]
        norm = float(np.hypot(planar[0], planar[1]))
        sun_dir = planar / norm if norm > 1e-9 else np.zeros(2)
        gl.glUniform2f(u["u_center"], device_w / 2.0, device_h / 2.0)
        gl.glUniform1f(u["u_radius"], radius)
        gl.glUniform2f(u["u_sun_dir"], float(sun_dir[0]), float(sun_dir[1]))
        backdrop = self._current_backdrop()
        atmosphere = self._palette.atmosphere
        gl.glUniform3f(u["u_bg"], backdrop[0], backdrop[1], backdrop[2])
        gl.glUniform3f(u["u_atmo"], atmosphere[0], atmosphere[1], atmosphere[2])
        gl.glBindVertexArray(self._empty_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

    def _draw_surface(self, mesh: _Mesh, mvp: np.ndarray, colour, gloss: float, mottle: float,
                      eye: np.ndarray, sun: np.ndarray) -> None:
        gl.glUseProgram(self._surface_program)
        u = self._uniforms["surface"]
        gl.glUniformMatrix4fv(u["u_mvp"], 1, gl.GL_TRUE, mvp)
        gl.glUniform3f(u["u_color"], colour[0], colour[1], colour[2])
        gl.glUniform1f(u["u_gloss"], gloss)
        gl.glUniform1f(u["u_mottle"], mottle)
        gl.glUniform3f(u["u_sun"], float(sun[0]), float(sun[1]), float(sun[2]))
        gl.glUniform3f(u["u_eye"], float(eye[0]), float(eye[1]), float(eye[2]))
        gl.glUniform1f(u["u_ambient"], AMBIENT)
        gl.glUniform3f(u["u_rim"], *self._palette.rim)
        gl.glBindVertexArray(mesh.vao)
        gl.glDrawElements(gl.GL_TRIANGLES, mesh.count, gl.GL_UNSIGNED_INT, None)

    def _draw_lines(self, mesh: _Mesh, mvp: np.ndarray, colour, eye: np.ndarray) -> None:
        gl.glUseProgram(self._line_program)
        u = self._uniforms["line"]
        gl.glUniformMatrix4fv(u["u_mvp"], 1, gl.GL_TRUE, mvp)
        gl.glUniform4f(u["u_color"], colour[0], colour[1], colour[2], colour[3])
        gl.glUniform3f(u["u_eye"], float(eye[0]), float(eye[1]), float(eye[2]))
        gl.glBindVertexArray(mesh.vao)
        gl.glDrawArrays(gl.GL_LINES, 0, mesh.count)
