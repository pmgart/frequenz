"""Runtime access to the globe's vector map arrays (numpy only).

The arrays are produced by ``globe_build`` (``frequenz build-globe``) from Natural Earth
1:10m data (public domain). The viewer never triangulates anything; it only loads the files:

* ``<layer>-lod<n>.npz`` with ``vertices`` (float32 N x 3, on the ellipsoid) and ``indices``
  (uint32 M x 3, counter-clockwise from outside) for surfaces, or ``segments`` (float32 S x 2 x 3)
  for lines,
* ``manifest.json`` with sources, checksums and counts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import geo

SCHEMA = 1
NE_BASE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
LICENCE = "Natural Earth, public domain: https://www.naturalearthdata.com/about/terms-of-use/"


@dataclass(frozen=True)
class Source:
    layer: str  # name used in the output files
    file: str  # Natural Earth file name without the .geojson extension
    kind: str  # "surface" (triangulated polygons) or "line"


SOURCES = (
    Source("land", "ne_10m_land", "surface"),
    Source("lakes", "ne_10m_lakes", "surface"),
    Source("ice", "ne_10m_glaciated_areas", "surface"),
    Source("borders", "ne_10m_admin_0_boundary_lines_land", "line"),
    Source("rivers", "ne_10m_rivers_lake_centerlines", "line"),
)
# Ocean depth bands (Natural Earth 10m bathymetry K_200, J_1000, I_2000, H_3000) are deliberately not
# built: their outlines contain straight lines that do not follow the seafloor (up to about 90 degrees
# long), so the ocean is drawn as one colour. See docs/REVERSE_ENGINEERING.md and the README.
SURFACE_LAYERS = tuple(source.layer for source in SOURCES if source.kind == "surface")


@dataclass(frozen=True)
class Detail:
    lod: int
    simplify_deg: float  # Douglas-Peucker tolerance; 0 keeps the source vertices
    cell_deg: float  # tile size; keeps chords between vertices short on the sphere
    densify_deg: float  # longest allowed edge after simplification


DETAIL = (
    Detail(0, simplify_deg=0.12, cell_deg=2.0, densify_deg=0.5),  # whole globe
    Detail(1, simplify_deg=0.02, cell_deg=2.0, densify_deg=0.25),  # close globe
    Detail(2, simplify_deg=0.0, cell_deg=1.0, densify_deg=0.2),  # region to city
)
LINE_LODS = {"borders": (1, 2), "rivers": (2,)}


def is_built(globe_dir: Path) -> bool:
    return (globe_dir / "manifest.json").is_file()


def surface_contains(vertices: np.ndarray, indices: np.ndarray, lng: float, lat: float) -> bool:
    """True when the surface triangles cover (lng, lat): a ray from the centre through that point hits one.

    Used to check the built geography against known places (Möller-Trumbore on nearby triangles).
    """
    direction = geo.lonlat_to_xyz(lng, lat).astype(np.float64)
    direction /= np.linalg.norm(direction)
    near = np.nonzero(vertices.astype(np.float64) @ direction > math.cos(math.radians(6.0)))[0]
    if near.size == 0:
        return False
    tris = indices[np.isin(indices, near).any(axis=1)].astype(np.int64)
    if tris.size == 0:
        return False
    a = vertices[tris[:, 0]].astype(np.float64)
    b = vertices[tris[:, 1]].astype(np.float64)
    c = vertices[tris[:, 2]].astype(np.float64)
    e1, e2 = b - a, c - a
    p = np.cross(direction, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-14
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    s = -a
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, e1)
    v = (q @ direction) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    return bool(np.any(ok & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (t > 0.0)))


def load_layer(globe_dir: Path, layer: str, lod: int) -> dict[str, np.ndarray] | None:
    """Arrays of one layer at one detail level, or None when that level was not built."""
    path = globe_dir / f"{layer}-lod{lod}.npz"
    if not path.is_file():
        return None
    with np.load(path) as data:
        return {name: data[name] for name in data.files}
