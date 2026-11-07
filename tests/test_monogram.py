from frequenzradio.text import monogram


def test_station_names_give_the_expected_tile_text():
    assert monogram("NTS Radio") == "NTS"
    assert monogram("Rinse FM") == "RIN"
    assert monogram("Radio X") == "X"
    assert monogram("BBC Radio 6 Music") == "BBC"


def test_a_leading_the_is_skipped():
    assert monogram("The Wire") == "WIR"


def test_nothing_usable_gives_a_dot():
    assert monogram("") == "•"
    assert monogram(None) == "•"
    assert monogram("Radio") == "•"


def test_invisible_characters_do_not_reach_the_tile():
    assert monogram("\u200bHsinchu Radio") == "HSI"
