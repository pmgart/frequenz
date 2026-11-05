"""Filesystem locations (XDG base directories)."""

from __future__ import annotations

import os
from pathlib import Path

APP_ID = "se.laps.Frequenz"
APP_NAME = "FREQUENZ"


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / "frequenz"
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
