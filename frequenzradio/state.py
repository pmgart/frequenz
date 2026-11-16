"""Small UI state persisted between runs (never contains catalog data)."""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field

from .paths import state_path
from .globe_palette import DEFAULT_PALETTE, normalize as normalize_palette
from .theme import DEFAULT_THEME, normalize

log = logging.getLogger("frequenzradio.state")


def _finite_float(value, default: float, minimum: float | None = None,
                  maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    if minimum is not None:
        number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


@dataclass
class AppState:
    last_station: str | None = None
    volume: float = 0.8
    yaw: float = 0.0
    pitch: float = 0.35
    dist: float = 3.5
    auto_rotate: bool = True
    theme: str = DEFAULT_THEME
    globe_palette: str = DEFAULT_PALETTE
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "AppState":
        try:
            path = state_path()
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("state.json is not a JSON object")
            kwargs = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            state = cls(**kwargs)
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()
        state.last_station = state.last_station if isinstance(state.last_station, str) else None
        state.volume = _finite_float(state.volume, 0.8, 0.0, 1.0)
        state.yaw = _finite_float(state.yaw, 0.0)
        state.pitch = _finite_float(state.pitch, 0.35, -1.5, 1.5)
        state.dist = _finite_float(state.dist, 3.5, 0.05, 100.0)
        if not isinstance(state.auto_rotate, bool):
            state.auto_rotate = True
        if not isinstance(state.extra, dict):
            state.extra = {}
        state.theme = normalize(state.theme) if isinstance(state.theme, str) else DEFAULT_THEME
        state.globe_palette = (
            normalize_palette(state.globe_palette)
            if isinstance(state.globe_palette, str)
            else DEFAULT_PALETTE
        )
        return state

    def save(self) -> None:
        tmp = None
        try:
            path = state_path()
            tmp = path.with_suffix(".json.tmp")
            text = json.dumps(asdict(self), indent=2, allow_nan=False)
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except (OSError, ValueError, TypeError) as exc:
            log.warning("could not save state: %s", exc)
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass
