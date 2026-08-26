"""
Event Polygon Optimizer Router
API endpoints for measuring event attendance per projection node and
proposing an optimised analysis polygon.
"""

import csv
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from shapely.geometry import mapping

from services import nodes as node_service
from services.nodes import NodeFileError
from services.polygon_optimizer import (
    NODE_COUNT_HARD_LIMIT,
    NODE_COUNT_SOFT_LIMIT,
    OptimizerError,
    build_diagnostic_geojson,
    collect_nodes,
    create_job,
    extract_input_polygon,
    geometry_for_nodes,
    job_status,
    nodes_in_geometry,
    run_job,
    score_job,
)

router = APIRouter(prefix="/api/polygon-optimizer", tags=["polygon-optimizer"])


# ==========================================
# Request Models
# ==========================================

class OptimizerParams(BaseModel):
    """Everything exposed in the Advanced panel."""

    # Hours kept for the analysis. 0-2 are dominated by people already in the
    # area at midnight and 23 is structurally depressed by the day cutoff.
    valid_hours: List[int] = list(range(3, 23))

    # Composite score weights. Without a baseline day the router reweights
    # towards curve shape, since excess gets less trustworthy.
    w_excess: float = 0.40
    w_similarity: float = 0.30
    w_peak: float = 0.15
    w_proximity: float = 0.15

    # Proximity decay length, in meters.
    proximity_length_m: float = 400.0

    # Spatial regularisation and selection.
    fill_neighbour_threshold: int = 6
    min_component_share: float = 0.05
    target_node_count: int = 10

    # Final geometry cleanup, in meters.
    closing_radius_m: float = 10.0
    simplify_tolerance_m: float = 5.0


class PreviewRequest(BaseModel):
    country_code: str
    geojson: Dict[str, Any]
    buffer_m: float = 500.0


class RunRequest(BaseModel):
    token: str
    root_url: str
    country_code: str
    geojson: Dict[str, Any]
    event_date: str
    baseline_date: Optional[str] = None
    buffer_m: float = 500.0
    primary_metric: str = "total_wanderers"
    params: Optional[OptimizerParams] = None


# ==========================================
# Node file endpoints
# ==========================================

@router.post("/upload-nodes")
async def upload_nodes(file: UploadFile = File(...), country_code: str = Form(...)):
    """
    Upload the projection node file for a country.

    Accepts a zip holding one CSV, a gzipped CSV or a plain CSV. The file is
    normalised and cached as parquet under /tmp, which the Space clears when
    it hibernates.
    """
    try:
        contents = await file.read()
        entry = node_service.load_nodes(contents, country_code, file.filename or "")
        return {
            "success": True,
            "country_code": entry["country_code"],
            "rows": entry["rows"],
            "bbox": entry["bbox"],
            "container": entry["container"],
        }
    except NodeFileError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": "The node file could not be processed: {}".format(exc)}


@router.get("/nodes-status/{country_code}")
async def nodes_status(country_code: str):
    """Report whether a node file is already cached for a country."""
    return {"success": True, **node_service.describe(country_code)}


@router.delete("/nodes/{country_code}")
async def drop_nodes(country_code: str):
    """Forget the cached node file so the user can upload a different one."""
    node_service.clear(country_code)
    return {"success": True}


# ==========================================
# Analysis endpoints
# ==========================================

@router.post("/preview")
async def preview(request: PreviewRequest):
    """
    Collect the candidate nodes without touching the Kido platform.

    This runs before the diagnostic project is created, so the user can see how
    many zones the project will hold and adjust the radius first.
    """
    try:
        geom, warnings = extract_input_polygon(request.geojson)
        frame, buffered, collect_warnings = collect_nodes(
            request.country_code, geom, request.buffer_m
        )
        warnings.extend(collect_warnings)

        return {
            "success": True,
            "node_count": int(len(frame)),
            "seed_count": int(frame["in_seed"].sum()),
            "outer_ring_count": int(frame["in_outer_ring"].sum()),
            "soft_limit": NODE_COUNT_SOFT_LIMIT,
            "hard_limit": NODE_COUNT_HARD_LIMIT,
            "buffer_geometry": mapping(buffered),
            "nodes": [
                {
                    "node_id": int(row.node_id),
                    "lon": float(row.lon),
                    "lat": float(row.lat),
                    "in_seed": bool(row.in_seed),
                }
                for row in frame.itertuples(index=False)
            ],
            "warnings": warnings,
        }
    except OptimizerError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": "The area could not be analysed: {}".format(exc)}


@router.post("/zones-preview")
async def zones_preview(request: PreviewRequest):
    """Return the diagnostic zone GeoJSON for inspection before creating it."""
    try:
        geom, _ = extract_input_polygon(request.geojson)
        frame, _, _ = collect_nodes(request.country_code, geom, request.buffer_m)
        return {"success": True, "geojson": build_diagnostic_geojson(frame)}
    except OptimizerError as exc:
        return {"success": False, "error": str(exc)}


