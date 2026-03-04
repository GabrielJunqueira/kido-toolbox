"""
AOI Generator via API — Backend Service
Uses Overpass API (OpenStreetMap) for dynamic province/municipality geometries.
Supports 9 countries: BR, MX, AR, CL, CO, PE, PT, ES, CH.
"""

import os
import json
import copy
import time
import unicodedata
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# ── Paths ───────────────────────────────────────────────────────
SERVICE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = SERVICE_DIR.parent / "data" / "aoi_generator"

# ── Overpass endpoints (round-robin) ────────────────────────────
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# ── Country configuration ──────────────────────────────────────
COUNTRY_CONFIG = {
    "Brazil":      {"iso": "BR", "prov_level": 4, "mun_level": 8,  "center": [-49.0, -14.0], "zoom": 4},
    "Mexico":      {"iso": "MX", "prov_level": 4, "mun_level": 6,  "center": [-102.5, 23.6], "zoom": 5},
    "Argentina":   {"iso": "AR", "prov_level": 4, "mun_level": 5,  "center": [-64.0, -34.0], "zoom": 4},
    "Chile":       {"iso": "CL", "prov_level": 4, "mun_level": 8,  "center": [-71.5, -35.6], "zoom": 4},
    "Colombia":    {"iso": "CO", "prov_level": 4, "mun_level": 6,  "center": [-74.3, 4.6],   "zoom": 5},
    "Peru":        {"iso": "PE", "prov_level": 4, "mun_level": 6,  "center": [-76.0, -9.2],  "zoom": 5},
    "Portugal":    {"iso": "PT", "prov_level": 6, "mun_level": 7,  "center": [-8.2, 39.4],   "zoom": 6},
    "Spain":       {"iso": "ES", "prov_level": 6, "mun_level": 8,  "center": [-3.7, 40.4],   "zoom": 5},
    "Switzerland": {"iso": "CH", "prov_level": 4, "mun_level": 8,  "center": [8.2, 46.8],    "zoom": 7},
}

# ── City key aliases (OSM state name → bundled JSON key) ───────
CITY_KEY_ALIASES = {
    "MX": {
        "Coahuila": "Coahuila de Zaragoza",
        "Estado de México": "México",
        "Michoacán": "Michoacán de Ocampo",
        "Veracruz": "Veracruz de Ignacio de la Llave",
    },
    "AR": {
        "Ciudad Autónoma de Buenos Aires": "Buenos Aires",
    },
    "CL": {
        "Región Aysén del General Carlos Ibáñez del Campo": "Región de Aysén del Gral.Ibañez del Campo",
        "Región de Magallanes y de la Antártica Chilena": "Región de Magallanes y Antártica Chilena",
        "Región de la Araucanía": "Región de La Araucanía",
        "Región del Biobío": "Región del Bío-Bío",
        "Región del Libertador General Bernardo O'Higgins": "Región del Libertador Bernardo O'Higgins",
    },
    "CO": {
        "Archipiélago de San Andrés, Providencia y Santa Catalina": "ARCHIPIELAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA",
        "Atlántico": "ATLANTICO",
        "Bogotá, Distrito Capital": "BOGOTA CAPITAL DISTRICT",
        "Bolívar": "BOLIVAR",
        "Boyacá": "BOYACA",
        "Caquetá": "CAQUETA",
        "Chocó": "CHOCO",
        "Córdoba": "CORDOBA",
        "Guainía": "GUAINIA",
        "Quindío": "QUINDIO",
        "Vaupés": "VAUPES",
    },
    "PE": {
        "Apurímac": "APURIMAC",
        "Huánuco": "HUANUCO",
        "Junín": "JUNIN",
        "San Martín": "SAN MARTIN",
    },
    "ES": {
        "Alacant / Alicante": "Alacant",
        "Araba / Álava": "Araba",
        "Asturias / Asturies": "Asturias",
        "Castelló / Castellón": "Castelló",
        "Comunidad de Madrid": "Madrid",
        "Región de Murcia": "Murcia",
        "València / Valencia": "València",
        "Navarra / Nafarroa": "Navarra",
    },
    "CH": {
        "Basel-Landschaft": "Basel Landschaft",
        "Basel-Stadt": "Basel Stadt",
        "Bern/Berne": "Bern",
        "Fribourg/Freiburg": "Fribourg",
        "Genève": "Geneve",
        "Graubünden/Grischun/Grigioni": "Grisons",
        "Luzern": "Lucerne",
        "Neuchâtel": "Neuchatel",
        "Valais/Wallis": "Valais",
    },
}


