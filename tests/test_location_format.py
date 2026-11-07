from frequenzradio.text import format_location


def test_place_and_country_are_capitals_separated_by_a_comma():
    assert format_location("London", "United Kingdom") == "LONDON, UNITED KINGDOM"


def test_missing_parts_are_left_out():
    assert format_location("London", None) == "LONDON"
    assert format_location(None, "Sweden") == "SWEDEN"
    assert format_location("  ", "") == ""
