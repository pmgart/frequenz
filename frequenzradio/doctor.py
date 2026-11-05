"""Environment check for the desktop app: GTK 4, libadwaita, GStreamer, OpenGL, catalog."""

from __future__ import annotations

import os

from .geodata import is_built
from .paths import catalog_path, globe_dir

GST_ELEMENTS = ("playbin3", "souphttpsrc", "decodebin", "autoaudiosink")
AUDIO_DECODERS = ("mpg123audiodec", "avdec_aac", "opusdec", "vorbisdec", "flacdec")


def run_doctor() -> int:
    failures = 0

    def report(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
        nonlocal failures
        if not ok and not warn_only:
            failures += 1
        status = "ok" if ok else ("warn" if warn_only else "FAIL")
        print(f"[{status:>4}] {name}" + (f": {detail}" if detail else ""))

    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        gi.require_version("Gst", "1.0")
        from gi.repository import Adw, Gst, Gtk

        report(
            "GTK 4 + libadwaita (PyGObject)",
            True,
            f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}, "
            f"libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}",
        )
        Gst.init(None)
        report("GStreamer", True, Gst.version_string())
        for name in GST_ELEMENTS:
            report(f"GStreamer element '{name}'", Gst.ElementFactory.find(name) is not None)
        decoders = [name for name in AUDIO_DECODERS if Gst.ElementFactory.find(name)]
        report(
            "audio decoders (MP3/AAC/Opus/Vorbis/FLAC)",
            bool(decoders),
            ", ".join(decoders) or "none installed",
        )
    except Exception as exc:  # noqa: BLE001 - doctor reports everything
        report("GTK / GStreamer bindings", False, str(exc))

    try:
        import importlib

        import OpenGL

        importlib.import_module("OpenGL.GL")  # availability check: the GL bindings must load
        report("PyOpenGL", True, f"{OpenGL.__version__} (platform {os.environ.get('PYOPENGL_PLATFORM', 'auto')})")
    except Exception as exc:  # noqa: BLE001
        report("PyOpenGL", False, str(exc))

    report("display", bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")),
           os.environ.get("XDG_SESSION_TYPE", "unknown session"))

    path = catalog_path()
    if path.exists():
        from .catalog import Catalog

        catalog = Catalog(path)
        stats = catalog.stats()
        catalog.close()
        report("station catalog", stats.stations > 0,
               f"{stats.stations} stations, {stats.places_synced}/{stats.places} places synced ({path})",
               warn_only=True)
        report("search index complete", stats.search_rows == stats.stations,
               f"{stats.search_rows}/{stats.stations} stations searchable", warn_only=True)
    else:
        report("station catalog", False, f"not found at {path}; run 'frequenz sync'", warn_only=True)

    built = is_built(globe_dir())
    report("vector map for the globe (Natural Earth 1:10m)", built,
           str(globe_dir()) if built else "not built; run 'frequenz build-globe'", warn_only=True)
    return 1 if failures else 0
