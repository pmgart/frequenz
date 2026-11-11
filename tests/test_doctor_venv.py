"""The venv checks in ``frequenz doctor``: they catch a virtualenv orphaned by a Python upgrade."""

from pathlib import Path

from frequenzradio.doctor import _declared_venv_version, _version_series


def test_version_series_keeps_major_and_minor():
    assert _version_series("3.15.2") == "3.15"
    assert _version_series("3.15") == "3.15"


def test_a_patch_upgrade_is_not_a_mismatch():
    assert _version_series("3.14.8") == _version_series("3.14.9")


def test_a_minor_upgrade_is_a_mismatch():
    # Fedora 45 moved 3.14 -> 3.15, which orphans lib/python3.14/site-packages.
    assert _version_series("3.14.8") != _version_series("3.15.2")


def test_declared_version_reads_pyvenv_cfg(tmp_path: Path):
    cfg = tmp_path / "pyvenv.cfg"
    cfg.write_text(
        "home = /usr/bin\n"
        "include-system-site-packages = true\n"
        "version = 3.14.8\n"
        "executable = /usr/bin/python3.14\n",
        encoding="utf-8",
    )
    assert _declared_venv_version(cfg) == "3.14.8"


def test_declared_version_is_empty_when_the_file_is_missing(tmp_path: Path):
    assert _declared_venv_version(tmp_path / "pyvenv.cfg") == ""


def test_declared_version_is_empty_without_a_version_key(tmp_path: Path):
    cfg = tmp_path / "pyvenv.cfg"
    cfg.write_text("home = /usr/bin\n", encoding="utf-8")
    assert _declared_venv_version(cfg) == ""
