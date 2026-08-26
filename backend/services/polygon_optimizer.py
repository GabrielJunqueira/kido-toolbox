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

import json
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import shapely.ops
from pyproj import Transformer
from shapely.geometry import mapping, shape

from services import polygon_scoring
from services.geo import get_utm_crs
from services.nodes import NodeFileError, covers_bbox, get_entry, query_bbox
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

    # "No file at all" and "file from the wrong country" need different
    # answers. The first one is common: the Space hibernates and clears /tmp
    # between the upload and the analysis.
    if get_entry(country_code) is None:
        raise OptimizerError(
            "No node file is loaded for {}. The Space clears its temporary storage "
            "when it hibernates, so the projection node file has to be uploaded "
            "again before running an analysis.".format(country_code.upper())
        )

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


# ==========================================
# KIDO PLATFORM CALLS
# ==========================================

# Validation and creation are slow in large countries. This is the timeout the
# rest of the Toolbox uses in production; do not shorten it.
PLATFORM_TIMEOUT = 600
QUERY_TIMEOUT = 300
LIGHT_TIMEOUT = 120

# The stays endpoint answers 422 while the project is still being processed.
QUERY_RETRY_SECONDS = 300
READY_TIMEOUT_SECONDS = 300

STAYS_PAGE_SIZE = 5000

# Analysis stops when the platform rejects more than this share of the zones,
# which means the local node file is out of step with the platform grid.
MAX_REJECTED_SHARE = 0.20

# Analysis stops when the response is almost entirely suppressed.
MAX_SUPPRESSED_SHARE = 0.80

DAILY_METRICS = ["total_wanderers", "total_visitors", "total_passerbys"]

HOURS_IN_DAY = 24


def _v1_base(root_url: str) -> str:
    """Normalise any stored root url into the v1 base."""
    base = root_url.replace("/v2/on-demand/", "/v1/").replace("/v2/", "/v1/")
    if not base.endswith("/"):
        base += "/"
    if not base.endswith("/v1/"):
        base = base.rstrip("/") + "/v1/"
    return base


def _v2_ondemand_base(root_url: str) -> str:
    """Normalise any stored root url into the v2 on-demand base."""
    return _v1_base(root_url).replace("/v1/", "/v2/on-demand/")


def _auth_headers(token: str) -> Dict[str, str]:
    return {"accept": "application/json", "Authorization": "Bearer {}".format(token)}


def _format_422(response: Any) -> str:
    """Turn a FastAPI validation error body into something a human can read."""
    try:
        detail = response.json().get("detail")
    except Exception:
        return response.text[:400]

    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        lines = []
        for item in detail:
            if isinstance(item, dict):
                where = " → ".join(str(p) for p in item.get("loc", []) if p not in ("body",))
                message = item.get("msg", "invalid value")
                lines.append("{}: {}".format(where or "request", message) if where else message)
            else:
                lines.append(str(item))
        return "; ".join(lines)
    return json.dumps(detail)[:400]


def _describe_http_error(action: str, response: Any) -> str:
    """Build a user-facing message for a failed platform call."""
    if response.status_code == 401:
        return (
            "Your session expired while {}. Sign in again and rerun the analysis.".format(action)
        )
    if response.status_code == 403:
        return "Your account is not allowed to {}. Ask for the right permissions.".format(action)
    if response.status_code == 422:
        return "The platform rejected the request while {}: {}".format(action, _format_422(response))
    return "The platform answered {} while {}: {}".format(
        response.status_code, action, response.text[:300]
    )


