"""Globe palettes: the classic colours are the ones FREQUENZ 0.1.1 shipped. The lime palette takes its
accent and surface colours from the design tokens in style.css."""

import re
from pathlib import Path

import pytest

from frequenzradio import globe_palette as gp

CSS = Path(__file__).resolve().parents[1] / "frequenzradio" / "data" / "style.css"
FIELDS = ("background", "atmosphere", "ocean", "land", "lake", "ice", "border", "river",
          "dot", "selected", "playing", "rim")


def _hex(value: str) -> tuple:
    h = value.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _token(theme: str, name: str) -> str:
    css = CSS.read_text(encoding="utf-8")
    block = re.search(r"^\.fq-%s\s*\{(.*?)\}" % theme, css, re.S | re.M)
    assert block, f".fq-{theme} block is missing"
    value = re.search(r"--fq-%s:\s*(#[0-9a-fA-F]{6})" % name, block.group(1))
    assert value, f"--fq-{name} is missing in the {theme} block"
    return value.group(1)


def test_classic_palette_keeps_the_colours_frequenz_has_shipped():
    p = gp.get_palette(gp.CLASSIC)
    assert p.name == "classic"
    assert p.background == (0.012, 0.016, 0.03)
    assert p.atmosphere == (0.34, 0.62, 1.0)
    assert p.ocean == (0.07, 0.24, 0.37)
    assert p.land == (0.34, 0.42, 0.23)
    assert p.lake == (0.14, 0.40, 0.50)
    assert p.border == (0.86, 0.90, 0.84, 0.30)
    assert p.river == (0.36, 0.64, 0.90, 0.50)
    assert p.dot == (0.82, 1.0, 0.95, 0.9)
    assert p.selected == (0.26, 0.90, 0.75, 1.0)
    assert p.playing == (0.26, 0.90, 0.75, 1.0)
    assert p.rim == (0.30, 0.55, 1.0)


def test_lime_palette_takes_its_accent_from_the_design_token():
    accent = _hex(_token("light", "accent"))  # the accent is the same in both themes
    p = gp.get_palette(gp.LIME)
    assert p.atmosphere[:3] == pytest.approx(accent)
    assert p.rim[:3] == pytest.approx(accent)
    assert p.dot[:3] == pytest.approx(accent)
    assert p.selected[:3] == pytest.approx(accent)


def test_lime_palette_ocean_and_land_come_from_the_dark_tokens():
    p = gp.get_palette(gp.LIME)
    assert p.ocean[:3] == pytest.approx(_hex(_token("dark", "surface")))
    assert p.land[:3] == pytest.approx(_hex(_token("dark", "divider")))


def test_playing_marker_is_magenta_blue_in_the_lime_palette():
    assert gp.get_palette(gp.LIME).playing[:3] == pytest.approx(_hex("#a23bff"))


def test_unknown_names_fall_back_to_the_default():
    assert gp.normalize("neon") == gp.LIME
    assert gp.normalize(None) == gp.LIME
    assert gp.normalize(42) == gp.LIME
    assert gp.normalize(gp.CLASSIC) == gp.CLASSIC


@pytest.mark.parametrize("name", gp.NAMES)
def test_every_channel_is_within_0_and_1(name):
    p = gp.get_palette(name)
    for field in FIELDS:
        for channel in getattr(p, field):
            assert 0.0 <= channel <= 1.0, f"{name}.{field}"
