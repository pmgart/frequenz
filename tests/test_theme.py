"""Theme names, and the window classes that select the design tokens in style.css."""

from frequenzradio.theme import DEFAULT_THEME, THEMES, normalize, other, window_class


def test_known_names_pass_through():
    assert normalize("dark") == "dark"
    assert normalize("light") == "light"


def test_anything_else_becomes_the_default():
    assert normalize("purple") == DEFAULT_THEME
    assert normalize("") == DEFAULT_THEME
    assert normalize(None) == DEFAULT_THEME
    assert normalize(1) == DEFAULT_THEME


def test_window_classes():
    assert window_class("dark") == "fq-dark"
    assert window_class("light") == "fq-light"
    assert window_class("nonsense") == "fq-dark"


def test_toggle_switches_between_the_two_themes():
    assert other("dark") == "light"
    assert other("light") == "dark"
    assert other("nonsense") == "light"
    assert set(THEMES) == {"dark", "light"}
