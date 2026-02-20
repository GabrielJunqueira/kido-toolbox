"""
Location Intelligence Project Creator Service
Handles node processing, establishment search (Nominatim/Overpass),
buffer filtering, and AOI project assembly for LI projects.
"""

import io
import time
import json
from typing import List, Dict, Any, Optional, Tuple

import pandas as pd
import numpy as np
import geopandas as gpd
import requests
from shapely.geometry import Point, Polygon, shape, mapping
from shapely.ops import transform
import pyproj

from services.aoi import generate_aoi_project


# ==========================================
# NODE PROCESSING
# ==========================================

def process_nodes_csv(file_bytes: bytes) -> Tuple[np.ndarray, int, dict]:
    """
    Read a CSV file with node data, detect lat/lon columns,
    and return a numpy array of [[lat, lon], ...].
    
    Returns:
        Tuple of (numpy array of shape (N, 2), total count, extra_data dict)
    """
    # Try comma first, then semicolon
    try:
        df = pd.read_csv(io.BytesIO(file_bytes))
    except Exception:
        df = pd.read_csv(io.BytesIO(file_bytes), sep=';')
    
    # Standardize column names
    df.columns = [c.strip().lower() for c in df.columns]
    
    # Detect lat/lon columns
    if 'latitude' in df.columns and 'longitude' in df.columns:
        lat_col, lon_col = 'latitude', 'longitude'
    elif 'lat' in df.columns and 'lon' in df.columns:
        lat_col, lon_col = 'lat', 'lon'
    else:
        raise ValueError(
            "CSV must contain 'latitude'/'longitude' or 'lat'/'lon' columns. "
            f"Found columns: {list(df.columns)}"
        )
    
    # Drop rows with missing coordinates
    df = df.dropna(subset=[lat_col, lon_col])
    
    # Convert to float
    df[lat_col] = pd.to_numeric(df[lat_col], errors='coerce')
    df[lon_col] = pd.to_numeric(df[lon_col], errors='coerce')
    df = df.dropna(subset=[lat_col, lon_col])
    
    # Keep as numpy array (fast — no Python list conversion)
    nodes = df[[lat_col, lon_col]].values  # shape (N, 2), dtype float64
    
    # Extra data summary (don't convert full columns to lists)
    extra_data = {}
    if 'id' in df.columns:
        extra_data['has_ids'] = True
    if 'cusec' in df.columns:
        extra_data['has_cusecs'] = True
    
    return nodes, len(nodes), extra_data


# ==========================================
# ESTABLISHMENT SEARCH (NOMINATIM)
# ==========================================

