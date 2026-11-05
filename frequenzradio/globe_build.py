"""Build the globe's vector map from Natural Earth 1:10m data (needs the ``build`` extra: shapely).

For every polygon layer and detail level:
1. simplify (coarse levels only) and densify the boundaries,
2. cut the polygons into longitude and latitude cells (1 or 2 degrees),
3. triangulate each piece exactly with a constrained Delaunay triangulation,
4. check that the triangles cover the pieces' planar area (a mismatch aborts the build),
5. place the vertices on the ellipsoid and orient every triangle counter-clockwise from outside.

Line layers are simplified and densified, then stored as segments. Output goes to
``globe_dir``; see ``frequenzradio.geodata`` for the file format.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Callable

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import Polygon, shape

from . import geo
from .geodata import DETAIL, LICENCE, LINE_LODS, NE_BASE_URL, SCHEMA, SOURCES, Detail

_UNITS = 1e7  # quantisation of longitude and latitude: 1e-7 degree (about 1 cm)
_LON_OFFSET = 1_800_000_000
_LAT_OFFSET = 900_000_000
_KEY_STRIDE = 1_800_000_001


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_sources(target: Path, *, log: Callable[[str], None] = print) -> None:
    """Download the Natural Earth files that are not in ``target`` yet."""
    target.mkdir(parents=True, exist_ok=True)
    for source in SOURCES:
        path = target / f"{source.file}.geojson"
        if path.exists():
            continue
        log(f"downloading {source.file}")
        partial = target / f"{source.file}.part"
        with urllib.request.urlopen(NE_BASE_URL + source.file + ".geojson", timeout=300) as response:
            with partial.open("wb") as handle:
                for chunk in iter(lambda: response.read(1 << 20), b""):
                    handle.write(chunk)
        os.replace(partial, path)


def _load_geometries(path: Path) -> list:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return [shape(feature["geometry"]) for feature in data["features"] if feature.get("geometry")]


def _object_array(items) -> np.ndarray:
    array = np.empty(len(items), dtype=object)
    for index, item in enumerate(items):  # assign one by one: numpy must not unpack geometries
        array[index] = item
    return array


def _polygons(geometries) -> list:
    """Valid, non-empty polygons from any geometries. Invalid input is repaired; lines are dropped."""
    if len(geometries) == 0:
        return []
    polygons = []
    for geometry in shapely.make_valid(_object_array(geometries)):
        for part in shapely.get_parts(geometry):
            if part.geom_type == "Polygon" and not part.is_empty and part.area > 0:
                polygons.append(part)
    return polygons


def _unwrap(coords: np.ndarray) -> np.ndarray:
    """Make longitudes continuous along a ring that crosses the antimeridian."""
    lng = coords[:, 0].astype(np.float64).copy()
    steps = np.diff(lng)
    shifts = np.where(steps > 180.0, -360.0, np.where(steps < -180.0, 360.0, 0.0))
    lng[1:] += np.cumsum(shifts)
    return np.column_stack([lng, coords[:, 1]])


def _split_antimeridian(polygon) -> list:
    """Cut a polygon whose ring jumps across ±180° into pieces inside [-180, 180]."""
    rings = [np.asarray(polygon.exterior.coords)[:, :2]] + [np.asarray(r.coords)[:, :2] for r in polygon.interiors]
    if not any(np.any(np.abs(np.diff(ring[:, 0])) > 180.0) for ring in rings):
        return [polygon]
    unwrapped = shapely.make_valid(Polygon(_unwrap(rings[0]), [_unwrap(ring) for ring in rings[1:]]))
    pieces = []
    for shift in (-360.0, 0.0, 360.0):
        moved = affinity.translate(unwrapped, xoff=shift)
        pieces.extend(_polygons([shapely.clip_by_rect(moved, -180.0, -90.0, 180.0, 90.0)]))
    return pieces


def _split_all(polygons) -> list:
    pieces = []
    for polygon in polygons:
        pieces.extend(_split_antimeridian(polygon))
    return pieces


def _prepare(polygons, detail: Detail) -> list:
    """Simplify and densify the polygons for one detail level; they stay valid."""
    prepared = []
    for polygon in polygons:
        geometry = polygon
        if detail.simplify_deg > 0:
            geometry = geometry.simplify(detail.simplify_deg, preserve_topology=True)
        geometry = shapely.segmentize(geometry, detail.densify_deg)
        prepared.extend(_polygons([geometry]))
    return prepared


def _triangulate(polygons, cell_deg: float) -> tuple[np.ndarray, float, float]:
    """Cut the polygons into longitude and latitude cells and triangulate every piece exactly.

    Returns the triangles (T, 3, 2) in degrees, the planar area they cover and the planar area of
    the pieces. The caller checks that the last two agree.
    """
    if not polygons:
        return np.zeros((0, 3, 2)), 0.0, 0.0
    tree = shapely.STRtree(polygons)
    items = _object_array(polygons)
    chunks: list[np.ndarray] = []
    expected = 0.0
    for x0 in np.arange(-180.0, 180.0, cell_deg):
        for y0 in np.arange(-90.0, 90.0, cell_deg):
            x1, y1 = x0 + cell_deg, y0 + cell_deg
            hits = tree.query(shapely.box(x0, y0, x1, y1))
            if hits.size == 0:
                continue
            clipped = shapely.clip_by_rect(items[hits], x0, y0, x1, y1)
            for piece in _polygons(list(clipped)):
                expected += piece.area
                triangles = shapely.get_parts(shapely.constrained_delaunay_triangles(piece))
                coords = shapely.get_coordinates(triangles)
                if coords.shape[0] != 4 * len(triangles):
                    raise RuntimeError(f"unexpected triangulation output for a piece of area {piece.area:.6f}")
                chunks.append(coords.reshape(-1, 4, 2)[:, :3])
    if not chunks:
        return np.zeros((0, 3, 2)), 0.0, expected
    tris = np.concatenate(chunks)
    e1 = tris[:, 1] - tris[:, 0]
    e2 = tris[:, 2] - tris[:, 0]
    covered = 0.5 * float(np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]).sum())
    return tris, covered, expected


def _triangles_to_mesh(tris: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Shared vertices on the ellipsoid and counter-clockwise triangle indices."""
    flat = np.rint(tris.reshape(-1, 2) * _UNITS).astype(np.int64)
    keys = (flat[:, 0] + _LON_OFFSET) * _KEY_STRIDE + (flat[:, 1] + _LAT_OFFSET)
    unique, inverse = np.unique(keys, return_inverse=True)
    lng = (unique // _KEY_STRIDE - _LON_OFFSET) / _UNITS
    lat = (unique % _KEY_STRIDE - _LAT_OFFSET) / _UNITS
    vertices = geo.lonlat_to_xyz(lng, lat)
    indices = inverse.reshape(-1, 3).astype(np.int64)
    a, b, c = (vertices[indices[:, k]].astype(np.float64) for k in range(3))
    area2 = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    indices = geo.orient_outward(vertices, indices[area2 > 1e-12])  # drop triangles collapsed at a pole
    return vertices, indices.astype(np.uint32)


def _build_surface(job: tuple) -> dict:
    """Worker: one polygon layer at one detail level. Runs in a separate process."""
    source_file, layer, detail_values, globe_dir = job
    detail = Detail(*detail_values)
    started = time.monotonic()
    polygons = _split_all(_polygons(_load_geometries(Path(source_file))))
    tris, covered, expected = _triangulate(_prepare(polygons, detail), detail.cell_deg)
    if abs(covered - expected) > 1e-8 * max(expected, 1e-12):
        raise RuntimeError(
            f"{layer} lod{detail.lod}: triangles cover {covered:.9f} deg2 but the pieces cover {expected:.9f} deg2"
        )
    vertices, indices = _triangles_to_mesh(tris)
    path = Path(globe_dir) / f"{layer}-lod{detail.lod}.npz"
    np.savez(path, vertices=vertices, indices=indices)
    return {
        "name": f"{layer}-lod{detail.lod}",
        "vertices": int(len(vertices)),
        "triangles": int(len(indices)),
        "area_deg2": round(expected, 3),
        "bytes": path.stat().st_size,
        "seconds": round(time.monotonic() - started, 1),
    }


def _line_segments(geometries, detail: Detail) -> np.ndarray:
    lines = []
    for geometry in geometries:
        for part in shapely.get_parts(geometry):
            if part.geom_type == "LineString" and not part.is_empty:
                lines.append(part)
    if not lines:
        return np.zeros((0, 2, 3), dtype=np.float32)
    array = _object_array(lines)
    if detail.simplify_deg > 0:
        array = shapely.simplify(array, detail.simplify_deg)
    array = shapely.segmentize(array, detail.densify_deg)
    coords, index = shapely.get_coordinates(array, return_index=True)
    same = index[:-1] == index[1:]  # join consecutive points only within one line
    pairs = np.stack([coords[:-1][same], coords[1:][same]], axis=1)  # (S, 2, 2) lng, lat
    return geo.lonlat_to_xyz(pairs[..., 0], pairs[..., 1]).astype(np.float32)


def _angle_diff(a: float, b: float) -> float:
    return (a - b + math.pi) % (2.0 * math.pi) - math.pi


def _straight_runs(xy: np.ndarray, tol_deg: float = 0.05, min_len: float = 10.0) -> list[tuple[float, np.ndarray]]:
    """Runs of consecutive edges that keep one heading (within tol_deg) and are longer than min_len degrees."""
    dxy = np.diff(xy, axis=0)
    lengths = np.hypot(dxy[:, 0], dxy[:, 1])
    heading = np.arctan2(dxy[:, 1], dxy[:, 0])
    breaks = np.abs(dxy[:, 0]) > 180.0  # antimeridian jumps are not edges
    tol = math.radians(tol_deg)
    runs: list[tuple[float, np.ndarray]] = []
    i, n = 0, len(heading)
    while i < n:
        if breaks[i] or lengths[i] == 0.0:
            i += 1
            continue
        reference, j, total = heading[i], i, lengths[i]
        while (j + 1 < n and not breaks[j + 1] and lengths[j + 1] > 0.0
               and abs(_angle_diff(heading[j + 1], reference)) < tol):
            j += 1
            total += lengths[j]
        if total > min_len:
            runs.append((float(total), xy[i:j + 2]))
        i = j + 1
    return runs


def outline_straight_runs(geometry, min_len: float = 10.0) -> list[tuple[float, tuple[float, float], tuple[float, float]]]:
    """Straight runs longer than min_len degrees on the outline of a geometry (map edges excluded).

    Real coastlines and ice fronts can be straight for several degrees (Antarctic ice shelves reach about 9),
    but a depth contour or a coastline 10 degrees long without a bend is an artifact. Runs on the antimeridian
    or within 0.001 degree of a pole are map edges and are not reported.
    """
    found: list[tuple[float, tuple[float, float], tuple[float, float]]] = []
    for line in shapely.get_parts(geometry.boundary):
        for length, pts in _straight_runs(shapely.get_coordinates(line), min_len=min_len):
            on_map_edge = bool(np.all((np.abs(pts[:, 0]) > 180.0 - 1e-3) | (np.abs(pts[:, 1]) > 90.0 - 1e-3)))
            if not on_map_edge:
                found.append((length, (float(pts[0, 0]), float(pts[0, 1])), (float(pts[-1, 0]), float(pts[-1, 1]))))
    return found


def build_globe(source_dir: Path, globe_dir: Path, *, workers: int | None = None,
                log: Callable[[str], None] = print) -> dict:
    """Triangulate every layer and detail level into ``globe_dir``. Returns the manifest."""
    globe_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    jobs = []
    for source in SOURCES:
        path = source_dir / f"{source.file}.geojson"
        if not path.exists():
            raise FileNotFoundError(f"missing {path}; the source files are fetched first")
        if source.kind == "surface":
            for detail in DETAIL:
                jobs.append((str(path), source.layer,
                             (detail.lod, detail.simplify_deg, detail.cell_deg, detail.densify_deg),
                             str(globe_dir)))
    layers: dict[str, dict] = {}
    with ProcessPoolExecutor(max_workers=workers or min(4, os.cpu_count() or 1)) as pool:
        for stats in pool.map(_build_surface, jobs):
            layers[stats["name"]] = stats
            log(f"  {stats['name']:<14} {stats['vertices']:>9,} vertices  {stats['triangles']:>9,} triangles"
                f"  {stats['bytes'] / 1e6:6.1f} MB  {stats['seconds']:6.1f}s")
    for source in SOURCES:
        if source.kind != "line":
            continue
        geometries = _load_geometries(source_dir / f"{source.file}.geojson")
        for lod in LINE_LODS[source.layer]:
            segments = _line_segments(geometries, DETAIL[lod])
            path = globe_dir / f"{source.layer}-lod{lod}.npz"
            np.savez(path, segments=segments)
            layers[f"{source.layer}-lod{lod}"] = {"segments": int(len(segments)), "bytes": path.stat().st_size}
            log(f"  {source.layer}-lod{lod:<6} {len(segments):>9,} segments  {path.stat().st_size / 1e6:6.1f} MB")
    produced = {f"{name}.npz" for name in layers}
    for stale in globe_dir.glob("*-lod*.npz"):  # layers no longer in the map, for example removed depth bands
        if stale.name not in produced:
            stale.unlink()
    manifest = {
        "schema": SCHEMA,
        "licence": LICENCE,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seconds": round(time.monotonic() - started, 1),
        "sources": {source.file: {"sha256": _sha256(source_dir / f"{source.file}.geojson")} for source in SOURCES},
        "layers": layers,
    }
    (globe_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
