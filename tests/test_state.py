"""AppState keeps the theme between runs, and older state files still load."""

import json

from frequenzradio.state import AppState


def _use_scratch_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path / "frequenz" / "state.json"


def test_defaults_to_the_dark_theme(tmp_path, monkeypatch):
    _use_scratch_data_dir(tmp_path, monkeypatch)
    assert AppState.load().theme == "dark"


def test_theme_round_trips_with_other_fields(tmp_path, monkeypatch):
    _use_scratch_data_dir(tmp_path, monkeypatch)
    AppState(theme="light", volume=0.3, last_station="abc").save()
    loaded = AppState.load()
    assert loaded.theme == "light"
    assert loaded.volume == 0.3
    assert loaded.last_station == "abc"


def test_unknown_theme_in_the_file_falls_back_to_dark(tmp_path, monkeypatch):
    path = _use_scratch_data_dir(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"theme": "purple", "volume": 0.5}), encoding="utf-8")
    loaded = AppState.load()
    assert loaded.theme == "dark"
    assert loaded.volume == 0.5


def test_state_written_before_the_theme_field_still_loads(tmp_path, monkeypatch):
    path = _use_scratch_data_dir(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"volume": 0.4, "yaw": 1.5, "last_station": "xyz"}), encoding="utf-8")
    loaded = AppState.load()
    assert loaded.theme == "dark"
    assert loaded.volume == 0.4
    assert loaded.yaw == 1.5
    assert loaded.last_station == "xyz"


def test_corrupt_file_gives_defaults(tmp_path, monkeypatch):
    path = _use_scratch_data_dir(tmp_path, monkeypatch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")
    assert AppState.load() == AppState()
