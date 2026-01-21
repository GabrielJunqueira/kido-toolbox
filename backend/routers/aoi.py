"""
AOI Project Generator Router
API endpoints for creating Tourism (AOI) projects
"""

import json
from typing import List, Optional

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from services.aoi import (
    get_available_countries,
    get_regions_for_country,
    get_municipalities_for_region,
    generate_aoi_project,
    COUNTRY_CONFIG
)
from services.auth import login_kido

router = APIRouter(prefix="/api/aoi", tags=["aoi"])


# ==========================================
# Request/Response Models
# ==========================================

class CountryInfo(BaseModel):
    code: str
    name: str


class RegionInfo(BaseModel):
    code: str
    name: str


class LoginRequest(BaseModel):
    username: str
    password: str
    country_code: str


class LoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    root_url: Optional[str] = None
    brand: Optional[str] = None
    error: Optional[str] = None


class GenerateProjectRequest(BaseModel):
    country_code: str
    region_code: str
    city_name: str


class GenerateProjectResponse(BaseModel):
    success: bool
    geojson: Optional[dict] = None
    filename: Optional[str] = None
    feature_count: Optional[int] = None
    error: Optional[str] = None


class CreateProjectRequest(BaseModel):
    token: str
    root_url: str
    name: str
    description: str
    geojson: dict


class CreateProjectResponse(BaseModel):
    success: bool
    project_id: Optional[str] = None
    error: Optional[str] = None


# ==========================================
# Endpoints
# ==========================================

@router.get("/countries", response_model=List[CountryInfo])
async def list_countries():
    """Get list of available countries."""
    return get_available_countries()


@router.get("/regions/{country_code}", response_model=List[RegionInfo])
async def list_regions(country_code: str):
    """Get list of regions/states for a country."""
    try:
        regions = get_regions_for_country(country_code.upper())
        return regions
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/municipalities/{country_code}/{region_code}")
async def list_municipalities(country_code: str, region_code: str):
    """Get list of municipalities for a region."""
    try:
        municipalities = get_municipalities_for_region(
            country_code.upper(), 
            region_code
        )
        return {"municipalities": municipalities}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/generate", response_model=GenerateProjectResponse)
async def generate_project(request: GenerateProjectRequest):
    """Generate AOI project GeoJSON."""
    try:
        geojson, filename = generate_aoi_project(
            request.country_code.upper(),
            request.region_code,
            request.city_name
        )
        
        feature_count = len(geojson.get('features', []))
        
        return GenerateProjectResponse(
            success=True,
            geojson=geojson,
            filename=filename,
            feature_count=feature_count
        )
    except ValueError as e:
        return GenerateProjectResponse(success=False, error=str(e))
    except FileNotFoundError as e:
        return GenerateProjectResponse(success=False, error=str(e))
    except Exception as e:
        return GenerateProjectResponse(success=False, error=f"Unexpected error: {str(e)}")


@router.post("/download")
async def download_geojson(request: GenerateProjectRequest):
    """Generate AOI project and return as downloadable GeoJSON file."""
    try:
        geojson, filename = generate_aoi_project(
            request.country_code.upper(),
            request.region_code,
            request.city_name
        )
        
        geojson_str = json.dumps(geojson, ensure_ascii=False, indent=2)
        
        return Response(
            content=geojson_str,
            media_type="application/geo+json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/create-project", response_model=CreateProjectResponse)
async def create_project(request: CreateProjectRequest):
    """Validate and create project in Kido cloud."""
    
    # Ensure V1 URL for project endpoints
    base_url = request.root_url.replace("/v2/", "/v1/").replace("/v2", "/v1")
    if not base_url.endswith("/"):
        base_url += "/"
    
    headers = {
        'accept': 'application/json',
        'Authorization': f"Bearer {request.token}"
    }
    
    try:
        # Step 1: Validate GeoJSON
        validate_url = base_url + "projects/validate?mode=hard"
        print(f"Validating GeoJSON at: {validate_url}")
        
        val_response = requests.post(
            validate_url,
            json=request.geojson,
            headers=headers,
            timeout=600  # 10 minutes for large country files
        )
        
        if val_response.status_code != 200:
            return CreateProjectResponse(
                success=False,
                error=f"Validation failed ({val_response.status_code}): {val_response.text}"
            )
        
        val_data = val_response.json()
        if val_data.get("valid") is False:
            return CreateProjectResponse(
                success=False,
                error=f"Invalid geometry: {val_data.get('reason', 'Unknown error')}"
            )
        
        # Get cleaned GeoJSON from validation
        clean_geojson = val_data.get("polygons", request.geojson)
        
        # Step 2: Create Project
        create_url = base_url + "projects/create"
        print(f"Creating project at: {create_url}")
        
        payload = {
            "name": request.name,
            "description": request.description,
            "geojson": clean_geojson,
            "with_traffic": False  # AOI projects typically don't need traffic
        }
        
        create_response = requests.post(
            create_url,
            json=payload,
            headers=headers,
            timeout=600  # 10 minutes for large project creation
        )
        
        if create_response.status_code == 200:
            project_id = create_response.json().get("id")
            return CreateProjectResponse(success=True, project_id=str(project_id))
        else:
            return CreateProjectResponse(
                success=False,
                error=f"Creation failed ({create_response.status_code}): {create_response.text}"
            )
            
    except requests.exceptions.Timeout as e:
        return CreateProjectResponse(
            success=False,
            error=f"Request timeout (10 mins exceeded). Kido API is slow for large countries. Check platform. Details: {str(e)}"
        )
    except requests.exceptions.ConnectionError as e:
        return CreateProjectResponse(
            success=False,
            error=f"Connection error - unable to reach the Kido API. Details: {str(e)}"
        )
    except Exception as e:
        return CreateProjectResponse(success=False, error=f"Unexpected error: {str(e)}")


@router.get("/debug-files")
async def debug_files():
    """List files in the data directory recursively with sizes."""
    import os
    from services.aoi import GEO_DATA_PATH
    
    result = {}
    try:
        if not os.path.exists(GEO_DATA_PATH):
            return {"error": f"Path does not exist: {GEO_DATA_PATH}"}

        for root, dirs, files in os.walk(GEO_DATA_PATH):
            rel_path = os.path.relpath(root, GEO_DATA_PATH)
            if rel_path == ".":
                rel_path = ""
            
            file_list = []
            for f in files:
                full_path = os.path.join(root, f)
                size = os.path.getsize(full_path)
                file_list.append({"name": f, "size": size})
            
            result[rel_path] = file_list
            
        return {"root": GEO_DATA_PATH, "files": result}
    except Exception as e:
        return {"error": str(e)}
