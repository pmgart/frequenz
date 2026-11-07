"""Geometry for the globe: Earth shape, coordinates, camera, projection, picking, zoom and daylight.

Conventions (right-handed, Y up):
* Earth is the WGS84 ellipsoid scaled so its equatorial radius is 1 (see ``lonlat_to_xyz``).
  East is +X, the north pole is +Y at height ``1 - flattening``, Greenwich is +Z.
* The globe is rotated by ``model = rot_x(pitch) @ rot_y(yaw)``. The camera sits on +Z at
  distance ``dist`` and looks at the origin. Distances are in equatorial radii.
* A point is visible when the ellipsoid normal there faces the camera.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

FOVY_DEG = 35.0
DEFAULT_DISTANCE = 3.5
MAX_PITCH = math.radians(85.0)

# WGS84 ellipsoid. Natural Earth and place coordinates are geodetic latitudes on this ellipsoid.
WGS84_FLATTENING = 1.0 / 298.257223563
WGS84_E2 = 2.0 * WGS84_FLATTENING - WGS84_FLATTENING**2
EARTH_RADIUS_KM = 6378.137
# Surface normal of the ellipsoid in scaled coordinates: normalize(x, y * INV_POLE_SCALE_SQ, z).
INV_POLE_SCALE_SQ = 1.0 / (1.0 - WGS84_FLATTENING) ** 2


def lonlat_to_xyz(lng_deg, lat_deg) -> np.ndarray:
    """Geodetic longitude and latitude in degrees to the scaled ellipsoid (equatorial radius 1)."""
    lng = np.radians(np.asarray(lng_deg, dtype=np.float64))
    lat = np.radians(np.asarray(lat_deg, dtype=np.float64))
    sin_lat, cos_lat = np.sin(lat), np.cos(lat)
    w = np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = cos_lat * np.sin(lng) / w
    y = (1.0 - WGS84_E2) * sin_lat / w
    z = cos_lat * np.cos(lng) / w
    return np.stack([x, y, z], axis=-1).astype(np.float32)


# -- zoom levels ---------------------------------------------------------------------------------
def distance_for_altitude_km(altitude_km: float) -> float:
    return 1.0 + altitude_km / EARTH_RADIUS_KM


def altitude_km(distance: float) -> float:
    """Height of the camera above the equatorial surface, in kilometres."""
    return (distance - 1.0) * EARTH_RADIUS_KM


@dataclass(frozen=True)
class ZoomLevel:
    name: str
    distance: float


# From far to close. The first three are the original zoom range; the last three are the
# close-in levels: 2,000 km (region), 500 km (country) and 100 km (city) above the surface.
ZOOM_LEVELS = (
    ZoomLevel("Far", 6.0),
    ZoomLevel("Globe", DEFAULT_DISTANCE),
    ZoomLevel("Close globe", 2.0),
    ZoomLevel("Region", distance_for_altitude_km(2000.0)),
    ZoomLevel("Country", distance_for_altitude_km(500.0)),
    ZoomLevel("City", distance_for_altitude_km(100.0)),
)
MAX_DISTANCE = ZOOM_LEVELS[0].distance
MIN_DISTANCE = ZOOM_LEVELS[-1].distance


def clamp_distance(distance: float) -> float:
    return min(MAX_DISTANCE, max(MIN_DISTANCE, distance))


def next_zoom_distance(distance: float, direction: int) -> float:
    """Distance of the next level closer (direction > 0) or farther (direction < 0)."""
    eps = 1e-6
    if direction > 0:
        closer = [level.distance for level in ZOOM_LEVELS if level.distance < distance - eps]
        return max(closer) if closer else MIN_DISTANCE
    farther = [level.distance for level in ZOOM_LEVELS if level.distance > distance + eps]
    return min(farther) if farther else MAX_DISTANCE


def zoom_level_name(distance: float, tolerance: float = 0.02) -> str | None:
    """Name of the zoom level the camera is at, or None between levels."""
    for level in ZOOM_LEVELS:
        if abs(level.distance - distance) <= tolerance * level.distance:
            return level.name
    return None


def zoom_fraction(distance: float) -> float:
    """Zoom slider position for a camera distance: 1.0 at the closest level, 0.0 at the farthest.

    The scale is logarithmic, so equal slider steps give equal zoom ratios.
    """
    low, high = math.log(MIN_DISTANCE), math.log(MAX_DISTANCE)
    return (high - math.log(clamp_distance(distance))) / (high - low)


def zoom_distance(fraction: float) -> float:
    """Camera distance for a slider position (the inverse of zoom_fraction)."""
    low, high = math.log(MIN_DISTANCE), math.log(MAX_DISTANCE)
    return math.exp(high - min(1.0, max(0.0, fraction)) * (high - low))


def level_of_detail(distance: float) -> int:
    """Detail of the vector data: 0 whole globe, 1 close globe, 2 region to city."""
    if distance < 1.5:
        return 2
    if distance < 2.5:
        return 1
    return 0


def clip_planes(distance: float) -> tuple[float, float]:
    """Near and far planes that keep the whole visible hemisphere inside the frustum."""
    return max(1e-5, 0.5 * (distance - 1.0)), distance + 2.0


# -- daylight ------------------------------------------------------------------------------------
def subsolar_point(when: datetime) -> tuple[float, float]:
    """Longitude and latitude in degrees of the point under the sun (NOAA solar approximation)."""
    utc = when.astimezone(timezone.utc) if when.tzinfo else when.replace(tzinfo=timezone.utc)
    hours = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
    gamma = 2.0 * math.pi / 365.0 * (utc.timetuple().tm_yday - 1 + (hours - 12.0) / 24.0)
    equation_of_time = 229.18 * (  # minutes
        0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma)
    )
    declination = (  # radians
        0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma)
    )
    lng = 180.0 - (hours * 60.0 + equation_of_time) / 4.0
    lng = (lng + 180.0) % 360.0 - 180.0
    return lng, math.degrees(declination)


def sun_direction(when: datetime) -> np.ndarray:
    """Unit vector towards the sun in the globe's Earth-fixed frame (for day and night shading)."""
    lng, lat = subsolar_point(when)
    vector = lonlat_to_xyz(lng, lat).astype(np.float64)
    return vector / np.linalg.norm(vector)