@router.post("/run")
async def run(request: RunRequest, background_tasks: BackgroundTasks):
    """
    Start the analysis job and return its id immediately.

    The access token is kept only inside the in-memory job record and is never
    written to disk, logged or echoed back in the status payload.
    """
    params = (request.params or OptimizerParams()).dict()
    payload = request.dict()
    payload["params"] = params

    job_id = create_job(payload)
    background_tasks.add_task(run_job, job_id)
    return {"success": True, "job_id": job_id}


@router.get("/status/{job_id}")
async def status(job_id: str):
    """Return the current to-do list state of a job."""
    payload = job_status(job_id)
    if payload is None:
        return {
            "success": False,
            "error": "This analysis is no longer available. Jobs are kept for two "
                     "hours and are lost when the Space hibernates. Start a new run.",
        }
    return {"success": True, **payload}


# ==========================================
# Review endpoints
# ==========================================

class RescoreRequest(BaseModel):
    job_id: str
    event_window: Optional[List[int]] = None
    params: Optional[OptimizerParams] = None


class GeometryRequest(BaseModel):
    job_id: str
    node_ids: List[int]


class NodesInPolygonRequest(BaseModel):
    job_id: str
    geometry: Dict[str, Any]


class ReportRequest(BaseModel):
    job_id: str
    node_ids: Optional[List[int]] = None


@router.post("/rescore")
async def rescore(request: RescoreRequest):
    """
    Score the stored data again with a different event window or parameters.

    Never calls the Kido API: the raw matrices live on the job.
    """
    try:
        window = None
        if request.event_window and len(request.event_window) == 2:
            window = (int(request.event_window[0]), int(request.event_window[1]))

        result = score_job(
            request.job_id,
            window_override=window,
            params_override=request.params.dict() if request.params else None,
            finish=False,
        )
        return {"success": True, "result": result}
    except OptimizerError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": "The rescore failed: {}".format(exc)}


@router.post("/geometry")
async def geometry(request: GeometryRequest):
    """Dissolve a hand-picked set of nodes into a polygon."""
    try:
        return {"success": True, **geometry_for_nodes(request.job_id, request.node_ids)}
    except OptimizerError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": "The polygon could not be rebuilt: {}".format(exc)}


@router.post("/nodes-in-polygon")
async def nodes_in_polygon(request: NodesInPolygonRequest):
    """Return the candidate nodes contained in a hand-drawn geometry."""
    try:
        return {"success": True, "node_ids": nodes_in_geometry(request.job_id, request.geometry)}
    except OptimizerError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:
        return {"success": False, "error": "The drawn area could not be read: {}".format(exc)}


REPORT_COLUMNS = [
    "node_id", "x", "y", "lon", "lat", "in_seed", "in_outer_ring", "dist_m",
    "selected", "reason", "rank", "score",
    "excess", "ratio", "similarity", "peak_hour", "peak_align", "proximity",
    "coverage_ratio", "low_confidence", "component_flagged",
    "total_event", "total_baseline",
    "total_wanderers", "total_visitors", "total_passerbys",
]


@router.post("/report-csv")
async def report_csv(request: ReportRequest):
    """
    Build the audit CSV: one row per candidate node with every computed metric,
    plus the hourly curves, so the analysis can be checked outside the tool.
    """
    try:
        selection = set(request.node_ids or [])
        result = score_job(
            request.job_id,
            selection_override=sorted(selection) if selection else None,
            finish=False,
        )
    except OptimizerError as exc:
        return {"success": False, "error": str(exc)}

    buffer = io.StringIO()
    hour_columns = ["event_h{:02d}".format(h) for h in range(24)]
    baseline_columns = ["baseline_h{:02d}".format(h) for h in range(24)]
    writer = csv.writer(buffer)
    writer.writerow(REPORT_COLUMNS + hour_columns + baseline_columns)

    for node in result["nodes"]:
        daily = node.get("total_event_daily") or {}
        writer.writerow([
            node["node_id"], node["x"], node["y"], node["lon"], node["lat"],
            node["in_seed"], node["in_outer_ring"], node["dist_m"],
            node["selected"], node["reason"], node["rank"], node["score"],
            node["excess"], node["ratio"], node["similarity"], node["peak_hour"],
            node["peak_align"], node["proximity"], node["coverage_ratio"],
            node["low_confidence"], node["component_flagged"],
            node["total_event"], node["total_baseline"],
            daily.get("total_wanderers"), daily.get("total_visitors"),
            daily.get("total_passerbys"),
        ] + node["hourly_event"] + (node["hourly_baseline"] or [""] * 24))

    filename = "{}_audit.csv".format(result.get("project_name") or "polygon_optimizer")
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="{}"'.format(filename)},
    )
