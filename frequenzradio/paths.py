"""Filesystem locations: XDG base directories on Linux, Application Support on macOS."""

from __future__ import annotations

import os
from pathlib import Path

from .osinfo import is_macos

APP_ID = "se.laps.Frequenz"
APP_NAME = "FREQUENZ"


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        root = Path(base)
    elif is_macos():
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path.home() / ".local" / "share"
    path = root / "frequenz"
    path.mkdir(parents=True, exist_ok=True)
    return path


def catalog_path() -> Path:
    override = os.environ.get("FREQUENZ_CATALOG")
    return Path(override).expanduser() if override else data_dir() / "catalog.sqlite"


def state_path() -> Path:
    return data_dir() / "state.json"


def naturalearth_dir() -> Path:
    """Downloaded Natural Earth GeoJSON (raw source data for the globe)."""
    path = data_dir() / "naturalearth"
    path.mkdir(parents=True, exist_ok=True)
    return path


def globe_dir() -> Path:
    """Triangulated vector map arrays used by the globe viewer."""
    path = data_dir() / "globe"
    path.mkdir(parents=True, exist_ok=True)
    return path


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def asset(name: str) -> Path:
    return package_dir() / "data" / name