# -- camera --------------------------------------------------------------------------------------
def rot_x(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], dtype=np.float64)


def rot_y(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], dtype=np.float64)


def model_matrix(yaw: float, pitch: float) -> np.ndarray:
    return rot_x(pitch) @ rot_y(yaw)


def perspective(fovy_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy_deg) / 2.0)
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = f / max(aspect, 1e-6)
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def view_matrix(dist: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float64)
    m[2, 3] = -dist
    return m


def camera_angles_for(lng_deg: float, lat_deg: float) -> tuple[float, float]:
    """Yaw and pitch that rotate the given coordinate to the front of the globe."""
    p = lonlat_to_xyz(lng_deg, lat_deg).astype(np.float64)
    r = math.hypot(p[0], p[2])
    yaw = math.atan2(-p[0], p[2])
    pitch = math.atan2(p[1], r)
    return yaw, max(-MAX_PITCH, min(MAX_PITCH, pitch))


# -- meshes --------------------------------------------------------------------------------------
def orient_outward(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Return the triangles wound counter-clockwise when seen from outside the globe."""
    a, b, c = (points[triangles[:, k]].astype(np.float64) for k in range(3))
    normal = np.cross(b - a, c - a)
    centre = a + b + c
    flip = np.einsum("ij,ij->i", normal, centre) < 0.0
    oriented = triangles.copy()
    oriented[flip] = triangles[flip][:, [0, 2, 1]]
    return oriented


def globe_mesh(stacks: int = 180, slices: int = 360) -> tuple[np.ndarray, np.ndarray]:
    """Ocean base: a latitude and longitude grid on the ellipsoid (flat triangle indices)."""
    lat = np.linspace(90.0, -90.0, stacks + 1)
    lng = np.linspace(-180.0, 180.0, slices + 1)
    lng_grid, lat_grid = np.meshgrid(lng, lat)
    positions = lonlat_to_xyz(lng_grid, lat_grid).reshape(-1, 3)
    row = slices + 1
    i = np.arange(stacks)[:, None]
    j = np.arange(slices)[None, :]
    a = (i * row + j).ravel()
    b = a + row
    c = a + 1
    d = b + 1
    triangles = np.concatenate([np.stack([a, b, c], axis=1), np.stack([c, b, d], axis=1)])
    return positions, orient_outward(positions, triangles).astype(np.uint32).ravel()


# -- projection and picking ----------------------------------------------------------------------
def project(points_xyz: np.ndarray, model: np.ndarray, dist: float, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (pixel_xy[N,2] with origin top-left, visible[N] bool)."""
    points = points_xyz.astype(np.float64)
    rotated = points @ model[:3, :3].T
    eye = model[:3, :3].T @ np.array([0.0, 0.0, dist])  # camera position in Earth-fixed coordinates
    normals = points * np.array([1.0, INV_POLE_SCALE_SQ, 1.0])
    visible = np.einsum("ij,ij->i", normals, eye - points) > 0.0
    aspect = width / max(height, 1)
    near, far = clip_planes(dist)
    proj = perspective(FOVY_DEG, aspect, near, far) @ view_matrix(dist)
    homo = np.concatenate([rotated, np.ones((rotated.shape[0], 1))], axis=1)
    clip = homo @ proj.T
    w = np.where(np.abs(clip[:, 3]) < 1e-9, 1e-9, clip[:, 3])
    ndc_x = clip[:, 0] / w
    ndc_y = clip[:, 1] / w
    px = (ndc_x + 1.0) * 0.5 * width
    py = (1.0 - ndc_y) * 0.5 * height
    return np.stack([px, py], axis=1), visible


def pick_nearest(
    points_xyz: np.ndarray,
    model: np.ndarray,
    dist: float,
    width: int,
    height: int,
    x: float,
    y: float,
    radius_px: float = 14.0,
    weights: np.ndarray | None = None,
) -> int | None:
    """Index of the visible point closest to (x, y) within ``radius_px``, else None.

    ``weights`` (e.g. station counts) breaks near-ties in favour of bigger places.
    """
    screen, visible = project(points_xyz, model, dist, width, height)
    d2 = (screen[:, 0] - x) ** 2 + (screen[:, 1] - y) ** 2
    candidates = np.where(visible & (d2 <= radius_px * radius_px))[0]
    if candidates.size == 0:
        return None
    if weights is None:
        return int(candidates[np.argmin(d2[candidates])])
    # Bigger places win only within about 2 px: a dot clicked exactly should stay the target.
    score = d2[candidates] - np.minimum(weights[candidates], 30.0) * 0.15
    return int(candidates[np.argmin(score)])
