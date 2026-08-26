"""
Event Polygon Optimizer Service
Job orchestration, node collection and Kido platform calls.

The tool measures where event attendance actually landed on the z=18
projection grid, instead of trusting a hand-drawn polygon. It builds a
throwaway diagnostic project with one zone per node, reads the hourly
arrival curve of each node and proposes an optimised polygon.

Credentials never touch disk or logs: the access token lives only inside the
in-memory job record and is stripped from every response.
"""

import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import pandas as pd
import shapely.ops
from pyproj import Transformer
from shapely.geometry import mapping, shape

from services.geo import get_utm_crs
from services.nodes import NodeFileError, covers_bbox, query_bbox
from services.tiles import tile_polygon

# ==========================================
# CONSTANTS
# ==========================================

# Steps reported to the sidebar to-do list, in execution order.
STEPS: List[Tuple[str, str]] = [
    ("collect_nodes", "Collect nearby nodes"),
    ("build_project_geojson", "Build diagnostic zones"),
    ("validate_project", "Validate zoning on platform"),
    ("price_project", "Check project price"),
    ("create_project", "Create project on platform"),
    ("wait_ready", "Wait for project to be ready"),
    ("query_event_daily", "Query event day totals"),
    ("query_event_hourly", "Query event day arrivals by hour"),
    ("query_baseline", "Query baseline day"),
    ("score", "Score nodes and build suggestion"),
]

# Node count guards. Above SOFT the map gets hard to read and the project gets
# expensive; HARD is the platform ceiling of 2048 polygons per project.
NODE_COUNT_SOFT_LIMIT = 800
NODE_COUNT_HARD_LIMIT = 2000

# Diagnostic zones are the tile square shrunk around its center, so that a
# zone contains exactly its own node at any latitude.
ZONE_SHRINK = 0.8

# A candidate belongs to the outer ring when it sits outside the input polygon
# and further than this share of the buffer radius from it.
OUTER_RING_FRACTION = 0.6

JOB_TTL_SECONDS = 2 * 60 * 60
MAX_JOBS = 20


class OptimizerError(Exception):
    """Raised for user-facing failures during a job."""


# ==========================================
# JOB STORE
# ==========================================

_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.RLock()


def _new_steps() -> List[Dict[str, Any]]:
    return [
        {"key": key, "label": label, "state": "pending", "detail": None}
        for key, label in STEPS
    ]


def _purge_expired() -> None:
    """Drop jobs older than the TTL, then trim to the concurrency ceiling."""
    now = time.time()
    with _jobs_lock:
        for job_id in [j for j, v in _jobs.items() if now - v["created_at"] > JOB_TTL_SECONDS]:
            _jobs.pop(job_id, None)

        while len(_jobs) >= MAX_JOBS:
            oldest = min(_jobs, key=lambda j: _jobs[j]["created_at"])
            _jobs.pop(oldest, None)


def create_job(request: Dict[str, Any]) -> str:
    """Register a new job and return its id. The request holds the token."""
    _purge_expired()
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "created_at": time.time(),
            "state": "pending",
            "steps": _new_steps(),
            "error": None,
            "result": None,
            "request": request,
            "raw": {},
        }
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    with _jobs_lock:
        return _jobs.get(job_id)


def job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Return the status payload for a job, without the stored credentials."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return {
            "job_id": job["job_id"],
            "state": job["state"],
            "steps": [dict(s) for s in job["steps"]],
            "error": job["error"],
            "result": job["result"],
        }


