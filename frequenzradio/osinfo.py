"""The few places where Linux and macOS differ: OpenGL version, the modifier key and platform checks."""

from __future__ import annotations

import sys


def is_macos(platform: str | None = None) -> bool:
    return (platform or sys.platform) == "darwin"


def desktop_gl_version(platform: str | None = None) -> tuple[int, int]:
    """OpenGL version to request on the desktop path. GTK's default is 3.2 core, which cannot compile
    the GLSL 330 shaders. The first Mac run with a 3.3 request showed "no usable OpenGL context", so
    macOS asks for 4.1 core, the newest profile it offers; the 330 shaders run in it. On Linux the
    request stays 3.0, which is valid for GLES 3.0 as well."""
    return (4, 1) if is_macos(platform) else (3, 0)


def primary_label(platform: str | None = None) -> str:
    """Name of the main modifier key, as shown in the shortcut text."""
    return "⌘" if is_macos(platform) else "Ctrl"


def quit_accels(platform: str | None = None) -> list[str]:
    """Accelerators for quitting. On macOS: Command-Q, and Control-Q as well."""
    return ["<Meta>q", "<Control>q"] if is_macos(platform) else ["<Primary>q"]
