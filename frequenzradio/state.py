"""Small UI state persisted between runs (never contains catalog data)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

from .paths import state_path
from .globe_palette import DEFAULT_PALETTE, normalize as normalize_palette
from .theme import DEFAULT_THEME, normalize

log = logging.getLogger("frequenzradio.state")


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
        path = state_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError, AttributeError):
            return cls()
        state.theme = normalize(state.theme)
        state.globe_palette = normalize_palette(state.globe_palette)
        return state

    def save(self) -> None:
        try:
            state_path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("could not save state: %s", exc)
