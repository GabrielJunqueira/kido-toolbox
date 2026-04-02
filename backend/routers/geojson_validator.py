"""
GeoJSON Validator — Router
Endpoint for the Project Validator tool.
"""

from dataclasses import asdict
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.geojson_validator import validate_geojson

router = APIRouter(prefix="/api/geojson-validator", tags=["geojson-validator"])


class ValidateRequest(BaseModel):
    geojson: Dict[str, Any]


@router.post("/validate")
async def validate(request: ValidateRequest):
    """
    Validate a GeoJSON against the platform's polygon rules.
    Returns a structured report with errors, warnings, and applied fixes.
    """
    try:
        result = validate_geojson(request.geojson)
        return {
            "valid": result.valid,
            "issues": [asdict(i) for i in result.issues],
            "fixed_geojson": result.fixed_geojson,
            "summary": result.summary,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na validação: {str(e)}")
