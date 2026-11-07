"""Colour palettes for the globe.

Two palettes exist:

- lime (the default): the design handoff's colours on the existing globe geometry. A charcoal
  sphere (ocean and land taken from the dark tokens), a lime limb glow, a lime rim and lime city
  dots. The station being played is marked in magenta-blue, as chosen for the design.
- classic: the blue ocean and olive land that FREQUENZ 0.1.1 shipped. These values are unchanged.

Colours are sRGB components in 0..1. They reach the GPU as uniforms, so switching palette needs no
shader rebuild. This module has no GTK import, so its tests run without a display.
"""

from __future__ import annotations

from dataclasses import dataclass

LIME = "lime"
CLASSIC = "classic"
NAMES = (LIME, CLASSIC)
DEFAULT_PALETTE = LIME

# Backdrop behind the globe in the light theme: the window's light page. The sphere stays dark.
LIGHT_BACKDROP = (0xF6 / 255, 0xF7 / 255, 0xF9 / 255)

_LIME_ACCENT = (0xC5 / 255, 1.0, 0.0)  # #c5ff00, the accent token
_MAGENTA_BLUE = (0xA2 / 255, 0x3B / 255, 1.0)  # #a23bff, the playing marker chosen for the design


@dataclass(frozen=True)
class Palette:
    name: str
    background: tuple  # behind the globe in the dark theme (RGB)
    atmosphere: tuple  # glow around the limb (RGB)
    ocean: tuple  # RGB
    land: tuple  # RGB
    lake: tuple  # RGB
    ice: tuple  # RGB
    border: tuple  # RGBA lines
    river: tuple  # RGBA lines
    dot: tuple  # RGBA, places
    selected: tuple  # RGBA, the place the list shows
    playing: tuple  # RGBA, the station being played
    rim: tuple  # RGB, lit edge of the sphere


CLASSIC_PALETTE = Palette(
    name=CLASSIC,
    background=(0.012, 0.016, 0.03),
    atmosphere=(0.34, 0.62, 1.0),
    ocean=(0.07, 0.24, 0.37),
    land=(0.34, 0.42, 0.23),
    lake=(0.14, 0.40, 0.50),
    ice=(0.88, 0.93, 0.97),
    border=(0.86, 0.90, 0.84, 0.30),
    river=(0.36, 0.64, 0.90, 0.50),
    dot=(0.82, 1.0, 0.95, 0.9),
    selected=(0.26, 0.90, 0.75, 1.0),
    playing=(0.26, 0.90, 0.75, 1.0),
    rim=(0.30, 0.55, 1.0),
)

LIME_PALETTE = Palette(
    name=LIME,
    background=(0x10 / 255, 0x12 / 255, 0x14 / 255),  # the dark theme's app background
    atmosphere=_LIME_ACCENT,
    ocean=(0x18 / 255, 0x1A / 255, 0x1D / 255),  # dark --fq-surface
    land=(0x39 / 255, 0x3D / 255, 0x41 / 255),  # dark --fq-divider
    lake=(0.10, 0.12, 0.13),
    ice=(0.88, 0.93, 0.97),
    border=(0.86, 0.90, 0.84, 0.30),
    river=(*_LIME_ACCENT, 0.45),
    dot=(*_LIME_ACCENT, 0.92),
    selected=(*_LIME_ACCENT, 1.0),
    playing=(*_MAGENTA_BLUE, 1.0),
    rim=_LIME_ACCENT,
)

_PALETTES = {LIME: LIME_PALETTE, CLASSIC: CLASSIC_PALETTE}


def normalize(value: object) -> str:
    """A known palette name. Anything else (missing, misspelt, wrong type) gives the default."""
    return value if isinstance(value, str) and value in _PALETTES else DEFAULT_PALETTE


def get_palette(name: object) -> Palette:
    return _PALETTES[normalize(name)]
