import os
from typing import Optional

import requests as http_requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from routers import aoi, anonymizer, editor, scaling_factor, li_project, report
from services.auth import login_kido

# Initialize FastAPI app
app = FastAPI(
    title="Kido Support Toolbox",
    description="Web-based tools for the Kido support team",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(aoi.router)
app.include_router(anonymizer.router)
app.include_router(editor.router)
app.include_router(scaling_factor.router)
app.include_router(li_project.router)
app.include_router(report.router)

# Get paths for static files
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BACKEND_DIR), "frontend")

# Mount static directories
if os.path.exists(os.path.join(FRONTEND_DIR, "css")):
    app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")

if os.path.exists(os.path.join(FRONTEND_DIR, "js")):
    app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")

if os.path.exists(os.path.join(FRONTEND_DIR, "pages")):
    app.mount("/pages", StaticFiles(directory=os.path.join(FRONTEND_DIR, "pages")), name="pages")


# ==========================================
# Shared API Models
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
# Shared API Endpoints
# ==========================================

@app.get("/")
async def root():
    """Serve the main index page."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Kido Support Toolbox API", "docs": "/docs"}


@app.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate with Kido Dynamics API (shared across all tools)."""
    result = login_kido(request.username, request.password, request.country_code)
    return LoginResponse(**result)


@app.post("/api/create-project", response_model=CreateProjectResponse)
async def create_project(request: CreateProjectRequest):
    """Validate and create project in Kido cloud (shared across all tools)."""
    base_url = request.root_url.replace("/v2/", "/v1/").replace("/v2", "/v1")
    if not base_url.endswith("/"):
        base_url += "/"

    headers = {
        'accept': 'application/json',
        'Authorization': f"Bearer {request.token}"
    }

    try:
        # Validate GeoJSON
        validate_url = base_url + "projects/validate?mode=hard"
        val_response = http_requests.post(
            validate_url, json=request.geojson, headers=headers, timeout=600
        )

        if val_response.status_code != 200:
            return CreateProjectResponse(
                success=False, error=f"Validation failed: {val_response.text}"
            )

        val_data = val_response.json()
        if val_data.get("valid") is False:
            return CreateProjectResponse(
                success=False,
                error=f"Invalid geometry: {val_data.get('reason', 'Unknown error')}"
            )

        clean_geojson = val_data.get("polygons", request.geojson)

        # Create Project
        create_url = base_url + "projects/create"
        payload = {
            "name": request.name,
            "description": request.description,
            "geojson": clean_geojson,
            "is_geoinsight": True,
            "with_traffic": False
        }

        create_response = http_requests.post(
            create_url, json=payload, headers=headers, timeout=600
        )

        if create_response.status_code == 200:
            project_id = create_response.json().get("id")
            return CreateProjectResponse(success=True, project_id=str(project_id))
        else:
            return CreateProjectResponse(
                success=False, error=f"Creation failed: {create_response.text}"
            )

    except http_requests.exceptions.Timeout:
        return CreateProjectResponse(
            success=False,
            error="Request timeout. Kido API may be slow. Check platform later."
        )
    except Exception as e:
        return CreateProjectResponse(success=False, error=f"Unexpected error: {str(e)}")



@app.get("/aoi")
async def aoi_page():
    """Serve the AOI project generator page."""
    page_path = os.path.join(FRONTEND_DIR, "pages", "aoi.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return {"error": "Page not found"}


@app.get("/anonymizer")
async def anonymizer_page():
    """Serve the dashboard anonymizer tool page."""
    page_path = os.path.join(FRONTEND_DIR, "pages", "anonymizer.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return {"error": "Page not found"}


@app.get("/scaling-factor")
async def scaling_factor_page():
    """Serve the polygon scaling factor adjustment tool page."""
    page_path = os.path.join(FRONTEND_DIR, "pages", "scaling_factor.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return {"error": "Page not found"}


@app.get("/editor")
async def editor_page():
    """Serve the interactive map editor page."""
    page_path = os.path.join(FRONTEND_DIR, "pages", "editor.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return {"error": "Page not found"}


@app.get("/li-project")
async def li_project_page():
    """Serve the LI Project Creator page."""
    page_path = os.path.join(FRONTEND_DIR, "pages", "li_project.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return {"error": "Page not found"}


@app.get("/report")
async def report_page():
    """Serve the AOI Report Generator page."""
    page_path = os.path.join(FRONTEND_DIR, "pages", "report.html")
    if os.path.exists(page_path):
        return FileResponse(page_path)
    return {"error": "Page not found"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
