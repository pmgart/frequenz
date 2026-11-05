"""Build tests on synthetic polygons (needs shapely: the 'build' extra; skipped without it)."""

import math

import numpy as np
import pytest

shapely = pytest.importorskip("shapely")
from shapely.geometry import LineString, MultiLineString, Point, Polygon  # noqa: E402

from frequenzradio import geo  # noqa: E402
from frequenzradio import globe_build  # noqa: E402
from frequenzradio.geodata import DETAIL, Detail  # noqa: E402


def test_triangulation_covers_polygons_exactly_including_holes():
    outer = Polygon([(0, 0), (3, 0), (3, 2), (0, 2)], [[(1, 0.5), (2, 0.5), (2, 1.5), (1, 1.5)]])
    tris, covered, expected = globe_build._triangulate([outer], cell_deg=1.0)
    assert math.isclose(expected, outer.area, rel_tol=1e-12)
    assert math.isclose(covered, expected, rel_tol=1e-12)
    assert tris.shape[1:] == (3, 2)


def test_split_antimeridian_keeps_the_area_and_stays_inside_180():
    wrapped = Polygon([(170, 0), (-170, 0), (-170, 10), (170, 10)])  # the ring jumps from 170 to -170
    pieces = globe_build._split_antimeridian(wrapped)
    assert len(pieces) == 2
    assert math.isclose(sum(p.area for p in pieces), 20 * 10, rel_tol=1e-12)
    for piece in pieces:
        xmin, _, xmax, _ = piece.bounds
        assert xmin >= -180.0 and xmax <= 180.0


def test_surface_mesh_is_counter_clockwise_from_outside_and_on_the_ellipsoid():
    square = Polygon([(10, 50), (20, 50), (20, 60), (10, 60)])
    detail = Detail(1, simplify_deg=0.0, cell_deg=1.0, densify_deg=0.2)
    tris, covered, expected = globe_build._triangulate(globe_build._prepare([square], detail), detail.cell_deg)
    assert math.isclose(expected, 100.0, rel_tol=1e-12)
    assert math.isclose(covered, expected, rel_tol=1e-12)
    vertices, indices = globe_build._triangles_to_mesh(tris)
    assert indices.dtype == np.uint32 and indices.max() < len(vertices)
    a, b, c = (vertices[indices[:, k]].astype(float) for k in range(3))
    normal = np.cross(b - a, c - a)
    centre = a + b + c
    assert np.all(np.einsum("ij,ij->i", normal, centre) > 0)  # outward and counter-clockwise
    value = vertices[:, 0] ** 2 + vertices[:, 2] ** 2 + (vertices[:, 1] / (1 - geo.WGS84_FLATTENING)) ** 2
    assert np.allclose(value, 1.0, atol=1e-6)


def test_triangulation_of_a_large_polygon_uses_cells_and_still_covers_it():
    # A cap of the globe with an interior hole: many cells, one exact cover.
    big = Polygon([(-120, -40), (120, -40), (120, 40), (-120, 40)], [[(-30, -10), (30, -10), (30, 10), (-30, 10)]])
    expected_area = big.area
    tris, covered, expected = globe_build._triangulate(globe_build._prepare([big], DETAIL[2]), DETAIL[2].cell_deg)
    assert math.isclose(expected, expected_area, rel_tol=1e-9)
    assert math.isclose(covered, expected, rel_tol=1e-9)


def test_line_segments_join_only_points_of_the_same_line():
    lines = [MultiLineString([[(0, 0), (1, 0), (1, 1)], [(5, 5), (6, 5)]]), LineString([(-10, -10), (-9, -10)])]
    segments = globe_build._line_segments(lines, Detail(2, 0.0, 1.0, 10.0))
    assert segments.shape == (4, 2, 3)  # two segments in the first line, one in the second, one in the third
    assert np.allclose(np.linalg.norm(segments[:, 0, :].astype(float) * [1, 1, 1], axis=1) > 0.9, True)


def test_fixed_polygons_outside_the_build_repair_invalid_input():
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])  # self-intersecting
    repaired = globe_build._polygons([bowtie])
    assert repaired and all(p.is_valid for p in repaired)
    assert math.isclose(sum(p.area for p in repaired), 2.0, rel_tol=1e-9)


def test_outline_check_flags_a_long_straight_edge_and_ignores_curves_and_map_edges():
    # A 30-degree straight top and bottom edge: both are artifacts; the 1-degree sides are too short to count.
    rectangle = Polygon([(0, 0), (30, 0), (30, 1), (0, 1)])
    runs = globe_build.outline_straight_runs(rectangle, min_len=10.0)
    assert sorted(round(length) for length, _, _ in runs) == [30, 30]
    # A round coastline bends at every edge: nothing to report.
    circle = Point(10, 50).buffer(5.0, quad_segs=16)
    assert globe_build.outline_straight_runs(circle, min_len=10.0) == []


def test_outline_check_skips_the_dateline_but_reports_a_straight_side_elsewhere():
    # 30 degrees long on the antimeridian (a map edge, not reported) and a 20-degree straight side at 170 E.
    polygon = Polygon([(180, 0), (180, 30), (175, 30), (170, 25), (170, 5), (175, 0)])
    runs = globe_build.outline_straight_runs(polygon, min_len=10.0)
    assert len(runs) == 1
    length, start, end = runs[0]
    assert math.isclose(length, 20.0, rel_tol=1e-9)
    assert start == (170.0, 25.0) and end == (170.0, 5.0)