def search_by_name(query: str, country_code: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    """
    Search for establishments by name using the Nominatim API.
    Respects rate limits (1 req/sec).
    """
    nominatim_url = "https://nominatim.openstreetmap.org/search"
    
    params = {
        'q': query,
        'format': 'json',
        'limit': limit,
        'addressdetails': 1,
        'extratags': 1,
    }
    
    # If country code provided, filter by country
    if country_code:
        params['countrycodes'] = country_code.lower()
    
    headers = {
        'User-Agent': 'KidoToolbox/1.0 (support-tool)'
    }
    
    try:
        response = requests.get(
            nominatim_url,
            params=params,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        results = response.json()
        
        options = []
        for i, result in enumerate(results):
            options.append({
                'index': i + 1,
                'name': result.get('display_name', 'Unknown'),
                'lat': float(result['lat']),
                'lon': float(result['lon']),
                'osm_id': result.get('osm_id'),
                'osm_type': result.get('osm_type'),
                'type': result.get('type', 'Unknown'),
            })
        
        return options
    
    except Exception as e:
        print(f"Nominatim search error: {e}")
        raise


# ==========================================
# ESTABLISHMENT POLYGON (OVERPASS)
# ==========================================

def get_establishment_polygon(
    lat: float,
    lon: float,
    custom_name: str = None,
    radius: int = 50,
    max_retries: int = 3
) -> Optional[Dict[str, Any]]:
    """
    Fetch the building/amenity polygon at given coordinates from Overpass API.
    Returns a GeoJSON Feature dict, or None if nothing found.
    """
    overpass_url = "http://overpass-api.de/api/interpreter"
    
    overpass_query = f"""
    [out:json][timeout:25];
    (
      nwr(around:{radius},{lat},{lon})["building"];
      nwr(around:{radius},{lat},{lon})["amenity"];
      nwr(around:{radius},{lat},{lon})["shop"];
    );
    out geom;
    """
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
            
            response = requests.get(
                overpass_url,
                params={'data': overpass_query},
                timeout=45
            )
            response.raise_for_status()
            data = response.json()
            
            if not data.get('elements'):
                return None
            
            point = Point(lon, lat)
            best_feature = None
            best_area = 0
            
            for element in data['elements']:
                osm_id = element.get('id')
                name = element.get('tags', {}).get('name', 'Unnamed')
                geometry = None
                
                # Node → small buffer
                if element['type'] == 'node':
                    if 'lat' in element and 'lon' in element:
                        node_point = Point(element['lon'], element['lat'])
                        geometry = node_point.buffer(0.00005)
                
                # Way → polygon
                elif element['type'] == 'way' and 'geometry' in element:
                    coords = [(n['lon'], n['lat']) for n in element['geometry']]
                    if len(coords) >= 3:
                        if coords[0] != coords[-1]:
                            coords.append(coords[0])
                        try:
                            geometry = Polygon(coords)
                        except Exception:
                            continue
                
                # Relation → multipolygon
                elif element['type'] == 'relation' and 'members' in element:
                    outer_coords = []
                    for member in element['members']:
                        if member.get('role') == 'outer' and 'geometry' in member:
                            outer_coords.extend(
                                [(n['lon'], n['lat']) for n in member['geometry']]
                            )
                    if len(outer_coords) >= 3:
                        if outer_coords[0] != outer_coords[-1]:
                            outer_coords.append(outer_coords[0])
                        try:
                            geometry = Polygon(outer_coords)
                        except Exception:
                            continue
                
                if geometry and geometry.is_valid:
                    dist = point.distance(geometry)
                    if geometry.contains(point) or dist < 0.001:
                        area = geometry.area
                        if area > best_area:
                            best_area = area
                            best_feature = {
                                'type': 'Feature',
                                'properties': {
                                    'id': str(osm_id),
                                    'name': custom_name or name,
                                    'poly_type': 'core',
                                },
                                'geometry': mapping(geometry),
                            }
            
            return best_feature
        
        except requests.exceptions.Timeout:
            if attempt == max_retries - 1:
                raise Exception("Overpass API timeout after all retries")
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 504:
                if attempt == max_retries - 1:
                    raise Exception("Overpass API gateway timeout")
            else:
                raise
        except Exception:
            if attempt == max_retries - 1:
                raise
    
    return None


# ==========================================
# BUFFER & NODE FILTERING
# ==========================================

def filter_nodes_in_buffer(
    nodes,
    center_lat: float,
    center_lon: float,
    radius_m: float = 1000
) -> List[List[float]]:
    """
    Given nodes (numpy array or list of [lat, lon]), return only those within
    `radius_m` meters of the center point.
    
    Uses vectorized haversine formula for performance.
    """
    if not isinstance(nodes, np.ndarray):
        if not nodes:
            return []
        arr = np.array(nodes)
    else:
        if len(nodes) == 0:
            return []
        arr = nodes
    
    # Haversine formula (vectorized)
    R = 6371000.0  # Earth radius in meters
    
    lat1 = np.radians(center_lat)
    lat2 = np.radians(arr[:, 0])
    dlat = lat2 - lat1
    dlon = np.radians(arr[:, 1] - center_lon)
    
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    distances = R * c
    
    # Filter by radius — only convert the small subset to Python lists
    mask = distances <= radius_m
    filtered = arr[mask].tolist()
    
    return filtered


def create_buffer_circle_geojson(
    center_lat: float,
    center_lon: float,
    radius_m: float = 500
) -> Dict[str, Any]:
    """
    Create a GeoJSON polygon representing a circular buffer
    around a point. Used for visualization.
    """
    center = Point(center_lon, center_lat)
    
    proj_wgs84 = pyproj.CRS('EPSG:4326')
    utm_zone = int((center_lon + 180) / 6) + 1
    hemisphere = 'north' if center_lat >= 0 else 'south'
    proj_utm = pyproj.CRS(f'+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84')
    
    transformer_to_utm = pyproj.Transformer.from_crs(
        proj_wgs84, proj_utm, always_xy=True
    )
    transformer_to_wgs = pyproj.Transformer.from_crs(
        proj_utm, proj_wgs84, always_xy=True
    )
    
    center_utm = transform(transformer_to_utm.transform, center)
    buffer_utm = center_utm.buffer(radius_m, resolution=64)
    buffer_wgs = transform(transformer_to_wgs.transform, buffer_utm)
    
    return {
        'type': 'Feature',
        'properties': {
            'radius_m': radius_m,
            'center_lat': center_lat,
            'center_lon': center_lon,
        },
        'geometry': mapping(buffer_wgs),
    }


# ==========================================
# POLYGON BUFFER CREATION
# ==========================================

def create_polygon_buffers(
    geometry: Dict[str, Any],
    distances: List[float],
) -> List[Dict[str, Any]]:
    """
    Create buffered versions of a polygon geometry at specified distances.
    Uses UTM projection for metric accuracy.
    
    Args:
        geometry: GeoJSON geometry dict (Polygon)
        distances: List of buffer distances in meters
    
    Returns:
        List of GeoJSON geometry dicts (buffered polygons)
    """
    poly = shape(geometry)
    centroid = poly.centroid
    
    # Set up UTM projection
    proj_wgs84 = pyproj.CRS('EPSG:4326')
    utm_zone = int((centroid.x + 180) / 6) + 1
    hemisphere = 'north' if centroid.y >= 0 else 'south'
    proj_utm = pyproj.CRS(f'+proj=utm +zone={utm_zone} +{hemisphere} +datum=WGS84')
    
    transformer_to_utm = pyproj.Transformer.from_crs(
        proj_wgs84, proj_utm, always_xy=True
    )
    transformer_to_wgs = pyproj.Transformer.from_crs(
        proj_utm, proj_wgs84, always_xy=True
    )
    
    # Project polygon to UTM
    poly_utm = transform(transformer_to_utm.transform, poly)
    
    # Create buffers
    result = []
    for dist in distances:
        buffered_utm = poly_utm.buffer(dist, resolution=64)
        buffered_wgs = transform(transformer_to_wgs.transform, buffered_utm)
        result.append(mapping(buffered_wgs))
    
    return result


# ==========================================
# AOI PROJECT ASSEMBLY
# ==========================================

def build_li_project_geojson(
    establishments: List[Dict[str, Any]],
    country_code: str,
    region_code: str,
    city_name: str
) -> Tuple[Dict[str, Any], str]:
    """
    Build a complete LI project GeoJSON by:
    1. Generating the base AOI project (from services/aoi)
    2. Changing the city polygon prefix from AOI- to DIS- (periphery)
    3. Inserting establishment polygons as AOI- (core)
    
    Args:
        establishments: List of GeoJSON Feature dicts with
            properties.name, properties.id, and geometry
        country_code: e.g. "ES"
        region_code: e.g. "Madrid"
        city_name: e.g. "Madrid"
    
    Returns:
        Tuple of (geojson_dict, filename)
    """
    # Step 1: Generate base AOI project
    base_geojson, _ = generate_aoi_project(country_code, region_code, city_name)
    
    # Step 2: Modify features
    new_features = []
    
    for feature in base_geojson.get('features', []):
        props = feature.get('properties', {})
        fid = props.get('id', '')
        
        if fid.startswith('AOI-'):
            # City polygon → change to DIS- (periphery)
            props['id'] = fid.replace('AOI-', 'DIS-')
            props['poly_type'] = 'periphery'
        
        new_features.append(feature)
    
    # Step 3: Add establishment polygons as AOI-
    for i, est in enumerate(establishments):
        est_props = est.get('properties', {})
        est_name = est_props.get('name', f'Establishment {i+1}')
        # Use custom id if provided (e.g., buffer polygons like AOI-1-50),
        # otherwise generate sequential AOI-{i+1}
        est_id = est_props.get('id', f'AOI-{i+1}')
        est_poly_type = est_props.get('poly_type', 'core')
        
        new_features.append({
            'type': 'Feature',
            'properties': {
                'id': est_id,
                'name': est_name,
                'poly_type': est_poly_type,
            },
            'geometry': est.get('geometry'),
        })
    
    # Build final GeoJSON
    final_geojson = {
        'type': 'FeatureCollection',
        'features': new_features,
    }
    
    # Generate filename
    city_clean = city_name.replace(' ', '_').replace('/', '_')
    filename = f"{country_code}_{city_clean}_LI.geojson"
    
    return final_geojson, filename
