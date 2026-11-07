"""Design tokens in style.css.

Both themes define the same token names. Text pairs reach 4.5:1 and non-text pairs reach 3:1, with
the known exceptions below. KNOWN_EXCEPTIONS records flat lime on white, which Pablo chose on
2026-11-06 ("today's approved look"). The exception must keep failing the rule: if the palette
changes so that it passes, the test asks for the record to be removed.
"""

import re
from pathlib import Path

import pytest

from frequenzradio.theme import window_class

CSS_PATH = Path(__file__).resolve().parents[1] / "frequenzradio" / "data" / "style.css"
THEMES = ("dark", "light")
TEXT_PAIRS = [
    ("text", "app-bg"),
    ("text", "surface"),
    ("text-muted", "surface"),
    ("text-muted", "app-bg"),
    ("on-accent", "accent"),
    ("card-text", "card-bg"),
    ("now-row-text", "now-row"),
    ("now", "surface"),
    ("live-text", "surface"),
    ("tile-text", "tile"),
    ("card-muted", "card-bg"),
]
NON_TEXT_PAIRS = [
    ("focus", "app-bg"),
    ("focus", "surface"),
    ("accent", "app-bg"),
    ("accent", "surface"),
    ("text", "chip"),
]
KNOWN_EXCEPTIONS = {
    ("light", "accent", "surface"): "flat lime fill on white (chosen 2026-11-06, 1.19:1)",
    ("light", "accent", "app-bg"): "flat lime fill on the light page (chosen 2026-11-06, 1.11:1)",
}


def _css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def _tokens(theme: str) -> dict:
    block = re.search(r"^\.fq-%s\s*\{(.*?)\}" % theme, _css(), re.S | re.M)
    assert block, f".fq-{theme} block is missing from style.css"
    return dict(re.findall(r"--fq-([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", block.group(1)))


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_both_themes_define_the_same_tokens():
    assert set(_tokens("dark")) == set(_tokens("light"))
    assert len(_tokens("dark")) >= 14


def test_every_token_the_css_uses_is_defined_in_both_themes():
    used = set(re.findall(r"var\(--fq-([a-z-]+)\)", _css()))
    assert used, "no token is used in style.css"
    for theme in THEMES:
        missing = used - set(_tokens(theme))
        assert not missing, f"{theme} lacks {sorted(missing)}"


@pytest.mark.parametrize("theme", THEMES)
def test_each_theme_has_a_css_block_that_matches_the_window_class(theme):
    assert re.search(r"^\.%s\s*\{" % re.escape(window_class(theme)), _css(), re.M)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("fg, bg", TEXT_PAIRS)
def test_text_pairs_reach_4_5_to_1(theme, fg, bg):
    tokens = _tokens(theme)
    ratio = contrast(tokens[fg], tokens[bg])
    assert ratio >= 4.5, f"{theme}: {fg} on {bg} is {ratio:.2f}:1"


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("fg, bg", NON_TEXT_PAIRS)
def test_non_text_pairs_reach_3_to_1_except_the_known_exceptions(theme, fg, bg):
    tokens = _tokens(theme)
    ratio = contrast(tokens[fg], tokens[bg])
    if (theme, fg, bg) in KNOWN_EXCEPTIONS:
        assert ratio < 3.0, "this exception passes now: remove it from KNOWN_EXCEPTIONS"
    else:
        assert ratio >= 3.0, f"{theme}: {fg} on {bg} is {ratio:.2f}:1"
