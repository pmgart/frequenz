"""Audio playback with GStreamer ``playbin3`` (PipeWire or PulseAudio output).

* Streams are opened through Radio Garden's ``listen`` endpoint, which 302-redirects to
  the broadcaster's stream; GStreamer's souphttpsrc follows the redirect.
* ICY (Shoutcast/Icecast) metadata is requested, so the "now playing" title appears.
* Every play, pause or reconnect builds a fresh pipeline and discards the old one.
  Bus messages from a discarded pipeline are ignored, so a late error from a previous
  connection can never affect the current station.
* Only audio is decoded. No pre-roll or advertising media is ever requested.
* Network errors reconnect a few times with a short back-off before reporting failure.
"""

from __future__ import annotations

import logging
from typing import Callable

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

log = logging.getLogger("frequenzradio.player")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 Frequenz/0.1"
)
GST_PLAY_FLAG_VIDEO = 1 << 0
GST_PLAY_FLAG_AUDIO = 1 << 1
GST_PLAY_FLAG_TEXT = 1 << 2
MAX_RECONNECTS = 2
SOURCE_TIMEOUT_S = 20


def clean_icy_title(raw: str) -> str | None:
    """Tidy an ICY StreamTitle. Some stations send JSON or bare numbers instead of a song title."""
    title = " ".join(raw.split())  # one line, no control characters
    if not title or title.startswith(("{", "[")) or title.isdigit():
        return None
    return title


