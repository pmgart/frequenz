"""The few places where Linux and macOS differ: OpenGL version, the modifier key and platform checks."""

from __future__ import annotations

import sys


def is_macos(platform: str | None = None) -> bool:
    return (platform or sys.platform) == "darwin"


def desktop_gl_version(platform: str | None = None) -> tuple[int, int]:
    """OpenGL version to request on the desktop path.

    macOS: 3.2 core, the profile GTK's docs name as its default. The first Mac runs showed a fixed
    "no usable OpenGL context" note with a 3.3 request, and macOS's "invalid share context" with a 4.1
    request, so the globe uses GLSL 150 shaders there. Linux: 3.0, which is also valid for GLES 3.0.
    """
    return (3, 2) if is_macos(platform) else (3, 0)


def primary_label(platform: str | None = None) -> str:
    """Name of the main modifier key, as shown in the shortcut text."""
    return "⌘" if is_macos(platform) else "Ctrl"


def quit_accels(platform: str | None = None) -> list[str]:
    """Accelerators for quitting. On macOS: Command-Q, and Control-Q as well."""
    return ["<Meta>q", "<Control>q"] if is_macos(platform) else ["<Primary>q"]
