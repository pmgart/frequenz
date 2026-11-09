"""Adw.Application entry point for the desktop app."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .geodata import is_built  # noqa: E402
from .osinfo import quit_accels  # noqa: E402
from .paths import APP_ID, APP_NAME, asset, globe_dir  # noqa: E402


def seed_bundled_globe() -> None:
    """Inside the Mac app bundle, copy the pre-built globe map into the data folder on first launch."""
    bundle = os.environ.get("FREQUENZ_BUNDLE_RESOURCES")
    if not bundle:
        return
    source = Path(bundle) / "globe"
    target = globe_dir()
    if is_built(source) and not is_built(target):
        shutil.copytree(source, target, dirs_exist_ok=True)


class FrequenzApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window = None
        self._snapshot_path = os.environ.get("FREQUENZ_SNAPSHOT")
        self.connect("startup", self._on_startup)
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def _on_startup(self, app) -> None:
        try:
            seed_bundled_globe()
        except OSError as exc:  # a read-only or full data folder must not stop the app
            print(f"could not copy the bundled globe map: {exc}", file=sys.stderr)
        from .state import AppState
        from .theme import apply_scheme, normalize

        apply_scheme(normalize(AppState.load().theme))
        provider = Gtk.CssProvider()
        provider.load_from_path(str(asset("style.css")))
        display = Gdk.Display.get_default()
        if display is not None:
            # The design tokens must win over personal GTK CSS (for example ~/.config/gtk-4.0/gtk.css,
            # which sets dark headerbar and sidebar colours). GTK ranks user CSS above app CSS, so the
            # stylesheet is added at the user-override priority.
            Gtk.StyleContext.add_provider_for_display(display, provider,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_USER)
            icon_theme = Gtk.IconTheme.get_for_display(display)
            icon_theme.add_search_path(str(asset("icons")))
            icon_theme.add_search_path(str(asset("icons") / "symbolic"))
        Gtk.Window.set_default_icon_name(APP_ID)

        from gi.repository import Gio

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", quit_accels())

    def _on_activate(self, app) -> None:
        if self.window is None:
            from .window import MainWindow

            self.window = MainWindow(app)
            self.window.set_title(APP_NAME)
            if self._snapshot_path:
                GLib.timeout_add_seconds(int(os.environ.get("FREQUENZ_SNAPSHOT_AFTER", "6")),
                                         self._take_snapshot)
        self.window.present()

    def _on_shutdown(self, app) -> None:
        # Stop the background catalog download; otherwise the interpreter waits for its worker threads.
        if self.window is not None:
            self.window.stop_background_work()

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
