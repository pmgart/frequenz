import sys

from frequenzradio.osinfo import desktop_gl_version, is_macos, primary_label, quit_accels


def test_linux_keeps_the_gles_compatible_request_and_ctrl():
    assert not is_macos("linux")
    assert desktop_gl_version("linux") == (3, 0)
    assert primary_label("linux") == "Ctrl"


def test_macos_requests_4_1_core_and_the_command_key():
    assert is_macos("darwin")
    assert desktop_gl_version("darwin") == (4, 1)
    assert primary_label("darwin") == "⌘"


def test_default_platform_is_the_running_one():
    assert is_macos() == (sys.platform == "darwin")


def test_quit_accelerators():
    assert quit_accels("linux") == ["<Primary>q"]
    assert quit_accels("darwin") == ["<Meta>q", "<Control>q"]
