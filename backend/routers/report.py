"""
AOI Report Generator Router
API endpoints for generating PDF visitor analysis reports.
"""

import io
import base64
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.auth import login_kido
from services.report import generate_pdf_report

router = APIRouter(prefix="/api/report", tags=["report"])


# ==========================================
# Request/Response Models
# ==========================================

class ReportLoginRequest(BaseModel):
    username: str
    password: str
    country_code: str


class ReportLoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    root_url: Optional[str] = None
    brand: Optional[str] = None
    error: Optional[str] = None


class GenerateReportRequest(BaseModel):
    token: str
    root_url: str
    project_id: str
    aoi_id: str
    months: List[str]  # ["2025-09", "2025-10", ...]


# ==========================================
# Endpoints
# ==========================================

@router.post("/login", response_model=ReportLoginResponse)
async def report_login(request: ReportLoginRequest):
    """Authenticate with Kido Dynamics API."""
    result = login_kido(request.username, request.password, request.country_code)
    return ReportLoginResponse(**result)


@router.post("/generate")
async def generate_report(request: GenerateReportRequest):
    """
    Generate a PDF report with visitor analysis.
    Returns JSON with base64-encoded PDF, chart images, and summary statistics.
    """
    if not request.months:
        raise HTTPException(status_code=400, detail="At least one month must be selected")

    if not request.project_id.strip():
        raise HTTPException(status_code=400, detail="Project ID is required")

    if not request.aoi_id.strip():
        raise HTTPException(status_code=400, detail="AOI ID is required")

    try:
        pdf_bytes, summary = generate_pdf_report(
            token=request.token,
            root_url=request.root_url,
            project_id=request.project_id.strip(),
            aoi_id=request.aoi_id.strip(),
            months=sorted(request.months)
        )

        # Create filename
        sorted_months = sorted(request.months)
        months_tag = f"{sorted_months[0]}_to_{sorted_months[-1]}" if len(sorted_months) > 1 else sorted_months[0]
        filename = f"report_{request.aoi_id}_{months_tag}.pdf"

        # Encode PDF as base64
        pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')

        return JSONResponse(content={
            "success": True,
            "filename": filename,
            "pdf_base64": pdf_b64,
            "summary": summary
        })

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {str(e)}")
