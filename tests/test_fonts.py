"""The bundled-font helper must be inert outside the app bundle."""

from __future__ import annotations

from pathlib import Path

from frequenzradio import fonts


def test_no_bundle_variable_is_a_noop(monkeypatch):
    monkeypatch.delenv("FREQUENZ_BUNDLE_RESOURCES", raising=False)
    fonts.register_bundled_fonts()  # must not touch CoreText or raise


def test_missing_font_folder_is_a_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("FREQUENZ_BUNDLE_RESOURCES", str(tmp_path))
    fonts.register_bundled_fonts()  # no fonts/ folder in the bundle


def test_register_fonts_skips_non_font_files(tmp_path):
    (tmp_path / "notes.txt").write_text("not a font")
    assert fonts.register_fonts(tmp_path) == 0


def test_register_fonts_accepts_an_empty_folder(tmp_path):
    assert fonts.register_fonts(Path(tmp_path)) == 0
