"""
AOI Project Generator Service
Handles geographic processing for Tourism (AOI) projects
"""

import os
import json
from typing import List, Dict, Any, Optional, Tuple
import geopandas as gpd
import pandas as pd
import warnings

warnings.filterwarnings('ignore')

# Base path for geographic data files
# Prioritize environment variable (for Docker/Cloud), fallback to local development path
# Note: In production, ensure the data is mounted or copied here
GEO_DATA_PATH = os.getenv(
    "GEO_DATA_PATH", 
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "aoi")
)

# Brazilian state code to name mapping
ESTADOS_BR = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo",
    "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
    "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins"
}

# Country configuration
COUNTRY_CONFIG = {
    "BR": {
        "name": "Brasil",
        "folder": "Brasil",
        "mode": "split_files",
        "file_l1": "brasil_UFs_simp.geojson",
        "subfolder_l2": "SIMP",
        "col_name_l1": "name",
        "col_name_l2": "name"
    },
    "PT": {
        "name": "Portugal",
        "folder": "Portugal",
        "mode": "single_file",
        "file_l1": "distritos_portugal_SIMP.geojson",
        "file_l2": "concelhos_portugal_SIMP.geojson",
        "col_filter_l2": "distrito",
        "col_name_l1": "name",
        "col_name_l2": "name"
    },
    "ES": {
        "name": "España",
        "folder": "Spain",
        "mode": "single_file",
        "file_l1": "esp_provinces_SIMP.geojson",
        "file_l2": "esp_municipalities_SIMP.geojson",
        "col_filter_l2": "provincia",
        "col_name_l1": "name",
        "col_name_l2": "name"
    },
    "MX": {
        "name": "México",
        "folder": "México",
        "mode": "single_file",
        "file_l1": "Estados.geojson",
        "file_l2": "mun_MX_SIMP.geojson",
        "col_filter_l2": "state",
        "col_name_l1": "name",
        "col_name_l2": "name"
    },
    "CL": {
        "name": "Chile",
        "folder": "Chile",
        "mode": "single_file",
        "file_l1": "regiones_SIMP.geojson",
        "file_l2": "comunas_SIMP.geojson",
        "col_filter_l2": "region",
        "col_name_l1": "name",
        "col_name_l2": "name"
    }
}


def normalize(text: str) -> str:
    """Normalize strings for comparison."""
    return str(text).strip().lower()


def get_available_countries() -> List[Dict[str, str]]:
    """Get list of available countries with their codes and names."""
    return [
        {"code": code, "name": cfg["name"]}
        for code, cfg in COUNTRY_CONFIG.items()
    ]


def get_brazilian_states() -> List[Dict[str, str]]:
    """Get list of Brazilian states with codes and names."""
    return [
        {"code": code, "name": name}
        for code, name in sorted(ESTADOS_BR.items(), key=lambda x: x[1])
    ]


