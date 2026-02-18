"""
Advanced Calibration Tool Router
Handles API proxying to Kido Dynamics and local reference data storage.
"""

from fastapi import APIRouter, HTTPException, Request, Response, Body
from typing import Dict, List, Any, Optional
import requests
import json
from services.calibration_storage import storage_service

router = APIRouter(
    prefix="/api/calibration",
    tags=["calibration"]
)

# -----------------------------------------------------------------------------
# PROXY ENDPOINTS
# -----------------------------------------------------------------------------

@router.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def kido_api_proxy(path: str, request: Request):
    """
    Proxy requests to Kido Dynamics API.
    Expects 'x-kido-token' and 'x-kido-root-url' headers, or standard Authorization.
    """
    # Extract configuration from headers
    token = request.headers.get("x-kido-token")
    root_url = request.headers.get("x-kido-root-url")
    
    # Fallback/Normalization
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
        
    if not root_url:
        # Default to standard URL if not provided (though frontend should provide it)
        # Assuming Switzerland/Global default for now if missing, but it should be passed
        root_url = "https://api.kido-ch.kidodynamics.com/v1/" 
    
    # Ensure root_url ends with slash and doesn't get duplicated
    if not root_url.endswith("/"):
        root_url += "/"
        
    # Construct target URL
    # path comes in as "projects" or "projects/123"
    # root_url is "https://api.../v1/"
    target_url = f"{root_url}{path}"
    
    # query params
    params = dict(request.query_params)
    
    # body
    body = None
    if request.method not in ["GET", "HEAD"]:
        try:
            body = await request.json()
        except Exception:
            body = await request.body()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        # Make the request to Kido API
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=params,
            json=body if isinstance(body, dict) else None,
            data=body if not isinstance(body, dict) else None,
            timeout=60
        )
        
        # Forward response
        # exclude specific headers that might cause issues
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers_to_return = {
            k: v for k, v in resp.headers.items() 
            if k.lower() not in excluded_headers
        }
        
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=headers_to_return,
            media_type=resp.headers.get("content-type", "application/json")
        )
        
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Upstream API error: {str(e)}")


# -----------------------------------------------------------------------------
# STORAGE ENDPOINTS (SQLite)
# -----------------------------------------------------------------------------

@router.post("/storage/refdata")
async def store_reference_data(data: Dict[str, Any] = Body(...)):
    """
    Store reference data key-value pair.
    Body: { "key": "...", "value": ... }
    """
    key = data.get("key")
    value = data.get("value")
    
    if not key or value is None:
        raise HTTPException(status_code=400, detail="Key and value are required")
        
    try:
        storage_service.store_ref_data(key, value)
        return {"success": True, "key": key}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/storage/refdata/project/{project_id}")
async def get_project_reference_data(project_id: str):
    """Get all reference data for a specific project."""
    try:
        entries = storage_service.get_project_ref_data(project_id)
        return {"entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/storage/refdata/{key}")
async def get_reference_data_item(key: str):
    """Get a single reference data item by key."""
    try:
        value = storage_service.get_ref_data(key)
        if value is None:
            raise HTTPException(status_code=404, detail="Key not found")
        return value
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/storage/refdata/{key}")
async def delete_reference_data_item(key: str):
    """Delete a reference data item by key."""
    try:
        deleted = storage_service.delete_ref_data(key)
        if not deleted:
            raise HTTPException(status_code=404, detail="Key not found")
        return {"success": True, "deleted": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
