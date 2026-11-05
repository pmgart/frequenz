"""ICY title cleanup: station metadata is free text, so only plausible song titles are shown."""

from frequenzradio.player import clean_icy_title


def test_plain_titles_are_kept_and_collapsed_to_one_line():
    assert clean_icy_title("  Thank You -  Kevin C. Montfort \n Angela Spivey ") == \
        "Thank You - Kevin C. Montfort Angela Spivey"


def test_json_and_bare_numbers_are_ignored():
    assert clean_icy_title('{"status":1,"message":"Ok"}0') is None
    assert clean_icy_title("[1, 2]") is None
    assert clean_icy_title("0") is None
    assert clean_icy_title("   ") is None
