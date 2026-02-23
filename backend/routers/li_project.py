"""
LI Project Creator Router
API endpoints for creating Location Intelligence projects for establishments.
"""

import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from services.li_project import (
    process_nodes_csv,
    search_by_name,
    get_establishment_polygon,
    filter_nodes_in_buffer,
    count_nodes_in_polygons,
    create_buffer_circle_geojson,
    build_li_project_geojson,
    create_polygon_buffers,
)

router = APIRouter(prefix="/api/li-project", tags=["li-project"])

# In-memory node store: { key: [[lat, lon], ...] }
_node_store = {}


# ==========================================
# Request/Response Models
# ==========================================

class SearchRequest(BaseModel):
    query: str
    country_code: str = ""
    limit: int = 10


class EstablishmentPolygonRequest(BaseModel):
    lat: float
    lon: float
    custom_name: str = ""
    radius: int = 50


class FilterNodesRequest(BaseModel):
    node_key: str  # Reference to stored nodes
    center_lat: float
    center_lon: float
    radius_m: float = 1000


class EstablishmentFeature(BaseModel):
    properties: dict
    geometry: dict
    type: str = "Feature"


class GenerateProjectRequest(BaseModel):
    establishments: List[dict]  # List of GeoJSON Feature dicts
    country_code: str
    region_code: str
    city_name: str


class CountNodesRequest(BaseModel):
    node_key: str
    polygons: List[dict]  # List of GeoJSON Feature dicts


class BufferPolygonRequest(BaseModel):
    geometry: dict  # GeoJSON geometry (Polygon)
    distances: List[float]  # List of buffer distances in meters


# ==========================================
# Endpoints
# ==========================================

@router.post("/upload-nodes")
async def upload_nodes(file: UploadFile = File(...)):
    """
    Upload a CSV file with node data.
    Stores nodes server-side and returns a key + count.
    """
    import time
    try:
        t0 = time.time()
        contents = await file.read()
        t1 = time.time()
        print(f"[upload-nodes] File read: {t1-t0:.2f}s ({len(contents)} bytes)")

        nodes, count, extra = process_nodes_csv(contents)
        t2 = time.time()
        print(f"[upload-nodes] CSV parsed: {t2-t1:.2f}s ({count} nodes)")

        # Store nodes server-side with a unique key
        node_key = str(uuid.uuid4())
        _node_store[node_key] = nodes
        t3 = time.time()
        print(f"[upload-nodes] Stored: {t3-t2:.2f}s | Total: {t3-t0:.2f}s")

        return {
            "success": True,
            "node_key": node_key,
            "count": count,
            "extra": extra,
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Error processing CSV: {str(e)}"}


@router.post("/search-establishment")
async def search_establishment(request: SearchRequest):
    """
    Search for establishments by name using Nominatim.
    """
    try:
        results = search_by_name(
            request.query,
            country_code=request.country_code,
            limit=request.limit,
        )
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": f"Search error: {str(e)}"}


@router.post("/get-establishment-polygon")
async def get_polygon(request: EstablishmentPolygonRequest):
    """
    Get the building polygon at given coordinates from Overpass API.
    """
    try:
        feature = get_establishment_polygon(
            request.lat,
            request.lon,
            custom_name=request.custom_name or None,
            radius=request.radius,
        )
        if feature:
            return {"success": True, "feature": feature}
        else:
            return {
                "success": False,
                "error": "No polygon found at these coordinates. "
                         "Try increasing the search radius or using different coordinates.",
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/filter-nodes")
async def filter_nodes(request: FilterNodesRequest):
    """
    Filter nodes that are within a buffer radius of a center point.
    Nodes are referenced by node_key from a previous upload.
    Also returns the buffer circle as GeoJSON for visualization.
    """
    try:
        nodes = _node_store.get(request.node_key)
        if nodes is None:
            return {"success": False, "error": "Node data not found. Please re-upload the CSV."}

        filtered = filter_nodes_in_buffer(
            nodes,
            request.center_lat,
            request.center_lon,
            request.radius_m,
        )
        buffer_geojson = create_buffer_circle_geojson(
            request.center_lat,
            request.center_lon,
            request.radius_m,
        )
        return {
            "success": True,
            "filtered_nodes": filtered,
            "filtered_count": len(filtered),
            "buffer_geojson": buffer_geojson,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/generate-project")
async def generate_project(request: GenerateProjectRequest):
    """
    Generate the final LI project GeoJSON.
    """
    try:
        geojson, filename = build_li_project_geojson(
            establishments=request.establishments,
            country_code=request.country_code.upper(),
            region_code=request.region_code,
            city_name=request.city_name,
        )

        feature_count = len(geojson.get('features', []))

        return {
            "success": True,
            "geojson": geojson,
            "filename": filename,
            "feature_count": feature_count,
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {str(e)}"}


@router.post("/count-nodes-in-polygons")
async def count_nodes_endpoint(request: CountNodesRequest):
    """
    Count nodes inside each polygon using vectorized operations.
    Much faster than doing point-in-polygon in the browser with JS.
    """
    try:
        nodes = _node_store.get(request.node_key)
        if nodes is None:
            return {"success": False, "error": "Node data not found. Please re-upload the CSV."}
        
        import time
        t0 = time.time()
        counts = count_nodes_in_polygons(nodes, request.polygons)
        t1 = time.time()
        print(f"[count-nodes-in-polygons] {len(request.polygons)} polygons, {len(nodes)} nodes -> {t1-t0:.2f}s")
        
        return {
            "success": True,
            "counts": counts,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"Error counting nodes: {str(e)}"}


@router.post("/buffer-polygon")
async def buffer_polygon(request: BufferPolygonRequest):
    """
    Create buffer polygons around a given polygon geometry.
    Returns buffered polygon geometries for each distance.
    """
    try:
        buffers = create_polygon_buffers(
            geometry=request.geometry,
            distances=request.distances,
        )
        return {
            "success": True,
            "buffers": buffers,
        }
    except Exception as e:
        return {"success": False, "error": f"Error creating buffer polygons: {str(e)}"}
