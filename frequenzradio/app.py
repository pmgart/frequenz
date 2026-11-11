"""Adw.Application entry point for the desktop app."""

from __future__ import annotations

import logging
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .paths import APP_ID, APP_NAME, asset  # noqa: E402

log = logging.getLogger("frequenzradio.app")


class FrequenzApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        self.window = None
        self._snapshot_path = os.environ.get("FREQUENZ_SNAPSHOT")
        self.connect("startup", self._on_startup)
        self.connect("activate", self._on_activate)
        self.connect("shutdown", self._on_shutdown)

    def _on_startup(self, app) -> None:
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
        # Close the window instead of quitting outright: close-request performs the
        # player/catalog teardown and the final state save.
        quit_action.connect(
            "activate",
            lambda *_: self.window.close() if self.window is not None else self.quit(),
        )
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def _on_activate(self, app) -> None:
        if self.window is None:
            from .window import MainWindow

            try:
                self.window = MainWindow(app)
            except Exception as exc:  # e.g. no playbin element, broken GTK install
                log.exception("application startup failed")
                dialog = Adw.AlertDialog(
                    heading="FREQUENZ could not start",
                    body=str(exc),
                )
                dialog.add_response("close", "Close")
                dialog.connect("response", lambda *_: self.quit())
                dialog.present(None)
                return
            self.window.set_title(APP_NAME)
            if self._snapshot_path:
                try:
                    delay = max(0, int(os.environ.get("FREQUENZ_SNAPSHOT_AFTER", "6")))
                except ValueError:
                    delay = 6
                GLib.timeout_add_seconds(delay, self._take_snapshot)
        self.window.present()

    def _on_shutdown(self, app) -> None:
        # Stop the background catalog download; otherwise the interpreter waits for its worker threads.
        if self.window is not None:
            self.window.stop_background_work()

    def _take_snapshot(self) -> bool:
        """Test hook: write the window's current rendering to PNG and quit."""
        try:
            window = self.window
            if window is None:
                raise RuntimeError("no window to snapshot")
            paintable = Gtk.WidgetPaintable.new(window)
            snapshot = Gtk.Snapshot.new()
            paintable.snapshot(snapshot, window.get_width(), window.get_height())
            node = snapshot.to_node()
            if node is None:
                raise RuntimeError("window produced no render node")
            native = window.get_native()
            renderer = native.get_renderer() if native is not None else None
            if renderer is None:
                raise RuntimeError("window has no renderer")
            texture = renderer.render_texture(node, None)
            texture.save_to_png(self._snapshot_path)
            print(f"snapshot written: {self._snapshot_path}", file=sys.stderr)
        except Exception as exc:  # a broken hook must not hang the app
            print(f"snapshot failed: {exc}", file=sys.stderr)
        finally:
            self.quit()
        return False


def run_gui(argv: list[str]) -> int:
    app = FrequenzApp()
    return app.run(argv)
