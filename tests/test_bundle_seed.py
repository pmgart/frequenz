"""First launch in the Mac app bundle copies the pre-built globe map into the data folder, once."""

import json

from frequenzradio import app as app_module
from frequenzradio import paths


def _write_map(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps({"layers": []}), encoding="utf-8")
    (folder / "land-lod0.npz").write_bytes(b"bundled")


def test_bundled_map_is_copied_into_the_data_folder(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle" / "Resources"
    _write_map(bundle / "globe")
    monkeypatch.setenv("FREQUENZ_BUNDLE_RESOURCES", str(bundle))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app_module.seed_bundled_globe()
    assert (paths.globe_dir() / "manifest.json").is_file()
    assert (paths.globe_dir() / "land-lod0.npz").read_bytes() == b"bundled"


def test_without_a_bundle_nothing_is_copied(monkeypatch, tmp_path):
    monkeypatch.delenv("FREQUENZ_BUNDLE_RESOURCES", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    app_module.seed_bundled_globe()
    assert not (paths.globe_dir() / "manifest.json").exists()


def test_an_existing_map_is_kept(monkeypatch, tmp_path):
    bundle = tmp_path / "bundle" / "Resources"
    _write_map(bundle / "globe")
    monkeypatch.setenv("FREQUENZ_BUNDLE_RESOURCES", str(bundle))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    _write_map(paths.globe_dir())
    (paths.globe_dir() / "land-lod0.npz").write_bytes(b"user copy")
    app_module.seed_bundled_globe()
    assert (paths.globe_dir() / "land-lod0.npz").read_bytes() == b"user copy"
