"""Geometry tests: ellipsoid, camera, projection, picking, zoom levels, detail and daylight (no GTK)."""

import math
from datetime import datetime, timezone

import numpy as np

from frequenzradio import geo


def test_lonlat_to_xyz_known_points_on_the_ellipsoid():
    xyz = geo.lonlat_to_xyz([0.0, 90.0, 0.0], [0.0, 0.0, 0.0]).astype(float)
    assert np.allclose(xyz[0], [0, 0, 1], atol=1e-6)  # Greenwich on the equator is on +Z
    assert np.allclose(xyz[1], [1, 0, 0], atol=1e-6)  # east on +X
    pole = geo.lonlat_to_xyz([0.0], [90.0]).astype(float)[0]
    assert np.allclose(pole, [0, 1 - geo.WGS84_FLATTENING, 0], atol=1e-6)  # north pole sits at 1 - f on +Y


def test_points_lie_on_the_wgs84_ellipsoid():
    rng = np.random.default_rng(1)
    lng = rng.uniform(-180, 180, 500)
    lat = rng.uniform(-90, 90, 500)
    xyz = geo.lonlat_to_xyz(lng, lat).astype(float)
    value = xyz[:, 0] ** 2 + xyz[:, 2] ** 2 + (xyz[:, 1] / (1 - geo.WGS84_FLATTENING)) ** 2
    assert np.allclose(value, 1.0, atol=1e-6)


def test_surface_normal_is_perpendicular_to_the_surface():
    """The shaders use normalize(x, y * INV_POLE_SCALE_SQ, z); it must match the true surface normal."""
    rng = np.random.default_rng(2)
    h = 1e-2  # degrees; central differences in float32 need a coarse step
    for lng, lat in rng.uniform([-180, -80], [180, 80], size=(50, 2)):
        dlng = (geo.lonlat_to_xyz(lng + h, lat).astype(float) - geo.lonlat_to_xyz(lng - h, lat).astype(float))
        dlat = (geo.lonlat_to_xyz(lng, lat + h).astype(float) - geo.lonlat_to_xyz(lng, lat - h).astype(float))
        p = geo.lonlat_to_xyz(lng, lat).astype(float)
        normal = np.array([p[0], p[1] * geo.INV_POLE_SCALE_SQ, p[2]])
        normal /= np.linalg.norm(normal)
        assert abs(normal @ dlng) / np.linalg.norm(dlng) < 2e-3, (lng, lat)
        assert abs(normal @ dlat) / np.linalg.norm(dlat) < 2e-3, (lng, lat)


def test_camera_angles_bring_any_place_to_the_front():
    rng = np.random.default_rng(3)
    for lng, lat in rng.uniform([-180, -84], [180, 84], size=(200, 2)):
        yaw, pitch = geo.camera_angles_for(lng, lat)
        rotated = geo.model_matrix(yaw, pitch)[:3, :3] @ geo.lonlat_to_xyz(lng, lat).astype(float)
        assert abs(rotated[0]) < 1e-6 and abs(rotated[1]) < 1e-6 and rotated[2] > 0, (lng, lat, rotated)


def test_globe_mesh_is_on_the_ellipsoid_and_faces_outward():
    positions, indices = geo.globe_mesh(8, 16)
    assert positions.shape == (9 * 17, 3)
    triangles = indices.reshape(-1, 3)
    assert triangles.max() < positions.shape[0]
    a, b, c = (positions[triangles[:, k]].astype(float) for k in range(3))
    normal = np.cross(b - a, c - a)
    centre = a + b + c
    assert np.all(np.einsum("ij,ij->i", normal, centre) >= -1e-12)  # counter-clockwise seen from outside


def test_projection_centers_the_selected_place():
    width, height = 1000, 800
    lng, lat = 18.07, 59.33  # Stockholm
    model = geo.model_matrix(*geo.camera_angles_for(lng, lat))
    screen, visible = geo.project(geo.lonlat_to_xyz([lng], [lat]), model, geo.DEFAULT_DISTANCE, width, height)
    assert visible[0]
    assert np.allclose(screen[0], [width / 2, height / 2], atol=1e-3)


def test_picking_hits_front_points_and_ignores_the_far_side():
    width, height = 1000, 800
    lng, lat = 18.07, 59.33
    model = geo.model_matrix(*geo.camera_angles_for(lng, lat))
    points = geo.lonlat_to_xyz([lng, lng + 180.0], [lat, -lat])
    screen, visible = geo.project(points, model, geo.DEFAULT_DISTANCE, width, height)
    assert visible.tolist() == [True, False]
    hit = geo.pick_nearest(points, model, geo.DEFAULT_DISTANCE, width, height,
                           screen[0][0] + 2, screen[0][1] - 3)
    assert hit == 0
    miss = geo.pick_nearest(points, model, geo.DEFAULT_DISTANCE, width, height, 5, 5)
    assert miss is None