def load_gdf(path: str) -> gpd.GeoDataFrame:
    """Load GeoJSON file with error handling."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    try:
        return gpd.read_file(path)
    except Exception as e:
        raise Exception(f"Error reading {path}: {e}")


def get_regions_for_country(country_code: str) -> List[str]:
    """
    Get list of regions/states/districts for a country.
    Returns list of region names from Level 1 file.
    """
    if country_code not in COUNTRY_CONFIG:
        raise ValueError(f"Country not configured: {country_code}")
    
    cfg = COUNTRY_CONFIG[country_code]
    
    # For Brazil, return state codes/names
    if country_code == "BR":
        return [{"code": code, "name": name} for code, name in sorted(ESTADOS_BR.items(), key=lambda x: x[1])]
    
    # For other countries, load Level 1 file
    path_l1 = os.path.join(GEO_DATA_PATH, cfg['folder'], cfg['file_l1'])
    gdf_l1 = load_gdf(path_l1)
    
    col_name = cfg.get('col_name_l1', 'name')
    if col_name not in gdf_l1.columns:
        # Try to find a name-like column
        for col in ['name', 'NAME', 'Name', 'nombre', 'NOMBRE']:
            if col in gdf_l1.columns:
                col_name = col
                break
    
    names = gdf_l1[col_name].dropna().unique().tolist()
    return [{"code": name, "name": name} for name in sorted(names)]


def get_municipalities_for_region(country_code: str, region_code: str) -> List[str]:
    """
    Get list of municipalities for a given region.
    """
    if country_code not in COUNTRY_CONFIG:
        raise ValueError(f"Country not configured: {country_code}")
    
    cfg = COUNTRY_CONFIG[country_code]
    
    # For Brazil, load state-specific file
    if cfg['mode'] == "split_files":
        # Handle special case for DF (has space in filename)
        if region_code == "DF":
            filename = "DF _Municipios.geojson"
        else:
            filename = f"{region_code}_Municipios.geojson"
        path_l2 = os.path.join(GEO_DATA_PATH, cfg['folder'], cfg['subfolder_l2'], filename)
        print(f"Loading Brazil file: {path_l2}")
        
        try:
            gdf_l2 = load_gdf(path_l2)
            col_name = cfg.get('col_name_l2', 'name')
            print(f"Columns found: {gdf_l2.columns.tolist()}")
            if col_name not in gdf_l2.columns:
                 # Fallback to finding name-like column (case insensitive)
                 for c in gdf_l2.columns:
                     if c.lower() == 'name':
                         col_name = c
                         break
            names = gdf_l2[col_name].dropna().unique().tolist()
            return sorted(names)
        except Exception as e:
            print(f"Error loading {path_l2}: {e}")
            raise e
    
    # For other countries, filter from single file
    path_l2 = os.path.join(GEO_DATA_PATH, cfg['folder'], cfg['file_l2'])
    print(f"Loading Country file: {path_l2}")
    gdf_l2 = load_gdf(path_l2)
    
    col_filter = cfg['col_filter_l2']
    col_name = cfg.get('col_name_l2', 'name')
    
    # Filter by region
    print(f"Filtering by {col_filter} == {region_code}")
    filtered = gdf_l2[gdf_l2[col_filter].apply(normalize) == normalize(region_code)]
    print(f"Found {len(filtered)} matches")
    
    if filtered.empty:
        return []
    
    names = filtered[col_name].dropna().unique().tolist()
    return sorted(names)


def generate_aoi_project(
    country_code: str,
    region_code: str,
    city_name: str
) -> Tuple[Dict[str, Any], str]:
    """
    Generate AOI project GeoJSON.
    
    Returns:
        Tuple of (geojson_dict, project_filename)
    """
    if country_code not in COUNTRY_CONFIG:
        raise ValueError(f"Country not configured: {country_code}")
    
    cfg = COUNTRY_CONFIG[country_code]
    
    # Get state name for Brazil
    if country_code == "BR":
        if region_code not in ESTADOS_BR:
            raise ValueError(f"Invalid Brazilian state: {region_code}")
        state_name = ESTADOS_BR[region_code]
    else:
        state_name = region_code
    
    # ---------------------------------------------------------
    # STEP 1: Load and filter Level 1 (States/Districts)
    # ---------------------------------------------------------
    path_l1 = os.path.join(GEO_DATA_PATH, cfg['folder'], cfg['file_l1'])
    gdf_l1 = load_gdf(path_l1)
    
    col_name_l1 = cfg.get('col_name_l1', 'name')
    
    # Filter: Keep all EXCEPT the selected state (they become PRO - periphery)
    l1_rest = gdf_l1[gdf_l1[col_name_l1].apply(normalize) != normalize(state_name)]
    
    # Validate that we found the state
    if len(l1_rest) == len(gdf_l1):
        raise ValueError(f"State/District '{state_name}' not found in Level 1 file")
    
    # Ensure 'id' column exists
    if 'id' not in l1_rest.columns:
        l1_rest = l1_rest.copy()
        l1_rest['id'] = range(len(l1_rest))
    
    l1_rest = l1_rest.copy()
    l1_rest['id'] = "PRO-" + l1_rest['id'].astype(str)
    l1_rest['poly_type'] = 'periphery'
    
    # Keep only necessary columns
    cols_to_keep = ['id', 'name', 'poly_type', 'geometry']
    cols_available = [c for c in cols_to_keep if c in l1_rest.columns]
    if col_name_l1 != 'name' and col_name_l1 in l1_rest.columns:
        l1_rest['name'] = l1_rest[col_name_l1]
    l1_rest = l1_rest[[c for c in cols_to_keep if c in l1_rest.columns]]
    
    # ---------------------------------------------------------
    # STEP 2: Load and filter Level 2 (Municipalities)
    # ---------------------------------------------------------
    
    if cfg['mode'] == "split_files":
        # Brazil: Load state-specific file
        if region_code == "DF":
            filename = "DF _Municipios.geojson"
        else:
            filename = f"{region_code}_Municipios.geojson"
        path_l2 = os.path.join(GEO_DATA_PATH, cfg['folder'], cfg['subfolder_l2'], filename)
        gdf_l2 = load_gdf(path_l2)
        l2_filtered = gdf_l2
    else:
        # Other countries: Filter from single file
        path_l2 = os.path.join(GEO_DATA_PATH, cfg['folder'], cfg['file_l2'])
        gdf_l2 = load_gdf(path_l2)
        
        col_filter = cfg['col_filter_l2']
        l2_filtered = gdf_l2[gdf_l2[col_filter].apply(normalize) == normalize(state_name)]
        
        if l2_filtered.empty:
            raise ValueError(f"No municipalities found for '{state_name}'")
    
    col_name_l2 = cfg.get('col_name_l2', 'name')
    
    # ---------------------------------------------------------
    # STEP 3: Separate target city from other municipalities
    # ---------------------------------------------------------
    
    target_city = l2_filtered[l2_filtered[col_name_l2].apply(normalize) == normalize(city_name)]
    
    if target_city.empty:
        raise ValueError(f"City '{city_name}' not found in '{state_name}'")
    
    other_cities = l2_filtered[l2_filtered[col_name_l2].apply(normalize) != normalize(city_name)]
    
    # ---------------------------------------------------------
    # STEP 4: Format IDs and prepare data
    # ---------------------------------------------------------
    
    # Prepare Target City (AOI - core)
    target_city = target_city.copy()
    if 'id' not in target_city.columns:
        target_city['id'] = '1'
    id_clean = target_city['id'].astype(str).str.replace('MUN-', '').str.replace('AOI-', '')
    target_city['id'] = 'AOI-' + id_clean
    target_city['poly_type'] = 'core'
    if col_name_l2 != 'name':
        target_city['name'] = target_city[col_name_l2]
    
    # Prepare Other Municipalities (MUN)
    other_cities = other_cities.copy()
    if 'id' not in other_cities.columns:
        other_cities['id'] = range(len(other_cities))
    id_clean_other = other_cities['id'].astype(str).str.replace('MUN-', '')
    other_cities['id'] = 'MUN-' + id_clean_other
    other_cities['poly_type'] = 'periphery'
    if col_name_l2 != 'name':
        other_cities['name'] = other_cities[col_name_l2]
    
    # Keep only necessary columns
    for df in [target_city, other_cities]:
        for col in list(df.columns):
            if col not in ['id', 'name', 'poly_type', 'geometry']:
                df.drop(columns=[col], inplace=True, errors='ignore')
    
    # ---------------------------------------------------------
    # STEP 5: Concatenate all geometries
    # ---------------------------------------------------------
    
    final_project = pd.concat([l1_rest, other_cities, target_city], ignore_index=True)
    final_gdf = gpd.GeoDataFrame(final_project, crs="EPSG:4326")
    
    # Generate filename
    city_clean = city_name.replace(' ', '_').replace('/', '_')
    filename = f"{country_code}_{city_clean}_AOI.geojson"
    
    # Convert to GeoJSON dict
    geojson = json.loads(final_gdf.to_json())
    
    return geojson, filename