def validate_zoning(
    root_url: str,
    token: str,
    zones: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """
    Run the mandatory hard validation of the diagnostic zoning.

    Returns:
        Tuple of (clean polygons to create, rejected zone names, platform warnings)
    """
    url = _v1_base(root_url) + "projects/validate?mode=hard&is_aoi_project=false"

    try:
        response = requests.post(
            url, json=zones, headers=_auth_headers(token), timeout=PLATFORM_TIMEOUT
        )
    except requests.exceptions.Timeout:
        raise OptimizerError(
            "Validation timed out after 10 minutes. The platform is slow for large "
            "countries. Wait a few minutes and rerun; nothing was created yet."
        )
    except requests.exceptions.RequestException as exc:
        raise OptimizerError("The platform could not be reached while validating: {}".format(exc))

    if response.status_code != 200:
        raise OptimizerError(_describe_http_error("validating the zoning", response))

    payload = response.json()
    if payload.get("valid") is False:
        raise OptimizerError(
            "The platform rejected the diagnostic zoning: {}. Adjust the polygon or "
            "the collection radius and try again.".format(payload.get("reason", "no reason given"))
        )

    rejected = [str(name) for name in (payload.get("rejected_names") or [])]
    warnings = [str(w) for w in (payload.get("warnings") or [])]
    clean = payload.get("polygons") or zones
    return clean, rejected, warnings


def price_project(
    root_url: str,
    token: str,
    zones: Dict[str, Any],
    start_date: str,
    end_date: str,
) -> Optional[Dict[str, Any]]:
    """
    Ask the platform what the diagnostic project would cost.

    A sanity check rather than a gate: a core count far above the zone count
    means the buffer went too wide. Failures here never block the run.
    """
    url = "{}projects/price?start_date={}&end_date={}".format(
        _v1_base(root_url), start_date, end_date
    )
    try:
        response = requests.post(
            url, json=zones, headers=_auth_headers(token), timeout=LIGHT_TIMEOUT
        )
        if response.status_code != 200:
            return None
        return response.json()
    except requests.exceptions.RequestException:
        return None


def create_diagnostic_project(
    root_url: str,
    token: str,
    name: str,
    description: str,
    zones: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create the throwaway diagnostic project.

    is_geoinsight is False here on purpose. The shared /api/create-project
    endpoint sends True because it serves the Tourism module, which is why
    this tool makes its own call instead of reusing it.
    """
    url = _v1_base(root_url) + "projects/create"
    payload = {
        "name": name,
        "description": description,
        "geojson": zones,
        "is_geoinsight": False,
        "with_traffic": False,
    }

    try:
        response = requests.post(
            url, json=payload, headers=_auth_headers(token), timeout=PLATFORM_TIMEOUT
        )
    except requests.exceptions.Timeout:
        raise OptimizerError(
            "Project creation timed out after 10 minutes. Check the platform for a "
            "project named '{}' before running again, it may have been created.".format(name)
        )
    except requests.exceptions.RequestException as exc:
        raise OptimizerError("The platform could not be reached while creating the project: {}".format(exc))

    if response.status_code != 200:
        raise OptimizerError(_describe_http_error("creating the diagnostic project", response))

    project = response.json()
    if not project.get("id"):
        raise OptimizerError(
            "The platform accepted the project but returned no id. Check the platform "
            "for a project named '{}'.".format(name)
        )
    return project


def fetch_project_by_name(root_url: str, token: str, name: str) -> Optional[Dict[str, Any]]:
    """
    Look the diagnostic project up by its unique name.

    The name carries a timestamp, so the search returns a single record.
    """
    url = "{}projects/?search_term={}&page_size=10".format(_v1_base(root_url), name)
    try:
        response = requests.get(url, headers=_auth_headers(token), timeout=LIGHT_TIMEOUT)
    except requests.exceptions.RequestException:
        return None

    if response.status_code != 200:
        return None

    payload = response.json()
    records = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(payload, dict) and not isinstance(records, list):
        records = payload.get("items") or payload.get("results") or []
    if not isinstance(records, list):
        return None

    for record in records:
        if isinstance(record, dict) and record.get("name") == name:
            return record
    return records[0] if records and isinstance(records[0], dict) else None


def wait_for_ready(
    root_url: str,
    token: str,
    project_name: str,
    project_id: str,
    on_progress=None,
) -> float:
    """
    Poll the project until it reports READY.

    Backoff starts at 3 s and is capped at 15 s per attempt, with a five
    minute ceiling overall.

    Returns:
        Seconds waited.

    Raises:
        OptimizerError naming the project, so the user can pick it up later
        without recreating anything.
    """
    started = time.time()
    delay = 3.0

    while True:
        record = fetch_project_by_name(root_url, token, project_name)
        status = (record or {}).get("status")

        if status == "READY":
            return time.time() - started

        if status in ("FAILED", "ERROR"):
            raise OptimizerError(
                "The diagnostic project '{}' (id {}) failed on the platform. "
                "Open it there to see why.".format(project_name, project_id)
            )

        elapsed = time.time() - started
        if elapsed > READY_TIMEOUT_SECONDS:
            raise OptimizerError(
                "The diagnostic project '{}' (id {}) was still not ready after 5 minutes. "
                "It exists on the platform, so wait for it to finish processing and rerun "
                "the analysis, or delete it if you no longer need it.".format(
                    project_name, project_id
                )
            )

        if on_progress is not None:
            on_progress(elapsed)

        time.sleep(delay)
        delay = min(15.0, delay * 1.5)


def query_stays(
    root_url: str,
    token: str,
    project_id: str,
    date: str,
    metrics: List[str],
    groupby: List[str],
    on_progress=None,
) -> pd.DataFrame:
    """
    Read the stays of a single day, following the pagination to the end.

    A 422 answer means the project is still being processed rather than a bad
    request, which is how routers/calibration.py already treats it, so the
    call is retried with backoff.

    Returns:
        DataFrame with the raw response rows. Metric columns arrive as text
        and must be parsed with parse_metric_column.
    """
    url = "{}stays/{}/{}/{}".format(_v2_ondemand_base(root_url), project_id, date, date)
    headers = _auth_headers(token)

    rows: List[Dict[str, Any]] = []
    page_num = 1
    total = None

    while True:
        params = [("metric", m) for m in metrics]
        params += [("groupby", g) for g in groupby]
        params += [("page_num", page_num), ("page_size", STAYS_PAGE_SIZE)]

        payload = _get_with_processing_retry(url, headers, params, date, on_progress)

        data = payload.get("data") or []
        rows.extend(data)

        metadata = payload.get("metadata") or {}
        total = metadata.get("num_records", total)

        if not data:
            break
        if total is not None and len(rows) >= int(total):
            break
        if len(data) < STAYS_PAGE_SIZE:
            break

        page_num += 1

    return pd.DataFrame(rows)


def _get_with_processing_retry(
    url: str,
    headers: Dict[str, str],
    params: List[Tuple[str, Any]],
    date: str,
    on_progress=None,
) -> Dict[str, Any]:
    """GET a stays page, treating 422 as 'still processing' and retrying."""
    started = time.time()
    delay = 5.0

    while True:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=QUERY_TIMEOUT)
        except requests.exceptions.Timeout:
            raise OptimizerError(
                "The stays query for {} timed out. The platform is under load; "
                "rerun the analysis in a few minutes.".format(date)
            )
        except requests.exceptions.RequestException as exc:
            raise OptimizerError("The platform could not be reached while reading the stays: {}".format(exc))

        if response.status_code == 200:
            return response.json()

        if response.status_code == 422:
            elapsed = time.time() - started
            if elapsed > QUERY_RETRY_SECONDS:
                raise OptimizerError(
                    "The project is still being processed after 5 minutes, so the data for "
                    "{} is not queryable yet. The diagnostic project already exists; wait a "
                    "few minutes and rerun the analysis.".format(date)
                )
            if on_progress is not None:
                on_progress(elapsed)
            time.sleep(delay)
            delay = min(20.0, delay * 1.5)
            continue

        raise OptimizerError(_describe_http_error("reading the stays for {}".format(date), response))


# ==========================================
# RESPONSE PARSING
# ==========================================

def parse_metric_column(series: pd.Series) -> Tuple[np.ndarray, np.ndarray]:
    """
    Parse a stays metric column into numbers plus a suppression mask.

    The column arrives as text and small counts come back as the literal
    string "<10". Never call float() on it and never read it with a float
    dtype: the suppressed cells have to survive as a separate signal.

    Returns:
        Tuple of (values with suppressed and missing cells as 0.0,
                  boolean mask that is True where the cell was suppressed)
    """
    raw = series.astype("object")
    numeric = pd.to_numeric(raw, errors="coerce")

    text = raw.astype(str).str.strip()
    is_suppressed = numeric.isna().values & text.str.startswith("<").values

    values = numeric.fillna(0.0).astype("float64").values
    return values, is_suppressed


def build_hourly_matrix(
    frame: pd.DataFrame,
    node_ids: List[int],
    metric: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Fold an hourly stays response into a node-by-hour matrix.

    The platform returns the full grid of sectors times hours, so a missing
    combination is unusual, but both a missing row and a suppressed cell are
    filled with zero and recorded in the mask.

    Returns:
        Tuple of (values array shaped (len(node_ids), 24),
                  suppression mask with the same shape)
    """
    values = np.zeros((len(node_ids), HOURS_IN_DAY), dtype="float64")
    suppressed = np.zeros((len(node_ids), HOURS_IN_DAY), dtype=bool)
    # A missing combination counts as unobserved, same as a suppressed one.
    observed = np.zeros((len(node_ids), HOURS_IN_DAY), dtype=bool)

    if frame.empty:
        suppressed[:] = True
        return values, suppressed

    _require_columns(frame, ["sector", "arrival", metric])

    index = {int(node_id): position for position, node_id in enumerate(node_ids)}
    sectors = pd.to_numeric(frame["sector"], errors="coerce")
    hours = pd.to_numeric(frame["arrival"], errors="coerce")
    parsed, is_suppressed = parse_metric_column(frame[metric])

    for position in range(len(frame)):
        sector = sectors.iloc[position]
        hour = hours.iloc[position]
        if pd.isna(sector) or pd.isna(hour):
            continue
        row = index.get(int(sector))
        if row is None:
            continue
        column = int(hour)
        if not 0 <= column < HOURS_IN_DAY:
            continue
        values[row, column] = parsed[position]
        suppressed[row, column] = bool(is_suppressed[position])
        observed[row, column] = True

    suppressed |= ~observed
    return values, suppressed


def build_daily_totals(
    frame: pd.DataFrame,
    node_ids: List[int],
    metrics: List[str],
) -> Dict[str, np.ndarray]:
    """Fold a daily stays response into one array per metric."""
    totals = {metric: np.zeros(len(node_ids), dtype="float64") for metric in metrics}
    if frame.empty:
        return totals

    _require_columns(frame, ["sector"])
    index = {int(node_id): position for position, node_id in enumerate(node_ids)}
    sectors = pd.to_numeric(frame["sector"], errors="coerce")

    for metric in metrics:
        if metric not in frame.columns:
            continue
        parsed, _ = parse_metric_column(frame[metric])
        for position in range(len(frame)):
            sector = sectors.iloc[position]
            if pd.isna(sector):
                continue
            row = index.get(int(sector))
            if row is not None:
                totals[metric][row] += parsed[position]

    return totals


def _require_columns(frame: pd.DataFrame, columns: List[str]) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise OptimizerError(
            "The stays response is missing the column(s) {}. It returned: {}. "
            "This usually means the metric or the grouping is not available for "
            "this project.".format(", ".join(missing), ", ".join(map(str, frame.columns)))
        )


def suppression_share(mask: np.ndarray, hours: List[int]) -> float:
    """Share of suppressed cells across the hours that matter."""
    if mask.size == 0:
        return 1.0
    window = mask[:, [h for h in hours if 0 <= h < HOURS_IN_DAY]]
    if window.size == 0:
        return 1.0
    return float(window.mean())


# ==========================================
# PLATFORM PIPELINE
# ==========================================

def _node_id_from_zone_name(name: str) -> Optional[int]:
    """Recover the node id from a diagnostic zone name like buffer_97097148700."""
    text = str(name)
    if text.startswith("buffer_"):
        text = text[len("buffer_"):]
    try:
        return int(text)
    except ValueError:
        return None


def run_platform_pipeline(job_id: str) -> None:
    """
    Create the diagnostic project, read the stays and hand the raw matrices
    over to the scoring stage.

    The order is fixed: validate, price, create, wait, query. The GeoJSON sent
    to create is always the cleaned `polygons` returned by the validation,
    never the one built locally.
    """
    job = get_job(job_id)
    if job is None:
        return

    request = job["request"]
    raw = job["raw"]
    frame = raw["frame"]
    warnings = raw["warnings"]

    root_url = request["root_url"]
    token = request["token"]
    event_date = request["event_date"]
    baseline_date = request.get("baseline_date")
    primary_metric = request["primary_metric"]
    valid_hours = request["params"]["valid_hours"]

    # --- Validate the zoning ------------------------------------------------
    set_step(job_id, "validate_project", "running")
    clean_zones, rejected_names, platform_warnings = validate_zoning(
        root_url, token, raw["zones"]
    )

    rejected_ids = set()
    for name in rejected_names:
        node_id = _node_id_from_zone_name(name)
        if node_id is not None:
            rejected_ids.add(node_id)

    total_zones = len(frame)
    if rejected_ids:
        share = len(rejected_ids) / float(total_zones)
        if share > MAX_REJECTED_SHARE:
            raise OptimizerError(
                "The platform rejected {} of the {} zones ({:.0%}). Your node file is "
                "probably older than the projection grid the platform is using. Get a "
                "fresh node export for {} and run the analysis again.".format(
                    len(rejected_ids), total_zones, share, request["country_code"].upper()
                )
            )

        frame = frame[~frame["node_id"].isin(rejected_ids)].reset_index(drop=True)
        if frame.empty:
            raise OptimizerError(
                "Every zone was rejected by the platform. The node file does not match "
                "the projection grid in use. Get a fresh node export and try again."
            )

        warnings.append({
            "level": "warning",
            "code": "nodes_rejected_by_platform",
            "message": (
                "{} of {} nodes were rejected by the platform and dropped from the "
                "analysis, most likely because the local node file is slightly out of "
                "date.".format(len(rejected_ids), total_zones)
            ),
        })

    # min_num_nodes warnings are expected here: every diagnostic zone holds
    # exactly one node by construction. They are logged, not surfaced.
    if platform_warnings:
        print("[polygon-optimizer] validation warnings: {}".format(platform_warnings[:5]))

    set_step(
        job_id,
        "validate_project",
        "done",
        "{} accepted, {} rejected".format(len(frame), len(rejected_ids)),
    )

    # --- Price check --------------------------------------------------------
    set_step(job_id, "price_project", "running")
    price = price_project(root_url, token, clean_zones, event_date, event_date)
    if price:
        # `days` comes back as zero because start and end are the same day,
        # so it is left out rather than shown as a misleading "0 days".
        detail = "{} cores".format(price.get("cores", "?"))
        if price.get("total_amount") is not None:
            detail += ", {} credits".format(price["total_amount"])
        set_step(job_id, "price_project", "done", detail)
    else:
        set_step(job_id, "price_project", "skipped", "price unavailable")

    # --- Create the diagnostic project --------------------------------------
    set_step(job_id, "create_project", "running")
    project_name = raw["project_name"]
    project = create_diagnostic_project(
        root_url, token, project_name, PROJECT_DESCRIPTION, clean_zones
    )
    project_id = str(project["id"])
    set_step(job_id, "create_project", "done", "{} · {}".format(project_name, project_id))

    with _jobs_lock:
        job["raw"]["project_id"] = project_id
        job["raw"]["frame"] = frame

    # --- Wait for the project to be ready -----------------------------------
    set_step(job_id, "wait_ready", "running")
    if project.get("status") == "READY":
        set_step(job_id, "wait_ready", "done", "already ready")
    else:
        waited = wait_for_ready(
            root_url,
            token,
            project_name,
            project_id,
            on_progress=lambda elapsed: set_step(
                job_id, "wait_ready", "running", "{:.0f}s".format(elapsed)
            ),
        )
        set_step(job_id, "wait_ready", "done", "{:.0f}s".format(waited))

    node_ids = [int(v) for v in frame["node_id"].values]

    # --- Event day, daily totals --------------------------------------------
    set_step(job_id, "query_event_daily", "running")
    event_daily_frame = query_stays(
        root_url, token, project_id, event_date, DAILY_METRICS, ["sector"],
        on_progress=lambda elapsed: set_step(
            job_id, "query_event_daily", "running", "project still processing, {:.0f}s".format(elapsed)
        ),
    )
    event_daily = build_daily_totals(event_daily_frame, node_ids, DAILY_METRICS)
    set_step(job_id, "query_event_daily", "done", "{} rows".format(len(event_daily_frame)))

    # --- Event day, arrivals by hour ----------------------------------------
    set_step(job_id, "query_event_hourly", "running")
    event_hourly_frame = query_stays(
        root_url, token, project_id, event_date, [primary_metric], ["sector", "arrival"],
        on_progress=lambda elapsed: set_step(
            job_id, "query_event_hourly", "running", "project still processing, {:.0f}s".format(elapsed)
        ),
    )
    event_matrix, event_suppressed = build_hourly_matrix(
        event_hourly_frame, node_ids, primary_metric
    )

    suppressed_share = suppression_share(event_suppressed, valid_hours)
    if suppressed_share > MAX_SUPPRESSED_SHARE:
        raise OptimizerError(
            "{:.0%} of the hourly cells came back suppressed (\"<10\"), so there is no "
            "measurable audience to analyse. Either the date is wrong, the event was "
            "small, or the area sits outside the coverage. Check the event date and "
            "the polygon before rerunning. Diagnostic project: '{}' (id {}).".format(
                suppressed_share, project_name, project_id
            )
        )
    if suppressed_share > 0.5:
        warnings.append({
            "level": "warning",
            "code": "high_suppression",
            "message": (
                "{:.0%} of the hourly cells were suppressed by the platform. Node level "
                "results are noisy at this volume.".format(suppressed_share)
            ),
        })

    set_step(
        job_id,
        "query_event_hourly",
        "done",
        "{} rows, {:.0%} suppressed".format(len(event_hourly_frame), suppressed_share),
    )

    # --- Baseline day -------------------------------------------------------
    baseline_matrix = None
    baseline_suppressed = None
    baseline_daily = None

    if baseline_date:
        set_step(job_id, "query_baseline", "running")
        baseline_daily_frame = query_stays(
            root_url, token, project_id, baseline_date, DAILY_METRICS, ["sector"],
            on_progress=lambda elapsed: set_step(
                job_id, "query_baseline", "running", "project still processing, {:.0f}s".format(elapsed)
            ),
        )
        baseline_daily = build_daily_totals(baseline_daily_frame, node_ids, DAILY_METRICS)

        baseline_hourly_frame = query_stays(
            root_url, token, project_id, baseline_date, [primary_metric], ["sector", "arrival"],
        )
        baseline_matrix, baseline_suppressed = build_hourly_matrix(
            baseline_hourly_frame, node_ids, primary_metric
        )

        if float(baseline_matrix.sum()) <= 0.0:
            warnings.append({
                "level": "warning",
                "code": "empty_baseline",
                "message": (
                    "The baseline day {} returned no usable volume, so the analysis fell "
                    "back to the background profile method.".format(baseline_date)
                ),
            })
            baseline_matrix = None
            baseline_suppressed = None
            set_step(job_id, "query_baseline", "done", "no data, using background profile")
        else:
            set_step(
                job_id, "query_baseline", "done",
                "{} rows".format(len(baseline_hourly_frame)),
            )
    else:
        set_step(job_id, "query_baseline", "skipped", "not requested")

    if float(event_matrix.sum()) <= 0.0:
        raise OptimizerError(
            "The event day {} returned no volume at all for these zones. The date is "
            "probably outside the data coverage, or the area has no traffic. "
            "Diagnostic project: '{}' (id {}).".format(event_date, project_name, project_id)
        )

    with _jobs_lock:
        job["raw"].update({
            "node_ids": node_ids,
            "event_matrix": event_matrix,
            "event_suppressed": event_suppressed,
            "event_daily": event_daily,
            "baseline_matrix": baseline_matrix,
            "baseline_suppressed": baseline_suppressed,
            "baseline_daily": baseline_daily,
            "warnings": warnings,
        })

    # --- Score --------------------------------------------------------------
    set_step(job_id, "score", "running")
    score_job(job_id)


def score_job(
    job_id: str,
    window_override: Optional[Tuple[int, int]] = None,
    selection_override: Optional[List[int]] = None,
    params_override: Optional[Dict[str, Any]] = None,
    finish: bool = True,
) -> Dict[str, Any]:
    """
    Turn the raw matrices into a suggestion.

    Called at the end of the pipeline and again by /rescore, which reuses the
    stored matrices and never touches the Kido API.
    """
    job = get_job(job_id)
    if job is None:
        raise OptimizerError(
            "This analysis is no longer available. Jobs are kept for two hours and are "
            "lost when the Space hibernates. Start a new run."
        )

    raw = job["raw"]
    if "event_matrix" not in raw:
        raise OptimizerError("This analysis has no data to score yet.")

    params = dict(job["request"]["params"])
    if params_override:
        params.update(params_override)

    result = polygon_scoring.analyse(
        frame=raw["frame"],
        event_matrix=raw["event_matrix"],
        event_suppressed=raw["event_suppressed"],
        baseline_matrix=raw.get("baseline_matrix"),
        event_daily=raw.get("event_daily"),
        baseline_daily=raw.get("baseline_daily"),
        params=params,
        window_override=window_override,
        selection_override=selection_override,
    )

    result["project_id"] = raw.get("project_id")
    result["project_name"] = raw.get("project_name")
    result["event_date"] = job["request"]["event_date"]
    result["baseline_date"] = job["request"].get("baseline_date")
    result["primary_metric"] = job["request"]["primary_metric"]
    result["buffer_m"] = job["request"]["buffer_m"]
    result["input_geometry"] = mapping(raw["seed_geometry"])
    result["buffer_geometry"] = mapping(raw["buffer_geometry"])
    result["warnings"] = list(raw.get("warnings", [])) + result["warnings"]

    if finish:
        summary = result["summary"]
        set_step(
            job_id,
            "score",
            "done",
            "{} nodes selected, {:.0%} of the excess".format(
                summary["selected_count"], summary["coverage_after"]
            ),
        )
        finish_job(job_id, result)

    return result


def geometry_for_nodes(job_id: str, node_ids: List[int]) -> Dict[str, Any]:
    """
    Dissolve an arbitrary set of nodes into a polygon.

    Used by the Toggle nodes mode, which rebuilds the outline on every click.
    """
    job = get_job(job_id)
    if job is None:
        raise OptimizerError("This analysis is no longer available. Start a new run.")

    frame = job["raw"]["frame"]
    wanted = {int(v) for v in node_ids}
    selected = frame["node_id"].isin(wanted).values

    if not selected.any():
        raise OptimizerError("No nodes are selected, so there is no polygon to build.")

    params = job["request"]["params"]
    geometry, warnings = polygon_scoring.build_geometry(
        frame["x"].values,
        frame["y"].values,
        frame["lon"].values,
        frame["lat"].values,
        selected,
        float(params.get("closing_radius_m", 10.0)),
        float(params.get("simplify_tolerance_m", 5.0)),
    )
    return {"geometry": geometry, "warnings": warnings, "node_count": int(selected.sum())}


def nodes_in_geometry(job_id: str, geometry: Dict[str, Any]) -> List[int]:
    """
    Return the candidate nodes contained in a hand-drawn geometry.

    Used by the Draw manually mode, so the user immediately sees which nodes
    the edit brought in and which it left out.
    """
    job = get_job(job_id)
    if job is None:
        raise OptimizerError("This analysis is no longer available. Start a new run.")

    try:
        drawn = shape(geometry.get("geometry", geometry))
    except Exception as exc:
        raise OptimizerError("The drawn geometry could not be read ({}).".format(exc))

    frame = job["raw"]["frame"]
    points = gpd.GeoSeries(
        gpd.points_from_xy(frame["lon"], frame["lat"]), crs="EPSG:4326"
    )
    inside = points.within(drawn).values
    return [int(v) for v in frame["node_id"].values[inside]]
