"""The CLI contract: exit codes, argument validation and the build-globe hint."""

import sys

import pytest

from frequenzradio import __version__
from frequenzradio.cli import main


def test_version_prints_the_package_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


@pytest.mark.parametrize("argv", [
    ["sync", "--workers", "0"],
    ["sync", "--workers", "999"],
    ["sync", "--limit", "0"],
    ["sync", "--min-interval", "-1"],
    ["search", "jazz", "--limit", "0"],
    ["build-globe", "--workers", "0"],
])
def test_out_of_range_options_are_rejected(argv):
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2


def test_build_globe_explains_the_missing_dependency(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "frequenzradio.globe_build", None)
    assert main(["build-globe"]) == 1
    err = capsys.readouterr().err
    assert "frequenzradio[build]" in err
    assert "python3-shapely" in err


def test_stats_on_a_fresh_catalog_succeeds(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("FREQUENZ_CATALOG", str(tmp_path / "catalog.sqlite"))
    assert main(["stats"]) == 0
    assert "stations:" in capsys.readouterr().out


def test_a_directory_as_catalog_path_is_reported_without_a_traceback(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("FREQUENZ_CATALOG", str(tmp_path))  # a directory, not a file
    assert main(["stats"]) == 1
    assert "FREQUENZ_CATALOG" in capsys.readouterr().err
