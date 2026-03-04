"""
AOI Generator via API — Router
Endpoints for the Project Generator via API (Beta) tool.
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from services.aoi_generator import (
    get_available_countries,
    get_states,
    get_cities,
    generate_aoi_project,
)

router = APIRouter(prefix="/api/aoi-generator", tags=["aoi-generator"])


# ── Request / Response Models ──────────────────────────────────

class GenerateRequest(BaseModel):
    country_name: str
    state_id: str
    state_name: str
    city_id: str
    city_name: str


class GenerateResponse(BaseModel):
    success: bool
    geojson: Optional[dict] = None
    filename: Optional[str] = None
    feature_count: Optional[int] = None
    provinces: Optional[int] = None
    municipalities: Optional[int] = None
    core: Optional[int] = None
    error: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────

@router.get("/countries")
async def list_countries():
    """List available countries."""
    return get_available_countries()


@router.get("/states/{iso}")
async def list_states(iso: str):
    """List states/provinces for a country."""
    states = get_states(iso.upper())
    if not states:
        raise HTTPException(404, f"No states found for {iso}")
    return states


@router.get("/cities/{iso}/{state_name}")
async def list_cities(iso: str, state_name: str):
    """List cities for a state."""
    cities = get_cities(iso.upper(), state_name)
    return cities


@router.post("/generate", response_model=GenerateResponse)
async def generate_project(request: GenerateRequest):
    """Generate AOI project GeoJSON via Overpass API."""
    try:
        geojson, filename = generate_aoi_project(
            country_name=request.country_name,
            state_id=request.state_id,
            state_name=request.state_name,
            city_id=request.city_id,
            city_name=request.city_name,
        )

        # Count feature types
        provinces = sum(1 for f in geojson["features"] if f["properties"]["id"].startswith("PRO-"))
        muns = sum(1 for f in geojson["features"] if f["properties"]["id"].startswith("MUN-"))
        core = sum(1 for f in geojson["features"] if f["properties"]["id"].startswith("AOI-"))

        return GenerateResponse(
            success=True,
            geojson=geojson,
            filename=filename,
            feature_count=len(geojson["features"]),
            provinces=provinces,
            municipalities=muns,
            core=core,
        )
    except Exception as e:
        return GenerateResponse(success=False, error=str(e))


@router.post("/download")
async def download_geojson(request: GenerateRequest):
    """Generate and return as downloadable GeoJSON file."""
    try:
        geojson, filename = generate_aoi_project(
            country_name=request.country_name,
            state_id=request.state_id,
            state_name=request.state_name,
            city_id=request.city_id,
            city_name=request.city_name,
        )
        content = json.dumps(geojson, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/geo+json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(500, str(e))
