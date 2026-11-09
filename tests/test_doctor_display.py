"""Display check in 'frequenz doctor': environment variables on Linux, GTK on macOS."""

from frequenzradio import doctor


def test_macos_display_is_asked_from_gtk_not_the_environment(monkeypatch):
    monkeypatch.setattr(doctor, "is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_gtk_display_opens", lambda: True)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    assert doctor._display_status() == (True, "macOS window server")


def test_macos_without_window_server_fails(monkeypatch):
    monkeypatch.setattr(doctor, "is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_gtk_display_opens", lambda: False)
    assert doctor._display_status() == (False, "no window server")


def test_gtk_error_is_reported_not_raised(monkeypatch):
    def broken() -> bool:
        raise RuntimeError("no GTK")

    monkeypatch.setattr(doctor, "is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_gtk_display_opens", broken)
    assert doctor._display_status() == (False, "no GTK")


def test_linux_display_still_comes_from_the_environment(monkeypatch):
    monkeypatch.setattr(doctor, "is_macos", lambda: False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert doctor._display_status() == (True, "wayland")
