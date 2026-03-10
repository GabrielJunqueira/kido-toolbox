import logging
from typing import List
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from services.retail_report import generate_retail_report_stream, get_generated_file

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
    and finally emits a success event with a download file_id.
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
            months=request.months,
        ),
        media_type="text/event-stream",
    )


@router.get("/download/{file_id}")
async def download_report(file_id: str):
    """Download a previously generated HTML report by its file_id."""
    filepath = get_generated_file(file_id)
    if not filepath:
        raise HTTPException(status_code=404, detail="Report not found or expired.")

    return FileResponse(
        filepath,
        media_type="text/html; charset=utf-8",
        filename=f"dashboard_{file_id[:8]}.html",
    )
