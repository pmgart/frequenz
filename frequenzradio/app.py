"""Adw.Application entry point for the desktop app."""

from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .paths import APP_ID, APP_NAME, asset  # noqa: E402


class FrequenzApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window = None
        self._snapshot_path = os.environ.get("FREQUENZ_SNAPSHOT")
        self.connect("startup", self._on_startup)
        self.connect("activate", self._on_activate)

    def _on_startup(self, app) -> None:
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(asset("style.css")))
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(display, provider,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            Gtk.IconTheme.get_for_display(display).add_search_path(str(asset("icons")))
        Gtk.Window.set_default_icon_name(APP_ID)

        from gi.repository import Gio

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def _on_activate(self, app) -> None:
        if self.window is None:
            from .window import MainWindow

            self.window = MainWindow(app)
            self.window.set_title(APP_NAME)
            if self._snapshot_path:
                GLib.timeout_add_seconds(int(os.environ.get("FREQUENZ_SNAPSHOT_AFTER", "6")),
                                         self._take_snapshot)
        self.window.present()

    def _take_snapshot(self) -> bool:
        """Test hook: write the window's current rendering to PNG and quit."""
        window = self.window
        paintable = Gtk.WidgetPaintable.new(window)
        snapshot = Gtk.Snapshot.new()
        paintable.snapshot(snapshot, window.get_width(), window.get_height())
        node = snapshot.to_node()
        if node is not None:
            texture = window.get_native().get_renderer().render_texture(node, None)
            texture.save_to_png(self._snapshot_path)
            print(f"snapshot written: {self._snapshot_path}", file=sys.stderr)
        self.quit()
        return False


def run_gui(argv: list[str]) -> int:
    app = FrequenzApp()
    return app.run(argv)