def test_picking_prefers_bigger_place_inside_a_cluster():
    width, height = 1000, 800
    lng, lat = 10.0, 50.0
    model = geo.model_matrix(*geo.camera_angles_for(lng, lat))
    points = geo.lonlat_to_xyz([lng, lng + 0.01], [lat, lat + 0.01])
    screen, _ = geo.project(points, model, geo.DEFAULT_DISTANCE, width, height)
    x, y = screen[0]
    weights = np.array([1.0, 40.0])
    assert geo.pick_nearest(points, model, geo.DEFAULT_DISTANCE, width, height, x, y, weights=weights) == 1


def test_perspective_matrix_maps_the_near_plane():
    proj = geo.perspective(60.0, 1.0, 0.1, 10.0)
    near_point = np.array([0.0, 0.0, -0.1, 1.0])
    clip = proj @ near_point
    assert math.isclose(clip[2] / clip[3], -1.0, abs_tol=1e-9)


def test_zoom_levels_are_ordered_and_add_three_close_levels():
    distances = [level.distance for level in geo.ZOOM_LEVELS]
    assert distances == sorted(distances, reverse=True)
    assert [level.name for level in geo.ZOOM_LEVELS[-3:]] == ["Region", "Country", "City"]
    assert math.isclose(geo.altitude_km(geo.MIN_DISTANCE), 100.0, rel_tol=1e-9)
    assert math.isclose(geo.altitude_km(geo.ZOOM_LEVELS[3].distance), 2000.0, rel_tol=1e-9)
    assert math.isclose(geo.altitude_km(geo.ZOOM_LEVELS[4].distance), 500.0, rel_tol=1e-9)
    assert geo.MIN_DISTANCE < 2.0  # the new close levels lie beyond the old closest zoom


def test_zoom_steps_move_one_level_and_stop_at_the_ends():
    assert math.isclose(geo.next_zoom_distance(geo.DEFAULT_DISTANCE, +1), 2.0)
    assert math.isclose(geo.next_zoom_distance(geo.DEFAULT_DISTANCE, -1), 6.0)
    assert math.isclose(geo.next_zoom_distance(geo.MIN_DISTANCE, +1), geo.MIN_DISTANCE)
    assert math.isclose(geo.next_zoom_distance(geo.MAX_DISTANCE, -1), geo.MAX_DISTANCE)
    # A continuous (scroll) position steps to the next level in the requested direction.
    assert math.isclose(geo.next_zoom_distance(2.5, +1), 2.0)
    assert math.isclose(geo.next_zoom_distance(2.5, -1), 3.5)


def test_zoom_level_names_and_clamping():
    assert geo.zoom_level_name(geo.MIN_DISTANCE) == "City"
    assert geo.zoom_level_name(2.5) is None
    assert geo.clamp_distance(100.0) == geo.MAX_DISTANCE
    assert geo.clamp_distance(0.5) == geo.MIN_DISTANCE


def test_level_of_detail_switches_at_the_close_levels():
    assert geo.level_of_detail(geo.DEFAULT_DISTANCE) == 0
    assert geo.level_of_detail(2.0) == 1
    assert geo.level_of_detail(geo.ZOOM_LEVELS[3].distance) == 2
    assert geo.level_of_detail(geo.MIN_DISTANCE) == 2


def test_clip_planes_keep_the_visible_hemisphere_inside_the_frustum():
    for distance in (geo.MAX_DISTANCE, geo.DEFAULT_DISTANCE, 1.2, geo.MIN_DISTANCE):
        near, far = geo.clip_planes(distance)
        assert 0 < near < distance - 1.0  # the surface directly below the camera is in front of the near plane
        assert far > distance + 1.0  # the far side of the globe is inside the far plane


def test_subsolar_point_matches_the_sun_at_known_times():
    # Equinox, 12:00 UTC: the apparent noon is about 7.5 minutes later at Greenwich, so the sun is near +2 degrees.
    lng, lat = geo.subsolar_point(datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc))
    assert abs(lng - 1.9) < 0.5 and abs(lat) < 0.5
    # 2 November 2026, 12:00 UTC: about -4 degrees longitude and -15 degrees latitude.
    lng, lat = geo.subsolar_point(datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
    assert abs(lng - (-4.1)) < 0.5 and abs(lat - (-15.0)) < 0.5
    # Midnight UTC puts the sun near the antimeridian; the equation of time moves it by up to ~2 degrees.
    lng, _ = geo.subsolar_point(datetime(2026, 3, 20, 0, 0, tzinfo=timezone.utc))
    assert min(abs(lng - 180.0), abs(lng + 180.0)) < 2.5


def test_sun_direction_is_a_unit_vector_on_the_subsolar_point():
    when = datetime(2026, 11, 2, 9, 30, tzinfo=timezone.utc)
    direction = geo.sun_direction(when)
    assert math.isclose(float(np.linalg.norm(direction)), 1.0, abs_tol=1e-9)
    lng, lat = geo.subsolar_point(when)
    expected = geo.lonlat_to_xyz(lng, lat).astype(float)
    assert np.allclose(direction, expected / np.linalg.norm(expected), atol=1e-6)
