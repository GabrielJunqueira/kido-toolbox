"""
GeoJSON Validator Service
Replicates the platform's polygon validation checks locally.
Every issue includes location data so the frontend can navigate to the exact problem.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import shapely.validation
from shapely.geometry import mapping, shape, Polygon, LineString
from shapely.validation import make_valid
from shapely.strtree import STRtree

VALID_POLY_TYPES = {"core", "periphery", "checkpoint"}
MIN_CORES   = 1
MIN_AREA_KM2 = 0.01


# ── Data classes ──────────────────────────────────────────────

@dataclass
class ValidationIssue:
    level: str                              # "error" | "warning" | "fix"
    code: str
    message: str
    feature_ids: List[str] = field(default_factory=list)
    problem_point: Optional[List[float]] = None   # [lon, lat] exact problem location
    centroids: List[List[float]] = field(default_factory=list)  # centroids of affected polys


@dataclass
class ValidationResult:
    valid: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    fixed_geojson: Optional[Dict] = None
    summary: Dict[str, Any] = field(default_factory=dict)


# ── Helpers ───────────────────────────────────────────────────

def _area_km2(geom) -> float:
    try:
        import pyproj, shapely.ops
        c = geom.centroid
        epsg = f"326{int((c.x+180)//6)+1:02d}" if c.y >= 0 else f"327{int((c.x+180)//6)+1:02d}"
        tr = pyproj.Transformer.fromcrs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        return shapely.ops.transform(tr.transform, geom).area / 1e6
    except Exception:
        return geom.area * 111_000 * 111_000 / 1e6


def _fid(feature: Dict) -> str:
    props = feature.get("properties") or {}
    v = props.get("id")
    return str(v) if v is not None else "(sem id)"


def _poly_type(feature: Dict) -> Optional[str]:
    props = feature.get("properties") or {}
    v = props.get("poly_type")
    return str(v).strip().lower() if v is not None else None


def _centroid(feature: Dict) -> Optional[List[float]]:
    gd = feature.get("geometry")
    if not gd:
        return None
    try:
        c = shape(gd).centroid
        return [c.x, c.y]
    except Exception:
        return None


def _centroids_for(features: List[Dict], id_set: set) -> List[List[float]]:
    return [c for f in features if _fid(f) in id_set for c in [_centroid(f)] if c]


def find_all_self_intersections(geom) -> List[List[float]]:
    """Encontra todos as coordenadas de intersecção reais de um polígono."""
    pts = []
    
    def process_ring(ring):
        coords = list(ring.coords)
        if len(coords) < 4:
            return
        segments = [LineString([coords[i], coords[i+1]]) for i in range(len(coords)-1)]
        tree = STRtree(segments)
        
        for i, seg in enumerate(segments):
            candidates_idx = tree.query(seg)
            for j in candidates_idx:
                if j <= i:
                    continue
                # Se os segmentos são adjacentes, eles naturalmente se tocam no vértice. Ignoramos.
                if abs(i - j) == 1 or (i == 0 and j == len(segments) - 1):
                    continue
                
                inter = seg.intersection(segments[j])
                if not inter.is_empty:
                    if inter.geom_type == 'Point':
                        pts.append([inter.x, inter.y])
                    elif inter.geom_type == 'MultiPoint':
                        for p in inter.geoms:
                            pts.append([p.x, p.y])

    # Tratamento de polígonos validos (extração de rings)
    try:
        if geom.geom_type == 'Polygon':
            process_ring(geom.exterior)
            for interior in geom.interiors:
                process_ring(interior)
        elif geom.geom_type == 'MultiPolygon':
            for poly in geom.geoms:
                process_ring(poly.exterior)
                for interior in poly.interiors:
                    process_ring(interior)
    except Exception:
        pass
        
    # Remove duplicados baseados na exata coordenada, round 6 casas decimais
    unique_pts = []
    seen = set()
    for pt in pts:
        coord = (round(pt[0], 6), round(pt[1], 6))
        if coord not in seen:
            seen.add(coord)
            unique_pts.append(pt)

    return unique_pts

# ── Individual checks ─────────────────────────────────────────

def check_structure(geojson: Dict) -> List[ValidationIssue]:
    issues = []
    if geojson.get("type") != "FeatureCollection":
        issues.append(ValidationIssue(
            level="error", code="invalidFeatureCollection",
            message=f"GeoJSON must be a 'FeatureCollection'. Found: '{geojson.get('type')}'."))
    features = geojson.get("features")
    if not isinstance(features, list) or len(features) == 0:
        issues.append(ValidationIssue(
            level="error", code="emptyFeatures",
            message="GeoJSON contains no features, or the 'features' field is missing/empty."))
    return issues


def clean_make_valid_result(geom) -> Optional[Any]:
    """
    Removes lines and points generated by make_valid.
    If a MultiPolygon remains, it removes 'slivers' (fragments 1000x smaller than the main part).
    Returns the cleaned geometry or None if nothing remains.
    """
    polygons = []
    if geom.geom_type == 'Polygon':
        polygons.append(geom)
    elif geom.geom_type in ('MultiPolygon', 'GeometryCollection'):
        for g in getattr(geom, 'geoms', []):
            if g.geom_type == 'Polygon':
                polygons.append(g)
            elif g.geom_type == 'MultiPolygon':
                for p in g.geoms:
                    polygons.append(p)
    
    if not polygons:
        return None
        
    if len(polygons) == 1:
        return polygons[0]
        
    # Limpeza de slivers (fragmentos 1000x menores)
    # Calculamos área aproximada
    areas = []
    for p in polygons:
        try:
            areas.append(_area_km2(p))
        except Exception:
            areas.append(p.area) # fallback para degraus relativos
            
    max_area = max(areas)
    if max_area <= 0:
        return polygons[0] # Edge case total, retorna primeiro
        
    filtered_polys = []
    for p, area in zip(polygons, areas):
        # Se a area do fragmento for > 0, checa proporção. Se for 1000x menor, descarta.
        if area > 0 and (max_area / area) > 1000:
            continue
        filtered_polys.append(p)
        
    if not filtered_polys:
        return None
    if len(filtered_polys) == 1:
        return filtered_polys[0]
    
    from shapely.geometry import MultiPolygon
    return MultiPolygon(filtered_polys)


def check_geometry_validity(features: List[Dict]) -> Tuple[List[ValidationIssue], Dict[str, str]]:
    issues, invalid_map = [], {}

    for feat in features:
        fid = _fid(feat)
        gd = feat.get("geometry")

        if gd is None:
            issues.append(ValidationIssue(
                level="error", code="missingGeometry",
                message=f"Polygon '{fid}' has no geometry.",
                feature_ids=[fid]))
            continue

        try:
            geom = shape(gd)
        except Exception as e:
            issues.append(ValidationIssue(
                level="error", code="unparsableGeometry",
                message=f"Polygon '{fid}': geometry could not be read ({e}).",
                feature_ids=[fid]))
            invalid_map[fid] = str(e)
            continue

        if not geom.is_valid:
            reason = shapely.validation.explain_validity(geom)
            invalid_map[fid] = reason
            
            c = _centroid(feat)
            
            # Se for auto-intersecção, reportamos TODAS as instâncias
            if "self-intersection" in reason.lower() or "intersect" in reason.lower():
                intersections = find_all_self_intersections(geom)
                if intersections:
                    for idx, pt in enumerate(intersections):
                        issues.append(ValidationIssue(
                            level="error",
                            code="invalidGeometry",
                            message=(
                                f"Polygon '{fid}' has self-intersection #{idx+1}. "
                                "Auto-repair pending, but you can use the 'Locate' button to fix it manually on the map."
                            ),
                            feature_ids=[fid],
                            problem_point=pt,
                            centroids=[c] if c else []))
                else:
                    # Fallback (caso falhe em encontrar)
                    issues.append(ValidationIssue(
                        level="error", code="invalidGeometry",
                        message=f"Polygon '{fid}' has self-intersection: {reason}.",
                        feature_ids=[fid], centroids=[c] if c else []))
            else:
                # Outros tipos de geometria invalida
                issues.append(ValidationIssue(
                    level="error", code="invalidGeometry",
                    message=f"Polygon '{fid}' has invalid geometry: {reason}.",
                    feature_ids=[fid], centroids=[c] if c else []))

    return issues, invalid_map


def clean_and_repair_geometries(features: List[Dict], invalid_map: Dict[str, str]) -> Tuple[List[Dict], List[ValidationIssue]]:
    """
    Applies make_valid to invalid geometries and cleans all geometries
    (removes non-polygonal noise and 1000x smaller slivers from MultiPolygons).
    """
    issues, updated = [], []

    for feat in features:
        fid = _fid(feat)
        gd = feat.get("geometry")
        if gd is None:
            updated.append(feat)
            continue
            
        try:
            geom = shape(gd)
            was_invalid = fid in invalid_map
            
            # 1. Repair if invalid
            current_geom = make_valid(geom) if was_invalid else geom
            
            # 2. Clean (remove lines, points, and 1000x smaller slivers)
            cleaned = clean_make_valid_result(current_geom)
            
            if not cleaned:
                if was_invalid:
                    raise ValueError("No valid polygon remained after repair and cleaning.")
                updated.append(feat)
                continue

            # Check if something actually changed
            # (We check type or part count change as a proxy for 'cleaning')
            changed = was_invalid or (cleaned.geom_type != geom.geom_type)
            if not changed and geom.geom_type == 'MultiPolygon':
                # Check if number of parts changed (slivers removed)
                if len(getattr(cleaned, 'geoms', [])) != len(getattr(geom, 'geoms', [])):
                    changed = True

            if changed:
                updated.append({**feat, "geometry": mapping(cleaned)})
                try:
                    fc = cleaned.centroid
                    centroids = [[fc.x, fc.y]]
                except Exception:
                    centroids = []
                
                if was_invalid:
                    msg = f"Polygon '{fid}': repaired and cleaned. "
                else:
                    msg = f"Polygon '{fid}': cleaned. "
                
                if cleaned.geom_type != geom.geom_type:
                    msg += f"Converted ({geom.geom_type} → {cleaned.geom_type}). Non-polygonal segments or tiny artifacts were removed."
                elif geom.geom_type == 'MultiPolygon' and len(getattr(cleaned, 'geoms', [])) < len(getattr(geom, 'geoms', [])):
                    msg += f"Tiny slivers (1000x smaller than the main part) were removed from this MultiPolygon."
                else:
                    msg += "Geometry stabilized."
                    
                issues.append(ValidationIssue(
                    level="fix", code="geometryCleaned",
                    message=msg,
                    feature_ids=[fid], centroids=centroids))
            else:
                updated.append(feat)

        except Exception as e:
            updated.append(feat)
            if fid in invalid_map:
                issues.append(ValidationIssue(
                    level="error", code="repairFailed",
                    message=f"Polygon '{fid}': repair failed ({e}). Manual correction on the map required.",
                    feature_ids=[fid],
                    centroids=[c for c in [_centroid(feat)] if c]))
    
    return updated, issues





def check_duplicate_ids(features: List[Dict]) -> Tuple[List[Dict], List[ValidationIssue]]:
    issues, seen, result = [], {}, []

    for feat in features:
        fid = _fid(feat)
        if fid in seen:
            seen[fid] += 1
            new_id = f"{fid}_dup{seen[fid]}"
            np2 = {**(feat.get("properties") or {}), "id": new_id}
            result.append({**feat, "properties": np2})
            issues.append(ValidationIssue(
                level="fix", code="duplicateIdFixed",
                message=f"Duplicate ID '{fid}' renamed to '{new_id}'.",
                feature_ids=[fid, new_id],
                centroids=[c for c in [_centroid(feat)] if c]))
        else:
            seen[fid] = 0; result.append(feat)

    dup_ids = [fid for fid, cnt in seen.items() if cnt > 0]
    if dup_ids:
        issues.insert(0, ValidationIssue(
            level="error", code="duplicateIds",
            message=f"Duplicate IDs: {', '.join(dup_ids)}. Renamed automatically, but review carefully.",
            feature_ids=dup_ids,
            centroids=_centroids_for(result, set(dup_ids))))
    return result, issues


def check_poly_types(features: List[Dict]) -> List[ValidationIssue]:
    invalid = [(f, _fid(f), _poly_type(f)) for f in features
               if _poly_type(f) is None or _poly_type(f) not in VALID_POLY_TYPES]
    if not invalid:
        return []
    detail = ", ".join([f"'{fid}' ('{pt}')" for _, fid, pt in invalid])
    return [ValidationIssue(
        level="error", code="invalidPolyType",
        message=f"Invalid poly_type in polygons: {detail}. Use: core, periphery, or checkpoint.",
        feature_ids=[fid for _, fid, _ in invalid],
        centroids=[c for f, _, _ in invalid for c in [_centroid(f)] if c])]


def fill_missing_names(features: List[Dict]) -> Tuple[List[Dict], List[ValidationIssue]]:
    result, fixed_ids, centroids = [], [], []
    for feat in features:
        props = feat.get("properties") or {}
        if props.get("name") is None:
            fixed_ids.append(_fid(feat))
            c = _centroid(feat)
            if c: centroids.append(c)
            result.append({**feat, "properties": {**props, "name": ""}})
        else:
            result.append(feat)
    issues = []
    if fixed_ids:
        issues.append(ValidationIssue(
            level="fix", code="missingNameFilled",
            message=f"Missing 'name' field automatically inserted in {len(fixed_ids)} polygon(s).",
            feature_ids=fixed_ids, centroids=centroids))
    return result, issues


def check_areas(features: List[Dict]) -> List[ValidationIssue]:
    small = []
    for feat in features:
        gd = feat.get("geometry")
        if not gd: continue
        try:
            area = _area_km2(shape(gd))
            if area < MIN_AREA_KM2:
                small.append((_fid(feat), round(area, 6), _centroid(feat)))
        except Exception:
            pass
    if not small:
        return []
    
    issues = []
    for fid, a, c in small:
        issues.append(ValidationIssue(
            level="warning", code="areaTooSmall",
            message=f"Warning: Polygon '{fid}' ({a} km²) might be too small (< {MIN_AREA_KM2} km²) and could be ignored.",
            feature_ids=[fid],
            centroids=[c] if c else []))
    return issues


def check_cardinality(features: List[Dict]) -> List[ValidationIssue]:
    issues = []
    cores = [f for f in features if _poly_type(f) == "core"]
    all_centroids = [c for f in features for c in [_centroid(f)] if c]
    if not features:
        issues.append(ValidationIssue(
            level="error", code="tooFewEntries",
            message="No valid polygons found."))
    elif len(cores) < MIN_CORES:
        issues.append(ValidationIssue(
            level="error", code="fewCoreEntries",
            message=f"At least {MIN_CORES} 'core' polygon(s) required. Found: {len(cores)}.",
            centroids=all_centroids))
    return issues


# ── Main entry point ──────────────────────────────────────────

def validate_geojson(geojson: Dict) -> ValidationResult:
    all_issues: List[ValidationIssue] = []

    struct_issues = check_structure(geojson)
    all_issues.extend(struct_issues)
    if any(i.level == "error" for i in struct_issues):
        return ValidationResult(valid=False, issues=all_issues,
                                summary={"total": 0, "cores": 0, "peripheries": 0, "checkpoints": 0})

    features: List[Dict] = list(geojson.get("features", []))

    geom_issues, invalid_map = check_geometry_validity(features)
    all_issues.extend(geom_issues)

    features, fix_issues = clean_and_repair_geometries(features, invalid_map)
    all_issues.extend(fix_issues)

    features, dup_issues = check_duplicate_ids(features)
    all_issues.extend(dup_issues)

    type_issues = check_poly_types(features)
    all_issues.extend(type_issues)

    features, name_issues = fill_missing_names(features)
    all_issues.extend(name_issues)

    area_issues = check_areas(features)
    all_issues.extend(area_issues)

    valid_features = [f for f in features if _poly_type(f) in VALID_POLY_TYPES]
    all_issues.extend(check_cardinality(valid_features))

    has_error = any(i.level == "error" for i in all_issues)
    has_fixes = any(i.level == "fix" for i in all_issues)

    cores       = sum(1 for f in valid_features if _poly_type(f) == "core")
    peripheries = sum(1 for f in valid_features if _poly_type(f) == "periphery")
    checkpoints = sum(1 for f in valid_features if _poly_type(f) == "checkpoint")

    return ValidationResult(
        valid=not has_error,
        issues=all_issues,
        fixed_geojson={**geojson, "features": features} if (has_fixes or has_error) else None,  # Fornece o fix partial mesmo com erros!
        summary={
            "total": len(features), "cores": cores,
            "peripheries": peripheries, "checkpoints": checkpoints,
            "invalid_geometries": sum(1 for i in all_issues if i.code in
                                      ("invalidGeometry", "unparsableGeometry", "missingGeometry")),
            "fixes_applied": sum(1 for i in all_issues if i.level == "fix"),
            "errors": sum(1 for i in all_issues if i.level == "error"),
            "warnings": sum(1 for i in all_issues if i.level == "warning"),
        })
