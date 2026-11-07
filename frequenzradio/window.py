"""Main window: the globe, a station sidebar (place / search / favorites) and the player bar.

Threading: everything touches GTK and the main catalog connection on the GLib main
loop. The catalog updater runs in a worker thread with its own SQLite connection and
hands progress back with GLib.idle_add.
"""

from __future__ import annotations

import dataclasses
import logging
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from .api import BASE_URL, RadioGardenClient  # noqa: E402
from .catalog import Catalog  # noqa: E402
from . import geo  # noqa: E402
from .globe import GlobeView, PlaceSet  # noqa: E402
from .paths import APP_ID, APP_NAME, catalog_path, globe_dir  # noqa: E402
from .player import Player  # noqa: E402
from .state import AppState  # noqa: E402
from .theme import apply_scheme, normalize, other, window_class  # noqa: E402
from .sync import SyncReport, sync_places, sync_stations  # noqa: E402
from .preferences import open_preferences  # noqa: E402
from .text import format_location, monogram  # noqa: E402
from .widgets import LiveCard, Rail, SectionHeading, icon  # noqa: E402

log = logging.getLogger("frequenzradio.window")

# States in which the primary button shows pause: the stream runs or is starting.
PAUSE_STATES = frozenset({"playing", "buffering", "loading"})
PLAYER_HEIGHT = 152
MAX_AUTO_SKIPS = 3


