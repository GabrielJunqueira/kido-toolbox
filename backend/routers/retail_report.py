import logging
import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from services.retail_report import generate_retail_report_stream

router = APIRouter(prefix="/api/retail-report", tags=["retail-report"])

logger = logging.getLogger(__name__)

class GenerateRetailReportRequest(BaseModel):
    token: str
    root_url: str
    project_id: str
    months: List[str]

@router.post("/generate")
async def generate_retail_report(request: GenerateRetailReportRequest):
    """
    Generate an HTML interactive dashboard for all polygons in a project.
    Returns a stream of Server-Sent Events (SSE) indicating progress,
    and finally returns the base64 encoded HTML file containing all data.
    """
    if not request.token or not request.root_url:
        raise HTTPException(status_code=401, detail="Missing authentication credentials")
    
    if not request.project_id:
        raise HTTPException(status_code=400, detail="Missing project ID")
        
    if not request.months:
        raise HTTPException(status_code=400, detail="No months selected")

    return StreamingResponse(
        generate_retail_report_stream(
            token=request.token,
            root_url=request.root_url,
            project_id=request.project_id,
            months=request.months
        ),
        media_type="text/event-stream"
    )
