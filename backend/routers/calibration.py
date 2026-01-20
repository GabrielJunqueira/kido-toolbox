"""
Mall Calibration Tool Router
API endpoints for buffer creation, project management, and data extraction
"""

import io
import json
from datetime import datetime
from typing import List, Optional

import pandas as pd
import requests
from fastapi import APIRouter, HTTPException
from pandas.tseries.offsets import MonthEnd
from pydantic import BaseModel, Field

from services.auth import login_kido, get_brand_and_url
from services.geo import create_circular_buffers, get_buffer_only_geojson

router = APIRouter(prefix="/api", tags=["calibration"])


# ==========================================
# Request/Response Models
# ==========================================

class LoginRequest(BaseModel):
    username: str
    password: str
    country_code: str


class LoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    root_url: Optional[str] = None
    brand: Optional[str] = None
    country_code: Optional[str] = None
    error: Optional[str] = None


class BufferPreviewRequest(BaseModel):
    lat: float
    lon: float
    radii: List[int] = Field(default=[200, 300, 400])


class CreateBuffersRequest(BaseModel):
    lat: float
    lon: float
    radii: List[int] = Field(default=[200, 300, 400])


class CreateBuffersResponse(BaseModel):
    success: bool
    geojson: Optional[dict] = None
    country_name: Optional[str] = None
    radii: List[int] = []
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


class ExtractDataRequest(BaseModel):
    token: str
    root_url: str
    project_id: str
    radii: List[int]
    start_month: str  # YYYY-MM
    end_month: str    # YYYY-MM


class VisitorData(BaseModel):
    month: str
    aoi_id: str
    radius: int
    visits: Optional[int] = None
    status: str = "success"


class ExtractDataResponse(BaseModel):
    success: bool
    data: List[VisitorData] = []
    error: Optional[str] = None


# ==========================================
# Endpoints
# ==========================================

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate with Kido Dynamics API."""
    result = login_kido(request.username, request.password, request.country_code)
    return LoginResponse(**result)


@router.post("/buffer-preview")
async def buffer_preview(request: BufferPreviewRequest):
    """Get buffer GeoJSON for map preview (without country)."""
    try:
        geojson = get_buffer_only_geojson(request.lat, request.lon, request.radii)
        return {"success": True, "geojson": geojson}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/create-buffers", response_model=CreateBuffersResponse)
async def create_buffers(request: CreateBuffersRequest):
    """Create circular buffers with country identification."""
    try:
        geojson, country_name = create_circular_buffers(
            request.lat, 
            request.lon, 
            request.radii
        )
        return CreateBuffersResponse(
            success=True,
            geojson=geojson,
            country_name=country_name,
            radii=request.radii
        )
    except Exception as e:
        return CreateBuffersResponse(success=False, error=str(e))


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
            timeout=180  # 3 minutes for validation
        )
        
        if val_response.status_code != 200:
            return CreateProjectResponse(
                success=False, 
                error=f"Validation failed: {val_response.text}"
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
        payload = {
            "name": request.name,
            "description": request.description,
            "geojson": clean_geojson,
            "with_traffic": True
        }
        
        print(f"Creating project at: {create_url}")
        create_response = requests.post(
            create_url,
            json=payload,
            headers=headers,
            timeout=300  # 5 minutes for project creation
        )
        
        if create_response.status_code == 200:
            project_id = create_response.json().get("id")
            return CreateProjectResponse(success=True, project_id=str(project_id))
        else:
            return CreateProjectResponse(
                success=False,
                error=f"Creation failed: {create_response.text}"
            )
            
    except requests.exceptions.Timeout as e:
        return CreateProjectResponse(
            success=False, 
            error=f"Request timeout - the Kido API is taking too long to respond. This can happen with large geometries. Please try again or contact support. Details: {str(e)}"
        )
    except requests.exceptions.ConnectionError as e:
        return CreateProjectResponse(
            success=False,
            error=f"Connection error - unable to reach the Kido API. Please check your network connection. Details: {str(e)}"
        )
    except Exception as e:
        return CreateProjectResponse(success=False, error=f"Unexpected error: {str(e)}")


@router.post("/extract-data", response_model=ExtractDataResponse)
async def extract_data(request: ExtractDataRequest):
    """Extract visitor data for each radius and month."""
    
    # Use V2 URL for data endpoints
    base_url = request.root_url.replace("/v1/", "/v2/").replace("/v1", "/v2")
    if not base_url.endswith("/"):
        base_url += "/"
    
    headers = {'Authorization': f"Bearer {request.token}"}
    
    all_data = []
    
    try:
        # Generate date range
        dates = pd.date_range(
            start=f"{request.start_month}-01",
            end=f"{request.end_month}-01",
            freq='MS'
        )
        
        for date in dates:
            d_start = date.strftime('%Y-%m-%d')
            d_end = (date + MonthEnd(1)).strftime('%Y-%m-%d')
            month_str = date.strftime('%Y-%m')
            
            for r in request.radii:
                aoi_id = f"AOI-1-{r}"
                
                url = (
                    f"{base_url}areas_of_interest/{request.project_id}/"
                    f"dashboard/visitors/{aoi_id}/{d_start}/{d_end}/csv/unique_visits"
                )
                
                try:
                    res = requests.get(
                        url,
                        headers=headers,
                        params={"metric": "wanderers"},
                        timeout=90  # 90 seconds for data extraction
                    )
                    
                    if res.status_code == 200:
                        # Handle JSON-wrapped CSV
                        try:
                            csv_txt = json.loads(res.text)
                        except:
                            csv_txt = res.text
                        
                        df = pd.read_csv(io.StringIO(csv_txt))
                        
                        if not df.empty:
                            visits = int(df.iloc[0, 0])
                            all_data.append(VisitorData(
                                month=month_str,
                                aoi_id=aoi_id,
                                radius=r,
                                visits=visits,
                                status="success"
                            ))
                        else:
                            all_data.append(VisitorData(
                                month=month_str,
                                aoi_id=aoi_id,
                                radius=r,
                                visits=0,
                                status="empty"
                            ))
                    elif res.status_code == 422:
                        all_data.append(VisitorData(
                            month=month_str,
                            aoi_id=aoi_id,
                            radius=r,
                            status="processing"
                        ))
                    else:
                        all_data.append(VisitorData(
                            month=month_str,
                            aoi_id=aoi_id,
                            radius=r,
                            status=f"error_{res.status_code}"
                        ))
                        
                except Exception as e:
                    all_data.append(VisitorData(
                        month=month_str,
                        aoi_id=aoi_id,
                        radius=r,
                        status=f"error: {str(e)}"
                    ))
        
        return ExtractDataResponse(success=True, data=all_data)
        
    except Exception as e:
        return ExtractDataResponse(success=False, error=str(e))
