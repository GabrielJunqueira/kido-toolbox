from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import geopandas as gpd
import pandas as pd
import json
import io
import os
import shutil
import tempfile
from typing import Optional, List

router = APIRouter(
    prefix="/api/editor",
    tags=["editor"]
)

def save_upload_file_tmp(upload_file: UploadFile) -> str:
    try:
        suffix = os.path.splitext(upload_file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(upload_file.file, tmp)
            return tmp.name
    finally:
        upload_file.file.close()

@router.post("/process")
async def process_map_data(
    polygons: UploadFile = File(...),
    nodes: UploadFile = File(None),
    antennas: UploadFile = File(None)
):
    tmp_poly = None
    tmp_nodes = None
    tmp_antennas = None

    try:
        # 1. Load Polygons
        tmp_poly = save_upload_file_tmp(polygons)
        try:
            polygons_gdf = gpd.read_file(tmp_poly)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Polygons file: {str(e)}")

        # Ensure CRS is EPSG:4326
        if polygons_gdf.crs is not None and polygons_gdf.crs.to_string() != "EPSG:4326":
            polygons_gdf = polygons_gdf.to_crs("EPSG:4326")
        
        # Add ID if missing
        if "polygon_id" not in polygons_gdf.columns:
            polygons_gdf["polygon_id"] = range(len(polygons_gdf))
        
        polygons_gdf["polygon_id"] = polygons_gdf["polygon_id"].astype(str)

        # Filter out checkpoint polygons
        # Check standard columns like 'poly_types' or 'type'
        if "poly_types" in polygons_gdf.columns:
            polygons_gdf = polygons_gdf[polygons_gdf["poly_types"].str.lower() != "checkpoint"]
        elif "type" in polygons_gdf.columns:
            polygons_gdf = polygons_gdf[polygons_gdf["type"].str.lower() != "checkpoint"]
        
        # Reset index after filtering
        polygons_gdf = polygons_gdf.reset_index(drop=True)


        # 2. Process Nodes (if provided)
        nodes_data = [] # List of [lat, lon]
        if nodes and nodes.size > 0:
            tmp_nodes = save_upload_file_tmp(nodes)
            
            if os.path.getsize(tmp_nodes) == 0:
                polygons_gdf["node_count"] = 0
            else:
                try:
                    # Read CSV
                    # Check separator (default , or ;)
                    try:
                        df_nodes = pd.read_csv(tmp_nodes)
                    except:
                        df_nodes = pd.read_csv(tmp_nodes, sep=';')
                    
                    if df_nodes.empty:
                        polygons_gdf["node_count"] = 0
                    else:
                        # Standarize columns
                        df_nodes.columns = [c.lower() for c in df_nodes.columns]
                        
                        if 'latitude' in df_nodes.columns and 'longitude' in df_nodes.columns:
                            lat_col, lon_col = 'latitude', 'longitude'
                        elif 'lat' in df_nodes.columns and 'lon' in df_nodes.columns:
                            lat_col, lon_col = 'lat', 'lon'
                        else:
                            raise ValueError("Nodes CSV must have latitude/longitude columns")

                        nodes_gdf = gpd.GeoDataFrame(
                            df_nodes,
                            geometry=gpd.points_from_xy(df_nodes[lon_col], df_nodes[lat_col]),
                            crs="EPSG:4326"
                        )

                        # Spatial Join
                        # Optimizing: Only join with polygon_id and geometry
                        nodes_joined = gpd.sjoin(
                            nodes_gdf,
                            polygons_gdf[["polygon_id", "geometry"]],
                            how="inner",
                            predicate="within"
                        )

                        # Count
                        node_counts = nodes_joined.groupby("polygon_id").size().reset_index(name="node_count")
                        
                        # Check if suffix issue might happen if column exists
                        if "node_count" in polygons_gdf.columns:
                            polygons_gdf = polygons_gdf.drop(columns=["node_count"])
                            
                        polygons_gdf = polygons_gdf.merge(node_counts, on="polygon_id", how="left")
                        polygons_gdf["node_count"] = polygons_gdf["node_count"].fillna(0).astype(int)

                        # Extract coordinates for frontend (only [lat, lon] to save bandwidth)
                        # Filter: Only return nodes that are INSIDE the polygons
                        nodes_filtered = nodes_joined.copy()
                        nodes_data = list(zip(nodes_filtered.geometry.y, nodes_filtered.geometry.x))

                except Exception as e:
                    print(f"Nodes processing error: {e}")
                    # Continue without nodes if error? No, warn user
                    raise HTTPException(status_code=400, detail=f"Error processing Nodes: {str(e)}")
        else:
            polygons_gdf["node_count"] = 0

        # 3. Process Antennas (if provided)
        antennas_data = []
        if antennas and antennas.size > 0: # Check if object is valid
            tmp_antennas = save_upload_file_tmp(antennas)
            
            # Check if file is empty
            if os.path.getsize(tmp_antennas) == 0:
                polygons_gdf["antenna_count"] = 0
            else:
                try:
                    try:
                        df_ant = pd.read_csv(tmp_antennas)
                    except:
                        df_ant = pd.read_csv(tmp_antennas, sep=';')
                    
                    if df_ant.empty:
                         polygons_gdf["antenna_count"] = 0
                    else:
                        df_ant.columns = [c.lower() for c in df_ant.columns]
                        
                        if 'latitude' in df_ant.columns and 'longitude' in df_ant.columns:
                            lat_col, lon_col = 'latitude', 'longitude'
                        elif 'lat' in df_ant.columns and 'lon' in df_ant.columns:
                            lat_col, lon_col = 'lat', 'lon'
                        else:
                            raise ValueError("Antennas CSV must have latitude/longitude columns")

                        antennas_gdf = gpd.GeoDataFrame(
                            df_ant,
                            geometry=gpd.points_from_xy(df_ant[lon_col], df_ant[lat_col]),
                            crs="EPSG:4326"
                        )

                        # Spatial Join
                        antennas_joined = gpd.sjoin(
                            antennas_gdf,
                            polygons_gdf[["polygon_id", "geometry"]],
                            how="inner",
                            predicate="within"
                        )

                        # Count
                        ant_counts = antennas_joined.groupby("polygon_id").size().reset_index(name="antenna_count")
                        
                        if "antenna_count" in polygons_gdf.columns:
                            polygons_gdf = polygons_gdf.drop(columns=["antenna_count"])
                            
                        polygons_gdf = polygons_gdf.merge(ant_counts, on="polygon_id", how="left")
                        polygons_gdf["antenna_count"] = polygons_gdf["antenna_count"].fillna(0).astype(int)

                        # Filter: Only return antennas that are INSIDE the polygons
                        antennas_filtered = antennas_joined.copy()
                        antennas_data = list(zip(antennas_filtered.geometry.y, antennas_filtered.geometry.x))
                except Exception as e:
                     # Re-raise nicely
                     raise ValueError(str(e))
        else:
             polygons_gdf["antenna_count"] = 0

        # 4. Final Cleanup
        # Calculate total
        polygons_gdf["total_count"] = polygons_gdf["node_count"] + polygons_gdf["antenna_count"]

        # Collect polygon property columns (all non-geometry columns, excluding computed stats)
        exclude_cols = {"node_count", "antenna_count", "total_count", "geometry"}
        polygon_columns = [c for c in polygons_gdf.columns if c not in exclude_cols]

        # Convert to GeoJSON
        geojson_str = polygons_gdf.to_json()
        
        return JSONResponse(content={
            "success": True,
            "polygons": json.loads(geojson_str),
            "nodes": nodes_data,           # List of [lat, lon]
            "antennas": antennas_data,     # List of [lat, lon]
            "polygon_columns": polygon_columns  # Available identifier columns
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup temp files
        for f in [tmp_poly, tmp_nodes, tmp_antennas]:
            if f and os.path.exists(f):
                os.remove(f)