# ════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

def _normalize(s: str) -> str:
    return " ".join(_strip_accents(s.strip().lower()).split())

def _norm_key(s: str) -> str:
    return _strip_accents(s.strip().lower())


# ── Overpass ────────────────────────────────────────────────────

def _overpass_query(query: str, timeout: int = 120) -> dict:
    """Execute Overpass QL with multi-endpoint retry and exponential backoff."""
    last_error = None
    # Two passes: if all endpoints fail once, wait and try again
    for attempt in range(2):
        for ep in OVERPASS_ENDPOINTS:
            try:
                r = requests.post(ep, data={"data": query}, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                if r.status_code in (429, 504):
                    # Rate-limited or gateway timeout — back off and try next
                    wait = 5 * (attempt + 1)
                    time.sleep(wait)
                    last_error = f"{ep} returned {r.status_code}"
                    continue
                last_error = f"{ep} returned {r.status_code}"
            except requests.exceptions.Timeout:
                last_error = f"{ep} timed out after {timeout}s"
                continue
            except Exception as e:
                last_error = f"{ep} error: {e}"
                continue
        # Wait before second pass
        if attempt == 0:
            time.sleep(10)
    raise RuntimeError(f"All Overpass endpoints failed. Last error: {last_error}")


def _osm_elements_to_geojson(elements: list) -> dict:
    """Convert Overpass 'out geom' elements into a GeoJSON FeatureCollection."""
    features = []
    for el in elements:
        if el.get("type") != "relation":
            continue
        tags = el.get("tags", {})
        members = el.get("members", [])

        outers, inners = [], []
        for m in members:
            geom = m.get("geometry", [])
            if not geom:
                continue
            coords = [[pt["lon"], pt["lat"]] for pt in geom]
            if len(coords) < 4:
                continue
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            role = m.get("role", "outer")
            (inners if role == "inner" else outers).append(coords)

        if not outers:
            continue

        merged = _merge_rings(outers)
        if not merged:
            continue

        if len(merged) == 1 and not inners:
            geometry = {"type": "Polygon", "coordinates": [merged[0]] + inners}
        else:
            polys = [[ring] + inners for ring in merged]
            geometry = {"type": "MultiPolygon", "coordinates": [p for p in polys]}

        features.append({
            "type": "Feature",
            "properties": {"id": str(el["id"]), "name": tags.get("name", "")},
            "geometry": geometry,
        })

    return {"type": "FeatureCollection", "features": features}


def _merge_rings(rings: list) -> list:
    """Merge connected open rings into closed polygons."""
    def is_closed(ring):
        return len(ring) >= 4 and ring[0] == ring[-1]

    closed, open_r = [], []
    for r in rings:
        (closed if is_closed(r) else open_r).append(r)

    while open_r:
        current = list(open_r.pop(0))
        changed = True
        while changed and not is_closed(current):
            changed = False
            for i, r in enumerate(open_r):
                if current[-1] == r[0]:
                    current.extend(r[1:])
                    open_r.pop(i)
                    changed = True
                    break
                elif current[-1] == r[-1]:
                    current.extend(list(reversed(r))[1:])
                    open_r.pop(i)
                    changed = True
                    break
        if is_closed(current):
            closed.append(current)

    return closed


# ── Core matching ──────────────────────────────────────────────

_PREFIXES = [
    "departamento de ", "departamento ",
    "municipio de ", "municipio ",
    "município de ", "município ",
    "partido de ", "partido ",
    "provincia de ", "provincia ",
    "concelho de ", "concelho ",
    "distrito de ", "distrito ",
    "freguesia de ", "freguesia ",
    "comuna de ", "comuna ",
    "canton de ", "cantón de ", "canton ",
    "city of ", "ville de ",
    "region de ", "región de ",
]

def _is_core_match(feat_name, feat_id, city_name, city_id):
    if str(feat_id) == str(city_id):
        return True
    fn = _normalize(feat_name)
    cn = _normalize(city_name)
    if fn == cn:
        return True
    for prefix in _PREFIXES:
        if fn.startswith(prefix) and fn[len(prefix):] == cn:
            return True
        if cn.startswith(prefix) and cn[len(prefix):] == fn:
            return True
    if len(cn) >= 5 and cn in fn:
        return True
    if len(fn) >= 5 and fn in cn:
        return True
    return False


# ════════════════════════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════════════════════════

def get_available_countries() -> List[Dict[str, str]]:
    return [
        {"name": name, "iso": cfg["iso"]}
        for name, cfg in COUNTRY_CONFIG.items()
    ]


def get_states(iso: str) -> List[Dict[str, str]]:
    path = DATA_DIR / f"states_{iso}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def get_cities(iso: str, state_name: str) -> List[Dict[str, str]]:
    path = DATA_DIR / f"cities_{iso}.json"
    if not path.exists():
        return []
    cities = json.loads(path.read_text(encoding="utf-8"))
    aliases = CITY_KEY_ALIASES.get(iso, {})
    lookup_key = aliases.get(state_name, state_name)

    mun_list = (
        cities.get(lookup_key)
        or cities.get(lookup_key.title())
        or cities.get(lookup_key.upper())
    )
    if not mun_list:
        lk_norm = _norm_key(lookup_key)
        for ck, cv in cities.items():
            if _norm_key(ck) == lk_norm:
                mun_list = cv
                break
    return mun_list or []


def generate_aoi_project(
    country_name: str,
    state_id: str,
    state_name: str,
    city_id: str,
    city_name: str,
) -> Tuple[Dict[str, Any], str]:
    """
    Generate AOI GeoJSON project.
    Returns (geojson_dict, filename).
    """
    cfg = COUNTRY_CONFIG.get(country_name)
    if not cfg:
        raise ValueError(f"Unknown country: {country_name}")

    iso = cfg["iso"]
    mun_level = cfg["mun_level"]

    # 1. Load all state OSM IDs
    states = get_states(iso)
    all_state_ids = [int(s["id"]) for s in states if str(s.get("id", "")).isdigit()]

    # 2. Fetch province geometries
    provinces_geojson = _fetch_provinces_by_ids(all_state_ids)

    # 3. Fetch municipalities for selected state
    mun_geojson = _fetch_state_municipalities(int(state_id), mun_level)

    # 4. Build AOI project
    features = []

    # Provinces (all except selected state)
    for feat in provinces_geojson.get("features", []):
        fid = str(feat["properties"].get("id", ""))
        if fid == str(state_id):
            continue
        new_feat = copy.deepcopy(feat)
        raw_id = fid.replace("PRO-", "")
        new_feat["properties"] = {
            "name": feat["properties"].get("name", ""),
            "id": f"PRO-{raw_id}",
            "poly_type": "periphery",
        }
        features.append(new_feat)

    # Municipalities
    core_feature = None
    for feat in mun_geojson.get("features", []):
        fid = str(feat["properties"].get("id", ""))
        fname = feat["properties"].get("name", "")
        is_core = _is_core_match(fname, fid, city_name, city_id)

        if is_core:
            core_feature = copy.deepcopy(feat)
            raw_id = fid.replace("MUN-", "").replace("AOI-", "")
            core_feature["properties"] = {
                "name": city_name,
                "id": f"AOI-{raw_id}",
                "poly_type": "core",
            }
        else:
            new_feat = copy.deepcopy(feat)
            raw_id = fid.replace("MUN-", "")
            new_feat["properties"] = {
                "name": fname,
                "id": f"MUN-{raw_id}",
                "poly_type": "periphery",
            }
            features.append(new_feat)

    if core_feature:
        features.append(core_feature)

    geojson = {"type": "FeatureCollection", "features": features}
    safe_name = city_name.replace(" ", "_").replace("/", "_")
    filename = f"{safe_name}_AOI.geojson"

    return geojson, filename


# ── Internal Overpass helpers ──────────────────────────────────

def _fetch_provinces_by_ids(osm_ids: List[int], chunk_size: int = 15) -> dict:
    all_features = []
    for i in range(0, len(osm_ids), chunk_size):
        chunk = osm_ids[i:i + chunk_size]
        id_filter = "".join(f"rel({rid});" for rid in chunk)
        query = f"""
        [out:json][timeout:120];
        ({id_filter})
        ->.rels;
        .rels out geom;
        """
        data = _overpass_query(query)
        gc = _osm_elements_to_geojson(data.get("elements", []))
        all_features.extend(gc["features"])
    return {"type": "FeatureCollection", "features": all_features}


def _fetch_state_municipalities(state_osm_id: int, mun_level: int) -> dict:
    query = f"""
    [out:json][timeout:120];
    rel({state_osm_id});
    map_to_area->.state;
    (
      relation["boundary"="administrative"]["admin_level"="{mun_level}"](area.state);
    );
    out geom;
    """
    data = _overpass_query(query)
    return _osm_elements_to_geojson(data.get("elements", []))
