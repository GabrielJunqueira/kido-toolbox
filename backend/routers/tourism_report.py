"""
AOI Tourism Report Router
API endpoints for generating tourism visitor analysis reports.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.auth import login_kido
from services.tourism_report import fetch_single_month, generate_charts_from_data

router = APIRouter(prefix="/api/tourism-report", tags=["tourism-report"])


# ==========================================
# Request/Response Models
# ==========================================

class TourismLoginRequest(BaseModel):
    username: str
    password: str
    country_code: str


class TourismLoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    root_url: Optional[str] = None
    brand: Optional[str] = None
    error: Optional[str] = None


class FetchMonthRequest(BaseModel):
    token: str
    root_url: str
    project_id: str
    aoi_id: str
    month: str  # "2025-09"


class GenerateChartsRequest(BaseModel):
    project_id: str
    aoi_id: str
    csv_data: List[str]       # List of CSV strings (one per month)
    months_count: int


# ==========================================
# Endpoints
# ==========================================

@router.post("/login", response_model=TourismLoginResponse)
async def tourism_report_login(request: TourismLoginRequest):
    """Authenticate with Kido Dynamics API."""
    result = login_kido(request.username, request.password, request.country_code)
    return TourismLoginResponse(**result)


@router.post("/fetch-month")
async def fetch_month(request: FetchMonthRequest):
    """
    Fetch tourism data for a single month with retry logic.
    Returns CSV data string + status message for live feedback.
    """
    if not request.project_id.strip():
        raise HTTPException(status_code=400, detail="Project ID is required")
    if not request.aoi_id.strip():
        raise HTTPException(status_code=400, detail="AOI ID is required")

    try:
        result = fetch_single_month(
            token=request.token,
            root_url=request.root_url,
            project_id=request.project_id.strip(),
            aoi_id=request.aoi_id.strip(),
            month=request.month.strip()
        )
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(content={
            "month": request.month,
            "success": False,
            "data": None,
            "message": f"❌ {request.month} — error: {str(e)}",
            "was_slow": False
        })


@router.post("/generate-charts")
async def generate_charts(request: GenerateChartsRequest):
    """
    Generate 12 tourism charts from pre-fetched CSV data.
    """
    if not request.csv_data:
        raise HTTPException(status_code=400, detail="No data provided")

    try:
        summary = generate_charts_from_data(
            csv_strings=request.csv_data,
            project_id=request.project_id.strip(),
            aoi_id=request.aoi_id.strip(),
            months_count=request.months_count
        )

        return JSONResponse(content={
            "success": True,
            "summary": summary
        })

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chart generation failed: {str(e)}")
