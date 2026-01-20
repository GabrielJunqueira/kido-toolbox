"""
Geographic Processing Service
Handles buffer creation and country identification
"""

import json
import os
from typing import List, Dict, Any, Optional, Tuple
import geopandas as gpd
import shapely.ops
from shapely.geometry import Point, shape, mapping
from pyproj import CRS, Transformer

# Load countries reference file
COUNTRIES_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'countries_kido.geojson')
countries_gdf: Optional[gpd.GeoDataFrame] = None

def load_countries():
    """Load the countries reference file."""
    global countries_gdf
    if countries_gdf is None:
        try:
            if os.path.exists(COUNTRIES_FILE):
                countries_gdf = gpd.read_file(COUNTRIES_FILE)
            else:
                print(f"Warning: Countries file not found at {COUNTRIES_FILE}")
        except Exception as e:
            print(f"Error loading countries file: {e}")
    return countries_gdf


def get_utm_crs(lat: float, lon: float) -> CRS:
    """
    Calculate the appropriate UTM CRS for a given lat/lon.
    
    Args:
        lat: Latitude
        lon: Longitude
        
    Returns:
        PyProj CRS object for the appropriate UTM zone
    """
    utm_zone = int((lon + 180) // 6) + 1
    utm_epsg = f"326{utm_zone:02d}" if lat >= 0 else f"327{utm_zone:02d}"
    return CRS.from_epsg(int(utm_epsg))


def create_circular_buffers(
    lat: float, 
    lon: float, 
    radii: List[int]
) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Create circular buffers around a point with specified radii.
    
    Args:
        lat: Latitude of center point
        lon: Longitude of center point
        radii: List of radii in meters
        
    Returns:
        Tuple of (GeoJSON dict, country_name or None)
    """
    # Create point
    point = Point(lon, lat)
    
    # Set up UTM projection for accurate meter-based buffers
    utm_crs = get_utm_crs(lat, lon)
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_wgs = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)
    
    # Transform point to UTM
    x, y = to_utm.transform(lon, lat)
    utm_point = Point(x, y)
    
    # Create buffer features
    features = []
    
    for r in sorted(radii):
        # Create buffer in UTM (meters)
        buffer_utm = utm_point.buffer(r)
        
        # Transform back to WGS84
        buffer_latlon = shapely.ops.transform(
            lambda x, y: to_wgs.transform(x, y), 
            buffer_utm
        )
        
        feature = {
            "type": "Feature",
            "properties": {
                "id": f"AOI-1-{r}",
                "name": f"buffer-{r}",
                "poly_type": "core"
            },
            "geometry": mapping(buffer_latlon)
        }
        features.append(feature)
    
    # Try to identify country
    country_name = None
    countries = load_countries()
    
    if countries is not None and not countries.empty:
        try:
            country_match = countries[countries.geometry.contains(point)]
            if not country_match.empty:
                country_name = country_match.iloc[0].get('name', 'Unknown')
                
                # Add country as periphery polygon
                country_feature = {
                    "type": "Feature",
                    "properties": {
                        "id": "AOI-0",
                        "name": country_name,
                        "poly_type": "periphery"
                    },
                    "geometry": mapping(country_match.iloc[0].geometry)
                }
                features.insert(0, country_feature)
        except Exception as e:
            print(f"Error identifying country: {e}")
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    return geojson, country_name


def get_buffer_only_geojson(
    lat: float, 
    lon: float, 
    radii: List[int]
) -> Dict[str, Any]:
    """
    Create only buffer GeoJSON without country (for preview).
    
    Args:
        lat: Latitude of center point
        lon: Longitude of center point
        radii: List of radii in meters
        
    Returns:
        GeoJSON dict with buffer features only
    """
    point = Point(lon, lat)
    utm_crs = get_utm_crs(lat, lon)
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_wgs = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)
    
    x, y = to_utm.transform(lon, lat)
    utm_point = Point(x, y)
    
    features = []
    
    for r in sorted(radii):
        buffer_utm = utm_point.buffer(r)
        buffer_latlon = shapely.ops.transform(
            lambda x, y: to_wgs.transform(x, y), 
            buffer_utm
        )
        
        feature = {
            "type": "Feature",
            "properties": {
                "id": f"AOI-1-{r}",
                "name": f"buffer-{r}",
                "radius": r,
                "poly_type": "core"
            },
            "geometry": mapping(buffer_latlon)
        }
        features.append(feature)
    
    # Add center point for reference
    center_feature = {
        "type": "Feature",
        "properties": {
            "id": "center",
            "name": "Center Point",
            "type": "center"
        },
        "geometry": mapping(point)
    }
    features.append(center_feature)
    
    return {
        "type": "FeatureCollection",
        "features": features
    }