class Player:
    """Single-stream audio player. All methods and callbacks run on the GLib main loop."""

    def __init__(self, audio_sink: str | None = None) -> None:
        Gst.init(None)
        self._factory = "playbin3" if Gst.ElementFactory.find("playbin3") else "playbin"
        if Gst.ElementFactory.find(self._factory) is None:
            raise RuntimeError(f"GStreamer element {self._factory!r} is not available")
        self._audio_sink_name = audio_sink
        self._volume = 1.0
        self.pipeline = None

        self.uri: str | None = None
        self.title = ""  # live ICY title for the current station
        self.state = "stopped"  # stopped | loading | playing | buffering | paused | error
        self.error: str | None = None
        self._reconnects = 0
        self._reconnect_timer = 0
        self._want_playing = False

        self.on_state: Callable[[str], None] | None = None
        self.on_title: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None

    # -- public API --------------------------------------------------------------
    def load(self, uri: str) -> None:
        """Start a station from scratch."""
        self._cancel_reconnect()
        self.uri = uri
        self.title = ""
        self.error = None
        self._reconnects = 0
        self._start(loading=True)

    def play(self) -> None:
        if self.uri is None:
            return
        self._cancel_reconnect()
        self._reconnects = 0
        self._start(loading=True)

    def pause(self) -> None:
        """Live radio: pausing disconnects instead of buffering in the background."""
        self._want_playing = False
        self._cancel_reconnect()
        self._destroy_pipeline()
        self._set_state_name("paused")

    def begin_loading(self) -> None:
        """Show 'connecting' while the stream address is being resolved."""
        self._cancel_reconnect()
        self._destroy_pipeline()
        self._want_playing = True
        self.title = ""
        self.error = None
        self._reconnects = 0
        self._set_state_name("loading")

    def toggle(self) -> None:
        if self._want_playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        self._cancel_reconnect()
        self._destroy_pipeline()
        self.uri = None
        self.title = ""
        self._want_playing = False
        self._set_state_name("stopped")

    def set_volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, value))
        if self.pipeline is not None:
            self.pipeline.set_property("volume", self._volume)

    def volume(self) -> float:
        return self._volume

    def position_seconds(self) -> float | None:
        if self.pipeline is None:
            return None
        ok, position = self.pipeline.query_position(Gst.Format.TIME)
        if not ok or position < 0:
            return None
        return position / Gst.SECOND

    def shutdown(self) -> None:
        self._cancel_reconnect()
        self._destroy_pipeline()

    # -- pipeline lifecycle ------------------------------------------------------
    def _build_pipeline(self):
        pipeline = Gst.ElementFactory.make(self._factory, "frequenz-player")
        if self._audio_sink_name:
            pipeline.set_property("audio-sink", Gst.ElementFactory.make(self._audio_sink_name, None))
        flags = pipeline.get_property("flags")
        pipeline.set_property("flags", (flags & ~(GST_PLAY_FLAG_VIDEO | GST_PLAY_FLAG_TEXT)) | GST_PLAY_FLAG_AUDIO)
        pipeline.set_property("volume", self._volume)
        pipeline.connect("source-setup", self._on_source_setup)
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message, pipeline)
        return pipeline

    def _destroy_pipeline(self) -> None:
        pipeline, self.pipeline = self.pipeline, None
        if pipeline is None:
            return
        pipeline.get_bus().remove_signal_watch()
        pipeline.set_state(Gst.State.NULL)

    def _start(self, *, loading: bool) -> None:
        self._destroy_pipeline()
        self._want_playing = True
        self.pipeline = self._build_pipeline()
        self.pipeline.set_property("uri", self.uri)
        if loading:
            self._set_state_name("loading")
        self.pipeline.set_state(Gst.State.PLAYING)

    # -- internals ---------------------------------------------------------------
    def _set_state_name(self, name: str) -> None:
        if name != self.state:
            self.state = name
            if self.on_state:
                self.on_state(name)

    def _emit_error(self, text: str) -> None:
        self.error = text
        self._set_state_name("error")
        if self.on_error:
            self.on_error(text)

    def _on_source_setup(self, pipeline, source) -> None:
        # Ask for ICY metadata (now-playing titles) and identify ourselves politely.
        # A dead station should fail in ~12 s instead of GStreamer's default 15 s.
        if source.find_property("iradio-mode") is not None:
            source.set_property("iradio-mode", True)
        if source.find_property("user-agent") is not None:
            source.set_property("user-agent", USER_AGENT)
        if source.find_property("timeout") is not None:
            source.set_property("timeout", SOURCE_TIMEOUT_S)

    def _on_bus_message(self, bus, message, pipeline) -> None:
        if pipeline is not self.pipeline:
            return  # stale: from a pipeline we already discarded
        mtype = message.type
        if mtype == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            log.warning("GStreamer error: %s (%s)", error.message, debug)
            self._handle_failure(error.message)
        elif mtype == Gst.MessageType.EOS:
            self._handle_failure("stream ended")
        elif mtype == Gst.MessageType.STATE_CHANGED and message.src is pipeline:
            _, new, _ = message.parse_state_changed()
            if new == Gst.State.PLAYING:
                self._set_state_name("playing")
        elif mtype == Gst.MessageType.BUFFERING:
            percent = message.parse_buffering()
            if percent < 50 and self.state == "playing":
                self._set_state_name("buffering")
            elif percent >= 50 and self.state == "buffering":
                self._set_state_name("playing")
        elif mtype == Gst.MessageType.TAG:
            tags = message.parse_tag()
            found, title = tags.get_string(Gst.TAG_TITLE)
            cleaned = clean_icy_title(title) if found and title else None
            if cleaned and cleaned != self.title:
                self.title = cleaned
                if self.on_title:
                    self.on_title(self.title)

    def _handle_failure(self, text: str) -> None:
        if self.uri is None or not self._want_playing:
            return
        self._destroy_pipeline()
        if self._reconnects < MAX_RECONNECTS:
            self._reconnects += 1
            delay_ms = 1500 * self._reconnects
            log.info("reconnecting in %d ms (attempt %d)", delay_ms, self._reconnects)
            self._set_state_name("loading")
            self._reconnect_timer = GLib.timeout_add(delay_ms, self._reconnect)
            return
        self._want_playing = False
        self._emit_error(text)

    def _reconnect(self) -> bool:
        self._reconnect_timer = 0
        if self.uri is not None and self._want_playing:
            self._start(loading=False)
        return GLib.SOURCE_REMOVE

    def _cancel_reconnect(self) -> None:
        if self._reconnect_timer:
            GLib.source_remove(self._reconnect_timer)
            self._reconnect_timer = 0
