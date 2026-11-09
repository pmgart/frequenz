"""Data folder on macOS: Application Support, unless XDG_DATA_HOME is set."""

from frequenzradio import paths


def test_macos_default_is_application_support(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(paths, "is_macos", lambda: True)
    assert paths.data_dir() == tmp_path / "Library" / "Application Support" / "frequenz"


def test_xdg_override_wins_on_macos(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(paths, "is_macos", lambda: True)
    assert paths.data_dir() == tmp_path / "xdg" / "frequenz"


def test_linux_default_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(paths, "is_macos", lambda: False)
    assert paths.data_dir() == tmp_path / ".local" / "share" / "frequenz"