def set_step(job_id: str, key: str, state: str, detail: Optional[str] = None) -> None:
    """Update one step of the sidebar to-do list."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        for step in job["steps"]:
            if step["key"] == key:
                step["state"] = state
                if detail is not None:
                    step["detail"] = detail
                break


def fail_job(job_id: str, message: str) -> None:
    """Mark a job as failed and stop every step still waiting."""
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["state"] = "error"
        job["error"] = message
        for step in job["steps"]:
            if step["state"] == "running":
                step["state"] = "error"
            elif step["state"] == "pending":
                step["state"] = "skipped"


def finish_job(job_id: str, result: Dict[str, Any]) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["state"] = "done"
        job["result"] = result


# ==========================================
# INPUT GEOMETRY
# ==========================================

def extract_input_polygon(geojson: Dict[str, Any]) -> Tuple[Any, List[Dict[str, str]]]:
    """
    Take the analysis polygon out of an uploaded or drawn GeoJSON.

    Accepts a FeatureCollection, a single Feature or a bare geometry. Only the
    first polygon is used, and the caller is told when others were discarded.

    Returns:
        Tuple of (shapely geometry, warnings)

    Raises:
        OptimizerError with an actionable message for unusable input.
    """
    warnings: List[Dict[str, str]] = []

    if not isinstance(geojson, dict):
        raise OptimizerError("The polygon is not valid GeoJSON. Upload a .geojson file or draw the area on the map.")

    crs = geojson.get("crs")
    if isinstance(crs, dict):
        name = str(crs.get("properties", {}).get("name", ""))
        if name and "CRS84" not in name.upper() and "4326" not in name:
            raise OptimizerError(
                "The GeoJSON declares the projected CRS '{}'. Reproject it to "
                "EPSG:4326 (longitude/latitude) and upload it again.".format(name)
            )

    gtype = geojson.get("type")
    if gtype == "FeatureCollection":
        features = [f for f in geojson.get("features", []) if isinstance(f, dict)]
        if not features:
            raise OptimizerError("The GeoJSON has no features. It must contain one polygon with the event area.")
        if len(features) > 1:
            warnings.append({
                "level": "warning",
                "code": "multiple_features",
                "message": "The file has {} features. Only the first one was used.".format(len(features)),
            })
        geometry = features[0].get("geometry")
    elif gtype == "Feature":
        geometry = geojson.get("geometry")
    else:
        geometry = geojson

    if not isinstance(geometry, dict) or "type" not in geometry:
        raise OptimizerError("The GeoJSON has no readable geometry. It must contain one Polygon or MultiPolygon.")

    if geometry.get("type") not in ("Polygon", "MultiPolygon"):
        raise OptimizerError(
            "The geometry is a {}. This tool needs a Polygon or MultiPolygon "
            "covering the event area.".format(geometry.get("type"))
        )

    try:
        geom = shape(geometry)
    except Exception as exc:
        raise OptimizerError("The geometry could not be read ({}). Check the coordinates and try again.".format(exc))

    if geom.is_empty:
        raise OptimizerError("The polygon is empty. Draw the event area on the map or upload a valid file.")

    if not geom.is_valid:
        geom = geom.buffer(0)
        if geom.is_empty or not geom.is_valid:
            raise OptimizerError("The polygon is self-intersecting and could not be repaired. Redraw it.")
        warnings.append({
            "level": "info",
            "code": "geometry_repaired",
            "message": "The polygon was self-intersecting and was repaired automatically.",
        })

    west, south, east, north = geom.bounds
    if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0
            and -90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
        raise OptimizerError(
            "The coordinates are outside the longitude/latitude range, which "
            "means the file is in a projected CRS. Reproject it to EPSG:4326."
        )

    return geom, warnings


def _utm_transformers(geom: Any):
    """Build the WGS84 <-> local UTM transformer pair for a geometry."""
    centroid = geom.centroid
    utm_crs = get_utm_crs(centroid.y, centroid.x)
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_wgs = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)
    return to_utm, to_wgs


def buffer_polygon(geom: Any, buffer_m: float) -> Any:
    """Buffer a WGS84 geometry by a distance in meters, through local UTM."""
    to_utm, to_wgs = _utm_transformers(geom)
    geom_utm = shapely.ops.transform(lambda x, y: to_utm.transform(x, y), geom)
    buffered_utm = geom_utm.buffer(buffer_m)
    return shapely.ops.transform(lambda x, y: to_wgs.transform(x, y), buffered_utm)


# ==========================================
# NODE COLLECTION
# ==========================================

def collect_nodes(
    country_code: str,
    geom: Any,
    buffer_m: float,
) -> Tuple[pd.DataFrame, Any, List[Dict[str, str]]]:
    """
    Find every projection node inside the buffered analysis area.

    Args:
        country_code: Country whose node file is cached
        geom: Input polygon in EPSG:4326
        buffer_m: Collection buffer radius in meters

    Returns:
        Tuple of (nodes frame, buffered geometry, warnings)

        The frame has one row per candidate node with columns node_id, x, y,
        lon, lat, in_seed, dist_m (distance to the input polygon border, zero
        inside) and in_outer_ring.
    """
    warnings: List[Dict[str, str]] = []
    buffered = buffer_polygon(geom, buffer_m)
    west, south, east, north = buffered.bounds

    if not covers_bbox(country_code, west, south, east, north):
        raise OptimizerError(
            "The uploaded node file does not cover the area of your polygon. "
            "Wrong country? The file must be the projection node export for {}.".format(
                country_code.upper()
            )
        )

    try:
        candidates = query_bbox(country_code, west, south, east, north)
    except NodeFileError as exc:
        raise OptimizerError(str(exc))

    if candidates.empty:
        raise OptimizerError(
            "No projection nodes were found around your polygon. Check that the "
            "country matches the node file and that the polygon is in the right place."
        )

    points = gpd.GeoSeries(
        gpd.points_from_xy(candidates["longitude"], candidates["latitude"]),
        crs="EPSG:4326",
    )
    inside_buffer = points.within(buffered).values
    candidates = candidates[inside_buffer].reset_index(drop=True)
    points = points[inside_buffer].reset_index(drop=True)

    if candidates.empty:
        raise OptimizerError(
            "No projection nodes fall inside the buffered area. Increase the "
            "collection radius or check that the polygon is in the right place."
        )

    if len(candidates) > NODE_COUNT_HARD_LIMIT:
        raise OptimizerError(
            "The area holds {} nodes, above the platform ceiling of {} polygons "
            "per project. Reduce the collection radius or draw a smaller area.".format(
                len(candidates), NODE_COUNT_HARD_LIMIT
            )
        )

    if len(candidates) > NODE_COUNT_SOFT_LIMIT:
        warnings.append({
            "level": "warning",
            "code": "many_nodes",
            "message": (
                "{} nodes were collected. Above {} the map gets hard to read and "
                "the diagnostic project gets slow. Consider a smaller collection "
                "radius or a tighter polygon.".format(len(candidates), NODE_COUNT_SOFT_LIMIT)
            ),
        })

    in_seed = points.within(geom).values

    # Distance to the input polygon border, measured in meters through UTM.
    to_utm, _ = _utm_transformers(geom)
    geom_utm = shapely.ops.transform(lambda x, y: to_utm.transform(x, y), geom)
    px, py = to_utm.transform(candidates["longitude"].values, candidates["latitude"].values)
    points_utm = gpd.GeoSeries(gpd.points_from_xy(px, py))
    dist_m = points_utm.distance(geom_utm).values
    dist_m = [0.0 if seed else float(d) for seed, d in zip(in_seed, dist_m)]

    frame = pd.DataFrame({
        "node_id": candidates["id"].astype("int64").values,
        "x": candidates["x"].astype("int32").values,
        "y": candidates["y"].astype("int32").values,
        "lon": candidates["longitude"].astype("float64").values,
        "lat": candidates["latitude"].astype("float64").values,
        "in_seed": in_seed,
        "dist_m": dist_m,
    })
    frame["in_outer_ring"] = (~frame["in_seed"]) & (frame["dist_m"] > OUTER_RING_FRACTION * buffer_m)

    if not frame["in_seed"].any():
        # Nothing sits inside the drawn polygon, which happens with polygons
        # smaller than a tile. Fall back to the five closest nodes.
        nearest = frame.nsmallest(min(5, len(frame)), "dist_m").index
        frame.loc[nearest, "in_seed"] = True
        warnings.append({
            "level": "warning",
            "code": "no_seed_nodes",
            "message": (
                "No projection node falls inside your polygon, probably because it "
                "is smaller than one tile. The {} closest nodes were used as the "
                "seed instead.".format(len(nearest))
            ),
        })

    return frame, buffered, warnings


# ==========================================
# DIAGNOSTIC PROJECT
# ==========================================

def build_diagnostic_geojson(frame: pd.DataFrame) -> Dict[str, Any]:
    """
    Build the diagnostic project GeoJSON: one zone per node.

    Each zone is the tile square shrunk to 80 percent around its center. A
    fixed-radius circle would behave differently by latitude, since a tile is
    141 m wide in Rio and 117 m in Madrid, while the shrunk square always holds
    exactly its own node and no neighbour.

    The zone id is the node id itself and the name is buffer_{node_id}, which
    is the convention the stays response echoes back in `sector`.
    """
    features = []
    for row in frame.itertuples(index=False):
        features.append({
            "type": "Feature",
            "properties": {
                "id": int(row.node_id),
                "name": "buffer_{}".format(int(row.node_id)),
                "poly_type": "core",
            },
            "geometry": mapping(tile_polygon(int(row.x), int(row.y), shrink=ZONE_SHRINK)),
        })

    return {"type": "FeatureCollection", "features": features}


def build_project_name(now: Optional[datetime] = None) -> str:
    """Build the unique diagnostic project name used to find it again later."""
    now = now or datetime.now()
    return "polyopt_{}".format(now.strftime("%Y%m%d_%H%M%S"))


PROJECT_DESCRIPTION = (
    "Temporary diagnostic project created by the Event Polygon Optimizer. "
    "One zone per projection node. Safe to delete once the analysis is exported."
)


# ==========================================
# JOB PIPELINE
# ==========================================

def run_job(job_id: str) -> None:
    """
    Execute an analysis job, updating the sidebar to-do list as it goes.

    Runs in a background task. Every failure is turned into a user-facing
    message on the job record rather than an exception, so the front end
    always has something actionable to show.
    """
    job = get_job(job_id)
    if job is None:
        return

    with _jobs_lock:
        job["state"] = "running"

    request = job["request"]

    try:
        # --- Collect nearby nodes -------------------------------------------
        set_step(job_id, "collect_nodes", "running")
        geom, warnings = extract_input_polygon(request["geojson"])
        frame, buffered, collect_warnings = collect_nodes(
            request["country_code"], geom, request["buffer_m"]
        )
        warnings.extend(collect_warnings)
        set_step(job_id, "collect_nodes", "done", "{} nodes found".format(len(frame)))

        # --- Build the diagnostic zones -------------------------------------
        set_step(job_id, "build_project_geojson", "running")
        zones = build_diagnostic_geojson(frame)
        project_name = build_project_name()
        set_step(
            job_id,
            "build_project_geojson",
            "done",
            "{} zones".format(len(zones["features"])),
        )

        with _jobs_lock:
            job["raw"].update({
                "frame": frame,
                "seed_geometry": geom,
                "buffer_geometry": buffered,
                "zones": zones,
                "project_name": project_name,
                "warnings": warnings,
            })

        run_platform_pipeline(job_id)

    except OptimizerError as exc:
        fail_job(job_id, str(exc))
    except Exception as exc:  # pragma: no cover - last-resort guard
        fail_job(job_id, "The analysis stopped unexpectedly: {}".format(exc))


def run_platform_pipeline(job_id: str) -> None:
    """
    Create the diagnostic project, read the stays and score the nodes.

    Implemented in the platform integration step; the local part of the
    pipeline above already runs end to end.
    """
    raise OptimizerError(
        "The platform integration is not wired up in this build yet. "
        "The node collection and the diagnostic zones are ready."
    )
