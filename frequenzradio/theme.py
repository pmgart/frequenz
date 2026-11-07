"""Theme names and the classes that select the design tokens in style.css.

GTK is imported only inside apply_scheme(), so the names can be tested without a display.
"""

from __future__ import annotations

THEMES = ("dark", "light")
DEFAULT_THEME = "dark"
_WINDOW_CLASS = {"dark": "fq-dark", "light": "fq-light"}


def normalize(value: object) -> str:
    """Return a known theme name. Anything else (missing, misspelt, wrong type) gives the default."""
    return value if isinstance(value, str) and value in THEMES else DEFAULT_THEME


def window_class(theme: str) -> str:
    """The CSS class the window carries, so that the matching token block applies."""
    return _WINDOW_CLASS[normalize(theme)]


def other(theme: str) -> str:
    """The theme that the toggle switches to."""
    return "light" if normalize(theme) == "dark" else "dark"


def apply_scheme(theme: str) -> None:
    """Ask libadwaita for the matching colour scheme. Needs GTK, so call it from the GUI only."""
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    scheme = Adw.ColorScheme.FORCE_LIGHT if normalize(theme) == "light" else Adw.ColorScheme.FORCE_DARK
    Adw.StyleManager.get_default().set_color_scheme(scheme)
