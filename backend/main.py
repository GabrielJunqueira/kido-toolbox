"""
Kido Support Toolbox - Backend Server
FastAPI application serving the web interface and API endpoints
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from routers import aoi, anonymizer, editor, scaling_factor, li_project, report

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


@app.get("/")
async def root():
    """Serve the main index page."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Kido Support Toolbox API", "docs": "/docs"}



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
