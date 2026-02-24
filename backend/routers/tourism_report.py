"""
AOI Tourism Report Router
API endpoints for generating tourism visitor analysis reports.
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.auth import login_kido
from services.tourism_report import generate_tourism_report

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


class GenerateTourismReportRequest(BaseModel):
    token: str
    root_url: str
    project_id: str
    aoi_id: str
    months: List[str]  # ["2025-09", "2025-10", ...]


# ==========================================
# Endpoints
# ==========================================

@router.post("/login", response_model=TourismLoginResponse)
async def tourism_report_login(request: TourismLoginRequest):
    """Authenticate with Kido Dynamics API."""
    result = login_kido(request.username, request.password, request.country_code)
    return TourismLoginResponse(**result)


@router.post("/generate")
async def generate_report(request: GenerateTourismReportRequest):
    """
    Generate a tourism report with 12 charts.
    Returns JSON with base64-encoded chart images and summary statistics.
    """
    if not request.months:
        raise HTTPException(status_code=400, detail="At least one month must be selected")

    if not request.project_id.strip():
        raise HTTPException(status_code=400, detail="Project ID is required")

    if not request.aoi_id.strip():
        raise HTTPException(status_code=400, detail="AOI ID is required")

    try:
        summary = generate_tourism_report(
            token=request.token,
            root_url=request.root_url,
            project_id=request.project_id.strip(),
            aoi_id=request.aoi_id.strip(),
            months=sorted(request.months)
        )

        return JSONResponse(content={
            "success": True,
            "summary": summary
        })

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tourism report generation failed: {str(e)}")
