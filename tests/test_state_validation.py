"""state.json must survive hand edits, wrong types and interrupted writes."""

import json

from frequenzradio.state import AppState
from frequenzradio.theme import DEFAULT_THEME


def _state_file(tmp_path, payload):
    path = tmp_path / "frequenz" / "state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_wrong_types_fall_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _state_file(tmp_path, {
        "volume": "loud", "dist": None, "pitch": "up", "auto_rotate": "yes", "theme": 7,
    })
    state = AppState.load()
    assert state.volume == 0.8
    assert state.dist == 3.5
    assert state.pitch == 0.35
    assert state.auto_rotate is True
    assert state.theme == DEFAULT_THEME


def test_nan_and_out_of_range_values_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    _state_file(tmp_path, {"volume": float("nan"), "dist": -4.0, "pitch": 99.0})
    state = AppState.load()
    assert state.volume == 0.8
    assert state.dist == 0.05  # clamped into the sane range
    assert state.pitch == 1.5


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    state = AppState(volume=0.42, last_station="abc")
    state.save()
    path = tmp_path / "frequenz" / "state.json"
    assert json.loads(path.read_text(encoding="utf-8"))["volume"] == 0.42
    assert list(path.parent.glob("*.tmp")) == []
