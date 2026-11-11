"""One version, one data directory: release metadata must not drift."""

import re
import tomllib
from pathlib import Path

from frequenzradio import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_spec_and_changelog_agree_on_the_version():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == __version__

    spec = (ROOT / "packaging/fedora/frequenz.spec").read_text(encoding="utf-8")
    assert re.search(rf"^Version:\s+{re.escape(__version__)}$", spec, re.MULTILINE)

    first = (ROOT / "packaging/debian/changelog").read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith(f"frequenz ({__version__}-")


def test_readme_documents_the_real_data_directory():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "~/.local/share/frequenzradio" not in readme
    assert "~/.local/share/frequenz/" in readme
