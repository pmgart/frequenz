"""Register the fonts that travel inside the Mac app bundle with CoreText.

GTK on macOS asks CoreText for font families, so a font that only sits in the
bundle is invisible until it is registered. Registering for the process keeps the
user's font folder untouched.
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path

log = logging.getLogger("frequenzradio.fonts")

_COREFOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
_CORETEXT = "/System/Library/Frameworks/CoreText.framework/CoreText"
_SCOPE_PROCESS = 1
FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}


def register_fonts(folder: Path) -> int:
    """Register every font file in *folder* for this process; return how many worked."""
    try:
        core_foundation = ctypes.CDLL(_COREFOUNDATION)
        core_text = ctypes.CDLL(_CORETEXT)
    except OSError as exc:
        log.warning("CoreText is unavailable: %s", exc)
        return 0

    core_foundation.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
    core_foundation.CFURLCreateFromFileSystemRepresentation.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool,
    ]
    core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
    core_text.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
    core_text.CTFontManagerRegisterFontsForURL.argtypes = [
        ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p,
    ]

    registered = 0
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in FONT_SUFFIXES:
            continue
        raw = str(path).encode()
        url = core_foundation.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
        if not url:
            continue
        try:
            if core_text.CTFontManagerRegisterFontsForURL(url, _SCOPE_PROCESS, None):
                registered += 1
            else:
                log.warning("could not register the bundled font %s", path.name)
        finally:
            core_foundation.CFRelease(url)
    return registered


def register_bundled_fonts() -> None:
    """Register the app bundle's fonts; a no-op outside the bundle."""
    bundle = os.environ.get("FREQUENZ_BUNDLE_RESOURCES")
    if not bundle:
        return
    folder = Path(bundle) / "fonts"
    if not folder.is_dir():
        return
    if not register_fonts(folder):
        log.warning("no bundled font was registered; the system font is used")