class MainWindow(Adw.ApplicationWindow):
    __gtype_name__ = "RGMainWindow"

    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.set_default_size(1440, 900)
        self.set_size_request(1100, 720)
        self.catalog = Catalog(catalog_path())
        self.state = AppState.load()
        self.theme = normalize(self.state.theme)
        self.add_css_class(window_class(self.theme))
        apply_scheme(self.theme)
        self.places: PlaceSet | None = None
        self.selected_index: int | None = None
        self.playing_index: int | None = None
        self.current_row = None  # sqlite row of the station being played
        self.queue: list[str] = []
        self.queue_index: int | None = None
        self.sidebar_mode = "empty"
        self._sidebar_rows: list = []
        self._sync_thread: threading.Thread | None = None
        self._resolve_token: object | None = None
        self._auto_skips = 0
        self._sync_cancel = threading.Event()
        self._search_timeout = 0
        self._suppress_volume = False
        self._zoom_guard = False

        self.player = Player()
        self.player.on_state = self._on_player_state
        self.player.on_title = self._on_player_title
        self.player.on_error = self._on_player_error
        self.player.set_volume(self.state.volume)

        self._build_ui()
        self._install_actions()
        self._install_keys()
        self.connect("close-request", self._on_close_request)
        GLib.timeout_add_seconds(10, self._persist_view)

        self._reload_places()
        self._restore_last_station()
        stats = self.catalog.stats()
        if stats.places == 0 or stats.stations == 0:
            self._show_empty_catalog()
            self.start_sync()

    # -- layout ------------------------------------------------------------------
    def _build_ui(self) -> None:
        header = self._build_header()
        self.rail = self._build_rail()
        self.zoom_scale = self._build_zoom_scale()
        self.globe_note = Gtk.Label(css_classes=["fq-globe-note"], halign=Gtk.Align.CENTER,
                                    valign=Gtk.Align.CENTER, wrap=True, visible=False)
        self.globe_note.set_can_target(False)
        self.globe = GlobeView(
            globe_dir(),
            on_select=self._on_globe_select,
            on_hover=self._on_globe_hover,
            on_focus=lambda index: None,
            on_zoom=self._on_zoom_changed,
        )
        self.globe.yaw, self.globe.pitch, self.globe.dist = (
            self.state.yaw, self.state.pitch, geo.clamp_distance(self.state.dist))
        self.globe.auto_rotate = self.state.auto_rotate
        overlay = Gtk.Overlay()
        overlay.set_child(self.globe)

        self.hover_label = Gtk.Label(css_classes=["rg-hover"], halign=Gtk.Align.START, valign=Gtk.Align.START)
        self.hover_label.set_visible(False)
        self.hover_label.set_can_target(False)
        overlay.add_overlay(self.hover_label)
        overlay.add_overlay(self.globe_note)
        overlay.add_overlay(self._build_zoom_controls())

        self.split = Adw.OverlaySplitView()
        self.split.set_content(overlay)
        self.split.set_sidebar(self._build_panel())
        self.split.set_sidebar_position(Gtk.PackType.END)
        self.split.set_min_sidebar_width(540)
        self.split.set_max_sidebar_width(620)
        self.split.set_sidebar_width_fraction(0.36)
        self.split.set_hexpand(True)
        self.sidebar_button.bind_property(
            "active", self.split, "show-sidebar",
            GObject.BindingFlags.SYNC_CREATE | GObject.BindingFlags.BIDIRECTIONAL,
        )

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        body.append(self.rail)
        body.append(self.split)

        self.player_bar = self._build_player_bar()
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bottom.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, css_classes=["fq-hairline"]))
        bottom.append(self.player_bar)

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(body)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_bottom_bar(bottom)
        toolbar.set_content(self.toasts)
        self.set_content(toolbar)

    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar(css_classes=["fq-header"])
        header.set_title_widget(Gtk.Box())  # no centred window title: the wordmark sits at the left
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, valign=Gtk.Align.CENTER,
                        margin_start=10)
        brand.append(Gtk.Label(label="//", css_classes=["fq-slash"]))
        brand.append(Gtk.Label(label="FREQUENZ", css_classes=["fq-wordmark"]))
        brand.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, css_classes=["fq-rule"]))
        brand.append(Gtk.Label(label="THE WORLD IS ON AIR", css_classes=["fq-tagline"]))
        header.pack_start(brand)

        switch = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2, valign=Gtk.Align.CENTER,
                         margin_end=8, css_classes=["fq-theme-switch"])
        self.theme_light = Gtk.ToggleButton(icon_name="fq-sun-symbolic", tooltip_text="Light theme",
                                            css_classes=["flat", "fq-theme-option"])
        self.theme_dark = Gtk.ToggleButton(icon_name="fq-moon-symbolic", tooltip_text="Dark theme",
                                           css_classes=["flat", "fq-theme-option"])
        self.theme_dark.set_group(self.theme_light)
        for button in (self.theme_light, self.theme_dark):
            button.connect("toggled", self._on_theme_toggled)
            switch.append(button)
        header.pack_end(switch)
        self._sync_theme_toggles()
        return header

    def _build_rail(self) -> Rail:
        rail = Rail()
        self.globe_button = rail.add_toggle("globe", "fq-globe-symbolic", "Globe", active=True)
        self.sidebar_button = rail.add_toggle("panel", "fq-radio-symbolic", "Show station panel", active=True,
                                style="fq-rail-panel")
        self.favorites_button = rail.add_toggle("favorites", "fq-heart-symbolic", "Favorites (F)")
        self.recent_button = rail.add_toggle("recent", "fq-clock-symbolic", "Recently played")
        self.favorites_button.set_group(self.globe_button)
        self.recent_button.set_group(self.globe_button)
        for button in (self.globe_button, self.favorites_button, self.recent_button):
            button.connect("toggled", self._on_rail_toggled)
        rail.add_spacer()
        preferences = rail.add_button("settings", "fq-settings-symbolic", "Preferences")
        preferences.connect("clicked", lambda *_: open_preferences(self))
        return rail

    def _build_panel(self) -> Gtk.Box:
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, css_classes=["fq-panel"],
                        margin_top=24, margin_start=24, margin_end=24, margin_bottom=20)
        self.search = Gtk.SearchEntry(placeholder_text="Search stations, places or countries",
                                      css_classes=["fq-search"])
        self.search.connect("search-changed", self._on_search_changed)
        self.search.connect("activate", lambda *_: self._run_search(self.search.get_text()))
        panel.append(self.search)

        self.live_card = LiveCard()
        self.fav_button = self.live_card.fav_button
        self.fav_button.connect("toggled", self._on_fav_button_toggled)
        panel.append(self.live_card)

        self.side_title = SectionHeading()
        panel.append(self.side_title)

        self.side_stack = Gtk.Stack(vexpand=True)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.station_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["fq-list"])
        self.station_list.connect("row-activated", self._on_row_activated)
        scroller.set_child(self.station_list)
        self.side_stack.add_named(scroller, "list")
        self.empty_page = Adw.StatusPage(icon_name="fq-radio-symbolic", title="No stations here",
                                         description="Pick a place on the globe, or search above.")
        self.side_stack.add_named(self.empty_page, "empty")
        panel.append(self.side_stack)
        self.side_title.set_title("Stations")
        self.empty_page.set_title("Pick a place")
        self.empty_page.set_description("Click a dot on the globe, search above, or press R for a random station.")
        self.side_stack.set_visible_child_name("empty")
        return panel

    def _build_zoom_scale(self) -> Gtk.Scale:
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.VERTICAL, 0.0, 1.0, 0.01)
        scale.set_draw_value(False)
        scale.set_size_request(-1, 150)
        scale.set_tooltip_text("Zoom: drag here, or scroll over the globe")
        scale.add_css_class("fq-zoom-scale")
        scale.connect("value-changed", self._on_zoom_slider)
        return scale

    def _build_zoom_controls(self) -> Gtk.Box:
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, css_classes=["fq-zoom"],
                           halign=Gtk.Align.START, valign=Gtk.Align.END, margin_start=24, margin_bottom=24)
        zoom_in = Gtk.Button(child=icon("fq-plus-symbolic", 18), tooltip_text="Zoom in one level (+)",
                             css_classes=["flat", "fq-zoom-button"])
        zoom_in.connect("clicked", lambda *_: self.globe.zoom_step(1))
        zoom_out = Gtk.Button(child=icon("fq-minus-symbolic", 18), tooltip_text="Zoom out one level (\u2212)",
                              css_classes=["flat", "fq-zoom-button"])
        zoom_out.connect("clicked", lambda *_: self.globe.zoom_step(-1))
        controls.append(zoom_in)
        controls.append(self.zoom_scale)
        controls.append(zoom_out)
        return controls

    def _build_player_bar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, css_classes=["rg-player"])
        bar.set_size_request(-1, PLAYER_HEIGHT)

        info = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16, valign=Gtk.Align.CENTER,
                       margin_start=24)
        self.now_tile = Gtk.Label(label="•", css_classes=["fq-tile"], valign=Gtk.Align.CENTER)
        self.now_tile.set_size_request(56, 56)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        self.now_title = Gtk.Label(label="Pick a station", xalign=0, ellipsize=Pango.EllipsizeMode.END,
                                   css_classes=["rg-title"], max_width_chars=40)
        self.now_sub = Gtk.Label(label="Click a dot on the globe", xalign=0,
                                 ellipsize=Pango.EllipsizeMode.END, css_classes=["fq-place"], hexpand=True)
        text.append(self.now_title)
        text.append(self.now_sub)
        info.append(self.now_tile)
        info.append(text)
        info.set_hexpand(True)
        bar.append(info)

        self.prev_button = Gtk.Button(icon_name="fq-skip-back-symbolic", tooltip_text="Previous (←)",
                                      css_classes=["flat", "circular", "fq-transport"])
        self.prev_button.connect("clicked", lambda *_: self.play_relative(-1))
        self.play_button = Gtk.Button(icon_name="fq-play-symbolic", tooltip_text="Play / pause (Space)",
                                      css_classes=["circular", "rg-play"])
        self.play_button.connect("clicked", lambda *_: self.toggle_play())
        self.next_button = Gtk.Button(icon_name="fq-skip-forward-symbolic", tooltip_text="Next (→)",
                                      css_classes=["flat", "circular", "fq-transport"])
        self.next_button.connect("clicked", lambda *_: self.play_relative(1))
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=22, valign=Gtk.Align.CENTER)
        controls.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, css_classes=["fq-rule"]))
        for button in (self.prev_button, self.play_button, self.next_button):
            controls.append(button)
        controls.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, css_classes=["fq-rule"]))
        bar.append(controls)

        right = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, valign=Gtk.Align.CENTER,
                        margin_end=28)
        right.append(Gtk.Box(hexpand=True))
        right.append(icon("fq-volume-2-symbolic", 20))
        self.volume = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.02)
        self.volume.set_size_request(200, -1)
        self.volume.set_draw_value(False)
        self.volume.set_value(self.state.volume)
        self.volume.connect("value-changed", self._on_volume_changed)
        right.append(self.volume)
        right.set_hexpand(True)
        bar.append(right)
        return bar

    def _on_theme_toggled(self, button) -> None:
        if button.get_active():
            self.set_theme_name("light" if button is self.theme_light else "dark")

    def _sync_theme_toggles(self) -> None:
        for button, theme in ((self.theme_light, "light"), (self.theme_dark, "dark")):
            button.handler_block_by_func(self._on_theme_toggled)
            button.set_active(self.theme == theme)
            button.handler_unblock_by_func(self._on_theme_toggled)

    def set_theme_name(self, theme_name: str) -> None:
        """Switch the design tokens (dark or light) and remember the choice."""
        theme = normalize(theme_name)
        if theme == self.theme:
            return
        self.theme = theme
        for name in ("fq-dark", "fq-light"):
            self.remove_css_class(name)
        self.add_css_class(window_class(self.theme))
        apply_scheme(self.theme)
        self.state.theme = self.theme
        self.state.save()
        self._sync_theme_toggles()

    # -- actions and keys --------------------------------------------------------
    def _install_actions(self) -> None:
        for name, callback in [
            ("sync", lambda *_: self.start_sync()),
            ("about", lambda *_: self._show_about()),
            ("shortcuts", lambda *_: self._show_shortcuts()),
            ("theme", lambda *_: self.set_theme_name(other(self.theme))),
            ("preferences", lambda *_: open_preferences(self)),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def _install_keys(self) -> None:
        controller = Gtk.EventControllerKey.new()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        name = Gdk.keyval_name(keyval) or ""
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if ctrl and name.lower() == "f":
            self.search.grab_focus()
            return True
        focus = self.get_focus()
        if isinstance(focus, Gtk.Editable):
            if name == "Escape":
                self.search.set_text("")
                self.globe.grab_focus()
                return True
            return False
        actions = {
            "space": self.toggle_play,
            "Left": lambda: self.play_relative(-1),
            "Right": lambda: self.play_relative(1),
            "p": lambda: self.play_relative(-1),
            "n": lambda: self.play_relative(1),
            "f": self.toggle_current_favorite,
            "r": self.play_random,
            "slash": lambda: self.search.grab_focus(),
            "plus": lambda: self.globe.zoom_step(1),
            "equal": lambda: self.globe.zoom_step(1),
            "minus": lambda: self.globe.zoom_step(-1),
            "0": self.globe.reset_view,
            "a": lambda: self.set_auto_rotate(not self.globe.auto_rotate),
            "Escape": self._clear_selection,
        }
        action = actions.get(name)
        if action is None:
            return False
        action()
        return True

    # -- catalog views -----------------------------------------------------------
    def _reload_places(self) -> None:
        rows = self.catalog.places()
        if rows:
            self.places = PlaceSet.from_rows(rows)
            self.globe.set_places(self.places)

    def _clear_list(self) -> None:
        child = self.station_list.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.station_list.remove(child)
            child = nxt

    def _show_rows(self, title: str, subtitle: str, rows: list, *, empty_text: str) -> None:
        self.side_title.set_title(title)
        self.side_title.set_subtitle(subtitle)
        self._clear_list()
        self._sidebar_rows = list(rows)
        if not rows:
            self.empty_page.set_title("Nothing here")
            self.empty_page.set_description(empty_text)
            self.side_stack.set_visible_child_name("empty")
            return
        for row in rows:
            self.station_list.append(self._station_row(row))
        self.side_stack.set_visible_child_name("list")
        self._highlight_playing_row()

    def _show_now(self, row) -> None:
        """Show the playing station in the bar, its monogram tile and the now-playing card."""
        place = format_location(row["place_title"], row["country"]) or "Radio station"
        self.now_tile.set_label(monogram(row["title"]))
        self.now_title.set_label(row["title"])
        self.now_sub.set_label(place)
        self.live_card.set_station(row["title"], place)

    def _station_row(self, row) -> Gtk.ListBoxRow:
        station_id = row["id"]
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14, margin_top=12, margin_bottom=12,
                       margin_start=6, margin_end=6)
        play = Gtk.Button(icon_name="fq-play-symbolic", tooltip_text="Play", css_classes=["flat", "fq-row-play"],
                          valign=Gtk.Align.CENTER)
        play.connect("clicked", self._on_row_play, station_id)
        line.append(play)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True, valign=Gtk.Align.CENTER)
        title = Gtk.Label(label=row["title"], xalign=0, ellipsize=Pango.EllipsizeMode.END,
                          css_classes=["fq-row-title"], max_width_chars=44)
        place = Gtk.Label(label=format_location(row["place_title"], row["country"]) or "RADIO STATION",
                          xalign=0, ellipsize=Pango.EllipsizeMode.END, css_classes=["fq-row-place"],
                          hexpand=True)
        text.append(title)
        text.append(place)
        line.append(text)
        is_favorite = self.catalog.is_favorite(station_id)
        fav = Gtk.ToggleButton(icon_name="fq-heart-filled-symbolic" if is_favorite else "fq-heart-symbolic",
                               tooltip_text="Favorite", css_classes=["flat", "fq-row-fav"],
                               valign=Gtk.Align.CENTER)
        fav.set_active(is_favorite)
        fav.connect("toggled", self._on_row_fav_toggled, station_id)
        line.append(fav)
        content.append(line)
        content.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, css_classes=["fq-hairline"]))
        list_row = Gtk.ListBoxRow(child=content, activatable=True)
        list_row.station_id = station_id
        list_row.title_label = title
        return list_row

    def _on_row_play(self, button, station_id: str) -> None:
        ids = [r["id"] for r in self._sidebar_rows]
        self.play_station(station_id, queue=ids)

    def _highlight_playing_row(self) -> None:
        current = self.current_row["id"] if self.current_row is not None else None
        child = self.station_list.get_first_child()
        while child is not None:
            if hasattr(child, "title_label"):
                if getattr(child, "station_id", None) == current:
                    child.title_label.add_css_class("rg-now")
                else:
                    child.title_label.remove_css_class("rg-now")
            child = child.get_next_sibling()

    def _on_row_fav_toggled(self, button, station_id: str) -> None:
        self.catalog.set_favorite(station_id, button.get_active())
        button.set_icon_name("fq-heart-filled-symbolic" if button.get_active() else "fq-heart-symbolic")
        if self.current_row is not None and self.current_row["id"] == station_id:
            self._sync_fav_button()
        if self.favorites_button.get_active():
            self._show_favorites()

    def _on_row_activated(self, listbox, row) -> None:
        station_id = getattr(row, "station_id", None)
        if station_id is None:
            return
        ids = [r["id"] for r in self._sidebar_rows]
        self.play_station(station_id, queue=ids)

    def open_place(self, index: int, *, play: bool) -> None:
        if self.places is None:
            return
        place_id = self.places.ids[index]
        rows = self.catalog.stations_in_place(place_id)
        title = self.places.titles[index]
        self.sidebar_mode = "place"
        self._set_rail_view("globe")
        self._show_rows(f"Stations in {title}", f"({len(rows)})", rows,
                        empty_text="This place has no stations in the catalog yet.")
        if play and rows:
            ids = [r["id"] for r in rows]
            self.play_station(ids[0], queue=ids)

    def _show_favorites(self) -> None:
        rows = self.catalog.favorites()
        self.sidebar_mode = "favorites"
        self._set_rail_view("favorites")
        self._show_rows("Favorites", f"{len(rows)} saved", rows,
                        empty_text="Press the heart on any station to save it here.")

    def _show_recent(self) -> None:
        rows = self.catalog.recent(limit=30)
        self.sidebar_mode = "recent"
        self._set_rail_view("recent")
        self._show_rows("Recently played", f"{len(rows)} stations", rows,
                        empty_text="Stations you play appear here.")

    def _run_search(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        rows = self.catalog.search(text, limit=120)
        self.sidebar_mode = "search"
        self._set_rail_view("globe")
        self._show_rows(f"“{text}”", f"{len(rows)} stations found", rows,
                        empty_text="No station matches. Try a shorter word or a country name.")

    def _on_search_changed(self, entry) -> None:
        if self._search_timeout:
            GLib.source_remove(self._search_timeout)
        text = entry.get_text()
        self._search_timeout = GLib.timeout_add(220, self._search_now, text)

    def _search_now(self, text: str) -> bool:
        self._search_timeout = 0
        if text.strip():
            self._run_search(text)
        return GLib.SOURCE_REMOVE

    def _on_rail_toggled(self, button) -> None:
        """Rail views: globe (default), favorites and recent. Only the view that was switched on acts."""
        if not button.get_active():
            return
        if button is self.favorites_button:
            self._show_favorites()
        elif button is self.recent_button:
            self._show_recent()
        else:
            self._clear_selection()

    def _set_rail_view(self, view: str) -> None:
        """Mark the rail item for the list on screen, without running its action."""
        for key, button in (("globe", self.globe_button), ("favorites", self.favorites_button),
                            ("recent", self.recent_button)):
            button.handler_block_by_func(self._on_rail_toggled)
            button.set_active(key == view)
            button.handler_unblock_by_func(self._on_rail_toggled)

    def _clear_selection(self) -> None:
        self.selected_index = None
        self.globe.set_states(selected=None, playing=self.playing_index)
        self._set_rail_view("globe")
        self.sidebar_mode = "empty"
        self.side_title.set_title("Stations")
        self.side_title.set_subtitle("")
        self.side_stack.set_visible_child_name("empty")
        self.empty_page.set_title("Pick a place")
        self.empty_page.set_description("Click a dot on the globe, search above, or press R for a random station.")

    def _show_empty_catalog(self) -> None:
        self.side_title.set_title("Station catalog needed")
        self.side_title.set_subtitle("First run")
        self.empty_page.set_title("Downloading the station list")
        self.empty_page.set_description(
            "FREQUENZ stores every station locally so the globe and search are instant. "
            "This one-time download takes about 15–20 minutes."
        )
        self.side_stack.set_visible_child_name("empty")

    # -- playback ----------------------------------------------------------------
    def play_station(self, station_id: str, *, queue: list[str] | None = None) -> None:
        row = self.catalog.station(station_id)
        if row is None:
            return
        if queue is not None:
            self.queue = list(queue)
        if station_id not in self.queue:
            self.queue = [station_id]
        self.queue_index = self.queue.index(station_id)
        self.current_row = row
        self.catalog.record_play(station_id)
        self._start_resolve(station_id)
        self.state.last_station = station_id
        self._show_now(row)
        self.player_bar.add_css_class("rg-playing")
        self._sync_fav_button()
        self._update_place_marker(row)
        self._highlight_playing_row()

    def _start_resolve(self, station_id: str) -> None:
        """Resolve the station's stream off the UI thread, then load it.

        The listen endpoint can take tens of seconds for some stations, so it is resolved in a
        worker with a longer timeout and GStreamer connects straight to the stream. A newer
        selection invalidates an older resolve.
        """
        token = object()
        self._resolve_token = token
        self.player.begin_loading()
        listen = f"{BASE_URL}/api/ara/content/listen/{station_id}/channel.mp3"

        def worker() -> None:
            try:
                client = RadioGardenClient(timeout=40.0, max_retries=1, retry_delay=1.0)
                target = client.resolve_stream(station_id)
            except Exception as exc:  # noqa: BLE001 - fall back to the listen URL
                log.info("stream resolve failed (%s); using the listen URL", exc)
                target = None
            GLib.idle_add(self._on_resolved, token, target or listen)

        threading.Thread(target=worker, name="rg-resolve", daemon=True).start()

    def _on_resolved(self, token: object, url: str) -> bool:
        if token is not self._resolve_token:
            return GLib.SOURCE_REMOVE
        self._resolve_token = None
        self.player.load(url)
        return GLib.SOURCE_REMOVE

    def _update_place_marker(self, row) -> None:
        if self.places is None or row["place_id"] is None:
            return
        index = self.places.index_by_id.get(row["place_id"])
        self.playing_index = index
        self.globe.set_states(selected=self.selected_index, playing=index)

    def _restore_last_station(self) -> None:
        last = self.state.last_station
        if not last:
            return
        row = self.catalog.station(last)
        if row is None:
            return
        self.current_row = row
        self.queue = [last]
        self.queue_index = 0
        self._show_now(row)
        self._sync_fav_button()
        self._update_place_marker(row)
        # Reopen the last place's station list on the right, without auto-playing,
        # and turn the globe to that place immediately (no animation on startup).
        if self.playing_index is not None:
            self.selected_index = self.playing_index
            self.globe.set_states(selected=self.selected_index, playing=self.playing_index)
            place = self.catalog.place(row["place_id"])
            if place is not None:
                self.globe.yaw, self.globe.pitch = geo.camera_angles_for(place["lng"], place["lat"])
            self.open_place(self.playing_index, play=False)

    def toggle_play(self) -> None:
        if self.current_row is None:
            self.play_random()
            return
        if self._resolve_token is not None:  # still connecting: cancel the pending start
            self._resolve_token = None
            self.player.pause()
            return
        if self.player.uri is None:
            self.play_station(self.current_row["id"], queue=self.queue or None)
            return
        self.player.toggle()

    def play_relative(self, delta: int) -> None:
        if not self.queue:
            if self.current_row is None:
                return
            self.queue = [self.current_row["id"]]
            self.queue_index = 0
        index = ((self.queue_index or 0) + delta) % len(self.queue)
        self.play_station(self.queue[index], queue=self.queue)

    def play_random(self) -> None:
        row = self.catalog.random_station()
        if row is None:
            self.toast("The catalog is empty. Use the menu to update it.")
            return
        self.play_station(row["id"], queue=[row["id"]])
        if row["place_id"] and self.places is not None:
            index = self.places.index_by_id.get(row["place_id"])
            if index is not None:
                self.selected_index = index
                self.globe.set_states(selected=index, playing=index)
                place_row = self.catalog.place(row["place_id"])
                if place_row is not None:
                    self.globe.focus_place(place_row["lng"], place_row["lat"], 3.3)
                    self.open_place(index, play=False)

    def toggle_current_favorite(self) -> None:
        if self.current_row is None:
            return
        station_id = self.current_row["id"]
        value = not self.catalog.is_favorite(station_id)
        self.catalog.set_favorite(station_id, value)
        self._sync_fav_button()
        self.toast("Added to favorites" if value else "Removed from favorites")

    def _sync_fav_button(self) -> None:
        if self.current_row is None:
            return
        active = self.catalog.is_favorite(self.current_row["id"])
        self.fav_button.handler_block_by_func(self._on_fav_button_toggled)
        self.fav_button.set_active(active)
        self.fav_button.set_icon_name("fq-heart-filled-symbolic" if active else "fq-heart-symbolic")
        self.fav_button.handler_unblock_by_func(self._on_fav_button_toggled)

    def _on_fav_button_toggled(self, button) -> None:
        if self.current_row is None:
            return
        self.catalog.set_favorite(self.current_row["id"], button.get_active())
        button.set_icon_name("fq-heart-filled-symbolic" if button.get_active() else "fq-heart-symbolic")
        if self.favorites_button.get_active():
            self._show_favorites()

    def _on_player_state(self, name: str) -> None:
        self.live_card.set_state(name)
        if name == "playing":
            self._auto_skips = 0
        self.play_button.set_icon_name("fq-pause-symbolic" if name in PAUSE_STATES else "fq-play-symbolic")
        if name == "error":
            reason = self.player.error or "unknown error"
            # A station that cannot start is skipped (a few in a row at most) so the list keeps playing.
            can_skip = (self._auto_skips < MAX_AUTO_SKIPS and self.queue_index is not None
                        and self.queue_index + 1 < len(self.queue))
            if can_skip:
                self._auto_skips += 1
                self.toast(f"Station unavailable ({reason}); trying the next one")
                GLib.timeout_add(700, lambda: (self.play_relative(1), GLib.SOURCE_REMOVE)[1])
            else:
                self.toast(f"Could not play this station: {reason}")

    def _on_player_title(self, title: str) -> None:
        if self.current_row is not None:
            self.now_sub.set_label(title)

    def _on_player_error(self, text: str) -> None:
        log.warning("playback error: %s", text)

    def _on_volume_changed(self, scale) -> None:
        value = scale.get_value()
        self.player.set_volume(value)
        self.state.volume = value

    # -- globe callbacks ---------------------------------------------------------
    def _on_globe_select(self, index: int) -> None:
        if index < 0:
            return
        self.selected_index = index
        self.globe.set_states(selected=index, playing=self.playing_index)
        self.open_place(index, play=True)

    def _on_zoom_changed(self, distance: float) -> None:
        """Keep the zoom slider in step with the globe, and say why the globe is missing when it is."""
        self._zoom_guard = True
        self.zoom_scale.set_value(geo.zoom_fraction(distance))
        self._zoom_guard = False
        note = ""
        if self.globe.gl_error:
            note = "3D globe unavailable: no usable OpenGL context"
        elif not self.globe.vector_map_ready:
            note = "Vector map not built: run 'frequenz build-globe'"
        self.globe_note.set_label(note)
        self.globe_note.set_visible(bool(note))

    def _on_globe_hover(self, index: int | None, x: float, y: float) -> None:
        if index is None or self.places is None:
            self.hover_label.set_visible(False)
            return
        title = self.places.titles[index]
        country = self.places.countries[index]
        count = int(self.places.counts[index])
        text = f"{title} · {country} · {count} station{'s' if count != 1 else ''}"
        self.hover_label.set_label(text)
        self.hover_label.set_margin_start(int(max(0, x + 14)))
        self.hover_label.set_margin_top(int(max(0, y + 14)))
        self.hover_label.set_visible(True)

    def set_auto_rotate(self, active: bool) -> None:
        self.globe.auto_rotate = active
        self.state.auto_rotate = active

    def _on_zoom_slider(self, scale) -> None:
        if not self._zoom_guard:
            self.globe.zoom_to(geo.zoom_distance(scale.get_value()))

    # -- catalog updates ---------------------------------------------------------
    def start_sync(self) -> None:
        if self._sync_thread is not None and self._sync_thread.is_alive():
            self.toast("The catalog is already updating")
            return
        self._sync_cancel = threading.Event()
        self._sync_thread = threading.Thread(target=self._sync_worker, name="rg-catalog", daemon=True)
        self.side_title.set_subtitle("Updating station catalog…")
        self.toast("Updating the station catalog in the background")
        self._sync_thread.start()

    def _sync_worker(self) -> None:
        catalog = Catalog(catalog_path())
        client = RadioGardenClient(min_interval=0.1)
        try:
            sync_places(client, catalog)
            GLib.idle_add(self._reload_places)

            def progress(report: SyncReport) -> None:
                GLib.idle_add(self._on_sync_progress, dataclasses.replace(report))

            report = sync_stations(client, catalog, workers=4, progress=progress, cancel=self._sync_cancel)
            GLib.idle_add(self._on_sync_done, dataclasses.replace(report))
        except Exception as exc:  # noqa: BLE001 - report to the user
            log.exception("catalog update failed")
            GLib.idle_add(self.toast, f"Catalog update failed: {exc}")
        finally:
            catalog.close()

    def _on_sync_progress(self, report: SyncReport) -> bool:
        done = report.places_done + report.places_failed
        self.side_title.set_subtitle(f"Updating catalog · {done}/{report.places_total} places")
        return GLib.SOURCE_REMOVE

    def _on_sync_done(self, report: SyncReport) -> bool:
        self._reload_places()
        stats = self.catalog.stats()
        self.side_title.set_subtitle(f"{stats.stations} stations in catalog")
        self.toast(f"Catalog updated: {stats.stations} stations, {report.places_failed} failed places")
        if self.side_stack.get_visible_child_name() == "empty" and self.sidebar_mode == "empty":
            self._clear_selection()
        return GLib.SOURCE_REMOVE

    # -- misc --------------------------------------------------------------------
    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast.new(text))

    def _persist_view(self) -> bool:
        self.state.yaw = self.globe.yaw
        self.state.pitch = self.globe.pitch
        self.state.dist = self.globe.dist
        self.state.auto_rotate = self.globe.auto_rotate
        self.state.save()
        return GLib.SOURCE_CONTINUE

    def stop_background_work(self) -> None:
        """Ask the catalog download to stop; called when the application quits."""
        self._sync_cancel.set()

    def _on_close_request(self, window) -> bool:
        self._persist_view()
        self.player.shutdown()
        self.catalog.close()
        return False

    def _show_about(self) -> None:
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            developer_name="Unofficial desktop client",
            version="0.1.1",
            website=BASE_URL,
            comments=("A native, local and ad-free radio globe for Linux. "
                      "Station data and streams belong to their owners; see the README."),
        )
        about.present(self)

    def _show_shortcuts(self) -> None:
        text = (
            "Space — play / pause\n← / → (or P / N) — previous / next station\n"
            "F — favorite the playing station\nR — random station\n"
            "/ or Ctrl+F — search\n+ / − — zoom one level in or out, 0 — reset view, A — slow auto-rotate\n"
            "Click a dot — tune in; double-click — zoom to the place\n"
            "Escape — clear the list; Ctrl+Q — quit"
        )
        dialog = Adw.AlertDialog(heading="Keyboard shortcuts", body=text)
        dialog.add_response("close", "Close")
        dialog.present(self)
