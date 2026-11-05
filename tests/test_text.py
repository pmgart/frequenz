"""Metadata cleanup: invisible characters and spacing never reach the catalog or the UI."""

from frequenzradio.api import station_from_page
from frequenzradio.text import clean_text


def test_zero_width_space_and_bidi_marks_are_removed():
    assert clean_text("\u200bHsinchu City") == "Hsinchu City"
    assert clean_text("Nabeul\u200e") == "Nabeul"


def test_joiners_that_carry_meaning_are_kept():
    assert clean_text("a\u200db") == "a\u200db"  # zero-width joiner
    assert clean_text("a\u200cb") == "a\u200cb"  # zero-width non-joiner


def test_whitespace_is_collapsed_and_control_characters_become_spaces():
    assert clean_text("  Hossana  FM \t\n") == "Hossana FM"
    assert clean_text("Radio\x00Hot") == "Radio Hot"


def test_empty_and_missing_values():
    assert clean_text(None) == ""
    assert clean_text("") == ""
    assert clean_text("\u200b \u200e") == ""


def test_text_is_normalized_to_nfc():
    assert clean_text("A\u030angelo") == "\u00c5ngelo"  # A + combining ring above


def test_station_parsing_applies_the_cleanup():
    station = station_from_page({
        "url": "/listen/hot-fm/abc123",
        "title": "\u200bHot  FM",
        "place": {"id": "p1", "title": "\u200bHsinchu City"},
        "country": {"id": "c1", "title": "Taiwan\u200e"},
    })
    assert station.title == "Hot FM"
    assert station.place_title == "Hsinchu City"
    assert station.country == "Taiwan"
