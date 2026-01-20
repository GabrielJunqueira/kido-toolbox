# Python 3.9 Slim image
FROM python:3.9-slim

# Install system dependencies for GeoPandas/Shapely
RUN apt-get update && apt-get install -y \
    gdal-bin \
    libgdal-dev \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first (for caching)
COPY backend/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ /app/backend/

# Copy frontend code
COPY frontend/ /app/frontend/

# Create directory for data (will be populated via COPY or Volume)
# Note: For Hugging Face Spaces, you should commit the data files via Git LFS
# to backend/data/aoi/ inside the repo.
RUN mkdir -p /app/backend/data/aoi

# Set environment variable for data path
# This overrides the local path in local settings
ENV GEO_DATA_PATH=/app/backend/data/aoi

# Expose port 7860 (Hugging Face default) or 8000
EXPOSE 7860

# Command to run the application
# Using 0.0.0.0 for external access
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
