"""Widgets for the FREQUENZ window: section heading, left rail and the now-playing card.

They show what the app already knows. None of them plays audio or reads the catalog.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango  # noqa: E402

RAIL_WIDTH = 88

# Player state -> text on the card's pill. A stopped player shows no pill.
CARD_STATE_TEXT = {
    "playing": "LIVE",
    "loading": "CONNECTING",
    "buffering": "CONNECTING",
    "paused": "PAUSED",
    "error": "UNAVAILABLE",
}


def icon(name: str, size: int) -> Gtk.Image:
    image = Gtk.Image.new_from_icon_name(name)
    image.set_pixel_size(size)
    return image


class SectionHeading(Gtk.Box):
    """Uppercase heading above the station list, with a count or status on the right."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, css_classes=["fq-section"])
        self._title = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                                css_classes=["fq-section-title"])
        self._count = Gtk.Label(xalign=1, ellipsize=Pango.EllipsizeMode.END,
                                css_classes=["fq-section-count"])
        self.append(self._title)
        self.append(self._count)

    def set_title(self, text: str) -> None:
        self._title.set_label(text.upper())

    def set_subtitle(self, text: str) -> None:
        self._count.set_label(text)


class Rail(Gtk.Box):
    """Left rail. Only items with a feature behind them are added."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                         css_classes=["fq-rail"], margin_top=14, margin_bottom=14)
        self.set_size_request(RAIL_WIDTH, -1)
        self.items: dict[str, Gtk.Widget] = {}

    def add_toggle(self, key: str, icon_name: str, tooltip: str, *, active: bool = False,
                   style: str = "fq-rail-item") -> Gtk.ToggleButton:
        button = Gtk.ToggleButton(icon_name=icon_name, tooltip_text=tooltip, active=active,
                                  css_classes=["flat", style], halign=Gtk.Align.CENTER)
        self._add(key, button)
        return button

    def add_button(self, key: str, icon_name: str, tooltip: str) -> Gtk.Button:
        button = Gtk.Button(icon_name=icon_name, tooltip_text=tooltip,
                            css_classes=["flat", "fq-rail-item"], halign=Gtk.Align.CENTER)
        self._add(key, button)
        return button

    def add_spacer(self) -> None:
        self.append(Gtk.Box(vexpand=True))

    def _add(self, key: str, widget: Gtk.Widget) -> None:
        self.items[key] = widget
        self.append(widget)


class LiveCard(Gtk.Box):
    """Now-playing card: state pill, station title, location and the favorite toggle."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, css_classes=["fq-card"])
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pill = Gtk.Label(halign=Gtk.Align.START, css_classes=["fq-pill"], visible=False)
        top.append(self.pill)
        top.append(Gtk.Box(hexpand=True))
        self.fav_button = Gtk.ToggleButton(icon_name="fq-heart-symbolic", tooltip_text="Add to favorites (F)",
                                           css_classes=["flat", "fq-card-action"], valign=Gtk.Align.CENTER)
        top.append(self.fav_button)
        self.append(top)

        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=28,
                               css_classes=["fq-card-title"])
        self.append(self.title)

        place_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        place_row.append(icon("fq-map-pin-symbolic", 14))
        self.place = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                               css_classes=["fq-card-place"])
        place_row.append(self.place)
        self.append(place_row)
        self.set_empty()

    def set_station(self, title: str, place: str) -> None:
        self.title.set_label(title)
        self.place.set_label(place)
        self.fav_button.set_sensitive(True)

    def set_empty(self) -> None:
        self.set_station("Pick a station", "Click a dot on the globe")
        self.fav_button.set_sensitive(False)
        self.set_state(None)

    def set_state(self, name: str | None) -> None:
        text = CARD_STATE_TEXT.get(name or "", "")
        self.pill.set_label(text)
        self.pill.set_visible(bool(text))
