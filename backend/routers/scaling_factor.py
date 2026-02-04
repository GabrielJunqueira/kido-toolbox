"""
Scaling Factor Adjustment API Router
Provides endpoints for authenticating with Kido API and adjusting polygon scaling factors.
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, List
import requests

router = APIRouter(
    prefix="/api/scaling-factor",
    tags=["scaling-factor"]
)

# =============================
# MODELS
# =============================

class LoginRequest(BaseModel):
    email: str
    password: str
    country_code: str

class LoginResponse(BaseModel):
    token: str
    root_url: str
    brand: str

class PolygonInfo(BaseModel):
    polygon_id: str
    uuid: str
    name: str

class PolygonsResponse(BaseModel):
    polygons: List[PolygonInfo]

class AdjustmentRequest(BaseModel):
    project_id: str
    polygon_uuid: str
    valid_from: str  # YYYY-MM-DD
    valid_to: str    # YYYY-MM-DD
    scaling_factor: float

class AdjustmentResponse(BaseModel):
    success: bool
    message: str

# =============================
# HELPERS
# =============================

def get_brand_from_country(country_code: str) -> str:
    """Determine the brand based on country code."""
    country_code = country_code.lower()
    
    if country_code in ["es", "mx", "ch", "co", "pe"]:
        return "kido"
    elif country_code == "pt":
        return "altice"
    elif country_code == "pa":
        return "cw"
    elif country_code == "qa":
        return "ooredoo"
    else:
        return "claro"

def build_root_url(brand: str, country_code: str) -> str:
    """Build the API root URL from brand and country code."""
    return f"https://api.{brand}-{country_code.lower()}.kidodynamics.com/v1/"

# =============================
# ENDPOINTS
# =============================

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Authenticate with the Kido API and return the access token.
    """
    brand = get_brand_from_country(request.country_code)
    root_url = build_root_url(brand, request.country_code)
    
    try:
        response = requests.post(
            f"{root_url}users/login",
            headers={
                'accept': 'application/json',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data=f'grant_type=password&username={request.email}&password={request.password}',
            timeout=30
        )
        
        if response.status_code == 200:
            token = response.json().get("access_token")
            return LoginResponse(
                token=token,
                root_url=root_url,
                brand=brand
            )
        elif response.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Login failed: {response.text}"
            )
            
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Connection timeout")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Connection error: {str(e)}")


@router.get("/polygons/{project_id}", response_model=PolygonsResponse)
async def get_polygons(
    project_id: str,
    authorization: str = Header(...),
    root_url: str = Header(..., alias="x-root-url")
):
    """
    Fetch all polygons for a given project from the Kido API.
    """
    try:
        response = requests.get(
            f"{root_url}projects/{project_id}/polygons",
            headers={
                "Authorization": authorization,
                "accept": "application/json"
            },
            params={"alt_engine": "false"},
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if not data:
                return PolygonsResponse(polygons=[])
            
            polygons = []
            for item in data:
                polygon_id = item.get('polygon_id')
                uuid = item.get('id')
                name = item.get('name', '')
                
                if polygon_id and uuid:
                    polygons.append(PolygonInfo(
                        polygon_id=polygon_id,
                        uuid=uuid,
                        name=name
                    ))
            
            return PolygonsResponse(polygons=polygons)
            
        elif response.status_code == 404:
            raise HTTPException(status_code=404, detail="Project not found")
        elif response.status_code == 401:
            raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to fetch polygons: {response.text}"
            )
            
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Connection timeout")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Connection error: {str(e)}")


@router.post("/adjust", response_model=AdjustmentResponse)
async def adjust_scaling_factor(
    request: AdjustmentRequest,
    authorization: str = Header(...),
    root_url: str = Header(..., alias="x-root-url")
):
    """
    Apply a scaling factor adjustment to a polygon.
    Uses the V2 API endpoint for polygon adjustments.
    """
    # Convert V1 URL to V2
    base_v2 = root_url.replace("/v1/", "/v2/")
    url = f"{base_v2}polygons_adjustments/{request.project_id}/{request.polygon_uuid}"
    
    payload = {
        "valid_from": request.valid_from,
        "valid_to": request.valid_to,
        "scaling_factor": request.scaling_factor
    }
    
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": authorization,
                "accept": "application/json",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=30
        )
        
        if response.status_code == 200:
            return AdjustmentResponse(
                success=True,
                message="Scaling factor adjustment applied successfully!"
            )
        elif response.status_code == 422:
            raise HTTPException(
                status_code=422,
                detail="Validation error. Please check the date format (YYYY-MM-DD) and scaling factor value."
            )
        elif response.status_code == 401:
            raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
        elif response.status_code == 404:
            raise HTTPException(status_code=404, detail="Project or polygon not found.")
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to apply adjustment: {response.text}"
            )
            
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Connection timeout")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Connection error: {str(e)}")


# Model for current adjustment info
class CurrentAdjustment(BaseModel):
    project_id: str
    polygon_id: str
    polygon_user_id: str
    valid_from: str
    valid_to: str
    scaling_factor: float
    created_by: str
    committed_at: str

class CurrentAdjustmentsResponse(BaseModel):
    adjustments: List[CurrentAdjustment]


@router.get("/current-adjustments/{project_id}")
async def get_current_adjustments(
    project_id: str,
    authorization: str = Header(...),
    root_url: str = Header(..., alias="x-root-url")
):
    """
    Fetch current scaling factor adjustments for a project.
    Uses the V2 API endpoint.
    """
    base_v2 = root_url.replace("/v1/", "/v2/")
    url = f"{base_v2}polygons_adjustments"
    
    try:
        response = requests.get(
            url,
            headers={
                "Authorization": authorization,
                "accept": "application/json"
            },
            params={
                "project_id": project_id,
                "alt_engine": "false"
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            
            if not data:
                return {"adjustments": []}
            
            adjustments = []
            for item in data:
                adjustments.append({
                    "project_id": item.get("project_id", ""),
                    "polygon_id": item.get("polygon_id", ""),
                    "polygon_user_id": item.get("polygon_user_id", ""),
                    "valid_from": item.get("valid_from", ""),
                    "valid_to": item.get("valid_to", ""),
                    "scaling_factor": item.get("scaling_factor", 0),
                    "created_by": item.get("created_by", ""),
                    "committed_at": item.get("committed_at", "")
                })
            
            return {"adjustments": adjustments}
            
        elif response.status_code == 401:
            raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to fetch adjustments: {response.text}"
            )
            
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="Connection timeout")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=503, detail=f"Connection error: {str(e)}")
