"""Checks of the built vector map against known geography (skipped until 'frequenz build-globe' ran)."""

import json

import numpy as np
import pytest

from frequenzradio import geodata
from frequenzradio.paths import globe_dir

BUILT = geodata.is_built(globe_dir())
needs_build = pytest.mark.skipif(not BUILT, reason="run 'frequenz build-globe' first")


def test_detail_levels_and_line_levels_are_consistent():
    assert [detail.lod for detail in geodata.DETAIL] == [0, 1, 2]
    assert set(geodata.LINE_LODS) == {s.layer for s in geodata.SOURCES if s.kind == "line"}
    assert set(geodata.SURFACE_LAYERS) == {s.layer for s in geodata.SOURCES if s.kind == "surface"}


def test_load_layer_returns_none_for_missing_levels(tmp_path):
    np.savez(tmp_path / "land-lod0.npz", vertices=np.zeros((3, 3), np.float32), indices=np.zeros((1, 3), np.uint32))
    arrays = geodata.load_layer(tmp_path, "land", 0)
    assert arrays is not None
    assert set(arrays) == {"vertices", "indices"} and arrays["indices"].shape == (1, 3)
    assert geodata.load_layer(tmp_path, "land", 2) is None
    assert not geodata.is_built(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"schema": geodata.SCHEMA}), encoding="utf-8")
    assert geodata.is_built(tmp_path)


def test_surface_contains_hits_a_single_triangle():
    # A triangle on the globe around Greenwich/equator, and a point well outside it.
    vertices = geodata.geo.lonlat_to_xyz([-1.0, 1.0, 0.0], [-1.0, -1.0, 1.0])
    indices = np.array([[0, 1, 2]], dtype=np.uint32)
    assert geodata.surface_contains(vertices, indices, 0.0, -0.1)
    assert not geodata.surface_contains(vertices, indices, 90.0, 0.0)


@needs_build
@pytest.mark.parametrize("name,lng,lat", [
    ("Stockholm", 18.07, 59.33),
    ("Nairobi", 36.82, -1.29),
    ("Sydney", 151.21, -33.87),
    ("Buenos Aires", -58.38, -34.60),
    ("Beijing", 116.40, 39.90),
    ("Cairo", 31.24, 30.04),
    ("Lake Victoria shore", 33.2, -1.0),
])
def test_built_land_covers_known_places(name, lng, lat):
    arrays = geodata.load_layer(globe_dir(), "land", 2)
    assert arrays is not None
    covered = geodata.surface_contains(arrays["vertices"], arrays["indices"], lng, lat)
    if name == "Lake Victoria shore":
        lakes = geodata.load_layer(globe_dir(), "lakes", 2)
        assert lakes is not None
        # The shore sits in land or in the lake layer; the lake layer must cover the lake itself.
        assert covered or geodata.surface_contains(lakes["vertices"], lakes["indices"], 33.0, -1.0)
    else:
        assert covered, f"{name} should be on land"


@needs_build
@pytest.mark.parametrize("name,lng,lat", [
    ("mid Atlantic", -30.0, 0.0),
    ("South Pacific", -150.0, -30.0),
    ("Indian Ocean", 80.0, -20.0),
])
def test_built_land_leaves_open_ocean_empty(name, lng, lat):
    arrays = geodata.load_layer(globe_dir(), "land", 2)
    assert arrays is not None
    assert not geodata.surface_contains(arrays["vertices"], arrays["indices"], lng, lat), f"{name} must be water"


@needs_build
def test_built_layers_match_the_map_definition_and_have_no_depth_bands():
    manifest = json.loads((globe_dir() / "manifest.json").read_text(encoding="utf-8"))
    built = {name.rsplit("-lod", 1)[0] for name in manifest["layers"]}
    assert built == {s.layer for s in geodata.SOURCES}
    assert not any(name.startswith("deep") for name in built)
    assert not list(globe_dir().glob("deep*-lod*.npz"))  # stale files from earlier builds are removed


@needs_build
def test_manifest_records_sources_and_the_licence():
    manifest = json.loads((globe_dir() / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == geodata.SCHEMA
    assert "public domain" in manifest["licence"]
    assert set(manifest["sources"]) == {s.file for s in geodata.SOURCES}
    assert all(len(entry["sha256"]) == 64 for entry in manifest["sources"].values())


@pytest.mark.parametrize("layer", ["land", "lakes", "ice"])
def test_source_outlines_have_no_artifact_straight_runs(layer):
    """Guard against straight-line artifacts such as the depth bands had (up to about 90 degrees long)."""
    shapely = pytest.importorskip("shapely")
    from frequenzradio import globe_build
    from frequenzradio.paths import naturalearth_dir

    source = next(s for s in geodata.SOURCES if s.layer == layer)
    path = naturalearth_dir() / f"{source.file}.geojson"
    if not path.exists():
        pytest.skip("run 'frequenz build-globe' to download the Natural Earth files")
    polygons = globe_build._split_all(globe_build._polygons(globe_build._load_geometries(path)))
    union = shapely.union_all(np.array(polygons, dtype=object))
    assert globe_build.outline_straight_runs(union, min_len=10.0) == []
