"""Preferences window: appearance, globe, stations, shortcuts and about.

Every row calls an action or a method that already exists on the main window. Nothing here adds
a feature.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from . import __version__  # noqa: E402
from .globe_palette import CLASSIC, LIME  # noqa: E402


def _button(label: str, callback) -> Gtk.Button:
    button = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=["flat"])
    button.connect("clicked", callback)
    return button


def open_preferences(window) -> Adw.PreferencesWindow:
    dialog = Adw.PreferencesWindow(transient_for=window, modal=True, title="Preferences")
    page = Adw.PreferencesPage(title="Preferences", icon_name="fq-settings-symbolic")
    dialog.add(page)

    appearance = Adw.PreferencesGroup(title="Appearance")
    light = Adw.SwitchRow(title="Light theme", subtitle="Off uses the dark theme")
    light.set_active(window.theme == "light")
    light.connect("notify::active",
                  lambda row, _pspec: window.set_theme_name("light" if row.get_active() else "dark"))
    appearance.add(light)
    classic = Adw.SwitchRow(title="Classic globe colours", subtitle="Blue ocean and olive land")
    classic.set_active(window.globe.palette_name == CLASSIC)
    classic.connect("notify::active",
                    lambda row, _pspec: window.set_globe_palette(CLASSIC if row.get_active() else LIME))
    appearance.add(classic)
    page.add(appearance)

    globe = Adw.PreferencesGroup(title="Globe")
    rotate = Adw.SwitchRow(title="Slow auto-rotate", subtitle="Turns the globe slowly when idle")
    rotate.set_active(window.globe.auto_rotate)
    rotate.connect("notify::active", lambda row, _pspec: window.set_auto_rotate(row.get_active()))
    globe.add(rotate)
    reset = Adw.ActionRow(title="Reset view", subtitle="Shortcut: 0")
    reset.add_suffix(_button("Reset", lambda *_: window.globe.reset_view()))
    globe.add(reset)
    page.add(globe)

    stations = Adw.PreferencesGroup(title="Stations")
    random_row = Adw.ActionRow(title="Random station", subtitle="Shortcut: R")
    random_row.add_suffix(_button("Play", lambda *_: window.play_random()))
    stations.add(random_row)
    update = Adw.ActionRow(title="Update station catalog", subtitle="Downloads new and changed stations")
    update.add_suffix(_button("Update", lambda *_: window.start_sync()))
    stations.add(update)
    page.add(stations)

    help_group = Adw.PreferencesGroup(title="Help")
    keys = Adw.ActionRow(title="Keyboard shortcuts")
    keys.add_suffix(_button("Show", lambda *_: window.activate_action("win.shortcuts", None)))
    help_group.add(keys)
    about = Adw.ActionRow(title="About FREQUENZ", subtitle=f"Version {__version__}")
    about.add_suffix(_button("About", lambda *_: window.activate_action("win.about", None)))
    help_group.add(about)
    page.add(help_group)

    dialog.present()
    return dialog
