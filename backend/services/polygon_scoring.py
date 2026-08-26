"""
Event Polygon Scoring Service
The analysis itself: event window detection, per-node metrics, the composite
score, the selection cascade and the final geometry.

Every function here is pure. It takes matrices and parameters and returns
numbers or geometry, with no network and no job state, so each stage can be
tested on its own.
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import shapely.ops
from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import unary_union

from services.geo import get_utm_crs
from services.tiles import tile_polygon, tile_width_m

HOURS_IN_DAY = 24

# Similarity below this marks a node as background noise when measuring the
# local noise floor of the outer ring.
NOISE_SIMILARITY_CEILING = 0.3

# A seed contributing less than this share of the median seed excess is
# flagged for removal, but stays selected: the user drew it.
SEED_DROP_SHARE = 0.02

# Floor an outside candidate has to clear, as a share of the median seed excess.
CANDIDATE_FLOOR_SHARE = 0.10

# The delta has to beat this multiple of its own noise level for the detected
# window to count as a real signal.
WEAK_SIGNAL_MAD_FACTOR = 3.0

# Peak alignment decays to zero this many hours away from the reference peak.
PEAK_ALIGN_TOLERANCE = 4.0

# Interior holes smaller than this many tiles are filled in.
HOLE_TILE_AREA = 2.0

# How many times the geometry cleanup is retried with halved tolerances.
GEOMETRY_RETRIES = 3


# ==========================================
# SMALL STATISTICS HELPERS
# ==========================================

def mad(values: Sequence[float]) -> float:
    """Median absolute deviation, the robust stand-in for a standard deviation."""
    array = np.asarray(values, dtype="float64")
    if array.size == 0:
        return 0.0
    return float(np.median(np.abs(array - np.median(array))))


def robust_z(values: Sequence[float]) -> np.ndarray:
    """
    Standardise with median and MAD instead of mean and standard deviation.

    Node volumes are heavy tailed, so a single busy node would otherwise
    flatten every other z-score.
    """
    array = np.asarray(values, dtype="float64")
    if array.size == 0:
        return array

    median = np.median(array)
    scale = 1.4826 * np.median(np.abs(array - median))
    if scale > 0:
        return (array - median) / scale

    # Every value identical, or almost: fall back to the standard deviation.
    std = float(array.std())
    if std <= 0:
        return np.zeros_like(array)
    return (array - median) / std


def pearson(a: Sequence[float], b: Sequence[float]) -> float:
    """Pearson correlation, returning 0.0 when either side is flat."""
    x = np.asarray(a, dtype="float64")
    y = np.asarray(b, dtype="float64")
    if x.size < 2 or x.size != y.size:
        return 0.0

    x = x - x.mean()
    y = y - y.mean()
    denominator = math.sqrt(float((x * x).sum()) * float((y * y).sum()))
    if denominator <= 0:
        return 0.0
    return float((x * y).sum() / denominator)


def moving_average(values: Sequence[float], window: int = 3) -> np.ndarray:
    """Centred moving average that keeps the array length, clipping at the edges."""
    array = np.asarray(values, dtype="float64")
    if array.size == 0 or window <= 1:
        return array

    half = window // 2
    out = np.empty_like(array)
    for index in range(array.size):
        low = max(0, index - half)
        high = min(array.size, index + half + 1)
        out[index] = array[low:high].mean()
    return out


# ==========================================
# 9.4 EVENT WINDOW DETECTION
# ==========================================

def background_profile(
    matrix: np.ndarray,
    hours: List[int],
    ring_mask: np.ndarray,
) -> Optional[np.ndarray]:
    """
    Estimate the normal hourly shape of the area from its outer ring.

    Returns:
        Array over `hours` summing to 1, or None when the ring is too small
        to be trusted (fewer than ten nodes).
    """
    if ring_mask.sum() < 10:
        return None

    profile = matrix[ring_mask][:, hours].sum(axis=0)
    total = float(profile.sum())
    if total <= 0:
        return None
    return profile / total


def seed_delta(
    matrix: np.ndarray,
    seed_mask: np.ndarray,
    hours: List[int],
    baseline: Optional[np.ndarray] = None,
    scale: float = 1.0,
    profile: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Hourly excess of the seed nodes over what a normal day would look like.

    With a baseline day the reference is that day, rescaled by `scale` so a
    generally busier or quieter day does not shift everything. Without one,
    the reference is the background profile of the outer ring, or the median
    of the curve itself when the ring is too thin.
    """
    curve = matrix[seed_mask][:, hours].sum(axis=0)

    if baseline is not None:
        expected = scale * baseline[seed_mask][:, hours].sum(axis=0)
    elif profile is not None:
        expected = float(curve.sum()) * profile
    else:
        expected = np.full(len(hours), float(np.median(curve)))

    return curve - expected


def volume_scale(
    matrix: np.ndarray,
    baseline: np.ndarray,
    hours: List[int],
) -> float:
    """
    Global correction for the overall volume difference between two days.

    Computed over every candidate, not only the seeds, so the event itself
    does not drive the correction.
    """
    event_total = float(matrix[:, hours].sum())
    baseline_total = float(baseline[:, hours].sum())
    if baseline_total <= 0:
        return 1.0
    return event_total / baseline_total


def detect_event_window(
    delta: np.ndarray,
    hours: List[int],
) -> Tuple[Tuple[int, int], bool, np.ndarray]:
    """
    Find the contiguous stretch of hours that carries the event.

    The delta is smoothed over three hours, the longest run above half the
    peak is taken and widened by an hour on each side.

    Returns:
        Tuple of ((first hour, last hour), signal_is_weak, smoothed delta)
    """
    smoothed = moving_average(delta, 3)

    if smoothed.size == 0:
        return (hours[0], hours[-1]), True, smoothed

    peak = float(smoothed.max())
    if peak <= 0:
        # Nothing rises above the reference at all.
        return (hours[0], hours[-1]), True, smoothed

    above = smoothed >= 0.5 * peak

    best_start, best_length = 0, 0
    run_start, run_length = None, 0
    for index, flag in enumerate(above):
        if flag:
            if run_start is None:
                run_start, run_length = index, 0
            run_length += 1
            if run_length > best_length:
                best_start, best_length = run_start, run_length
        else:
            run_start, run_length = None, 0

    start = max(0, best_start - 1)
    end = min(len(hours) - 1, best_start + best_length - 1 + 1)

    outside = np.array(
        [value for index, value in enumerate(smoothed) if not (start <= index <= end)],
        dtype="float64",
    )
    if outside.size == 0:
        # The whole day reads as "event", so there is no background to measure
        # against. That is a level shift, not an event.
        weak = True
    else:
        noise = mad(outside)
        weak = peak <= WEAK_SIGNAL_MAD_FACTOR * noise if noise > 0 else False

    return (hours[start], hours[end]), weak, smoothed


# ==========================================
# 9.5 PER-NODE METRICS
# ==========================================

def expected_matrix(
    matrix: np.ndarray,
    hours: List[int],
    baseline: Optional[np.ndarray],
    scale: float,
    profile: Optional[np.ndarray],
) -> np.ndarray:
    """
    Per-node expectation of a normal day, restricted to the valid hours.

    Returns:
        Array shaped (nodes, len(hours))
    """
    if baseline is not None:
        return scale * baseline[:, hours]

    totals = matrix[:, hours].sum(axis=1, keepdims=True)
    if profile is None:
        # No usable outer ring: assume a flat day for every node.
        flat = np.full(len(hours), 1.0 / len(hours))
        return totals * flat
    return totals * profile


def compute_node_metrics(
    matrix: np.ndarray,
    hours: List[int],
    window: Tuple[int, int],
    expected: np.ndarray,
    reference: np.ndarray,
    seed_mask: np.ndarray,
    dist_m: np.ndarray,
    suppressed: np.ndarray,
    proximity_length_m: float,
) -> Dict[str, np.ndarray]:
    """
    Compute every per-node signal the score is built from.

    Returns a dict with excess, ratio, similarity, peak_align, proximity,
    coverage_ratio, peak_hour and the node total over the valid hours.
    """
    hour_index = {hour: position for position, hour in enumerate(hours)}
    window_positions = [
        hour_index[h] for h in range(window[0], window[1] + 1) if h in hour_index
    ]
    if not window_positions:
        window_positions = list(range(len(hours)))

    observed = matrix[:, hours]
    residual = observed - expected

    excess = residual[:, window_positions].sum(axis=1)
    window_observed = observed[:, window_positions].sum(axis=1)
    window_expected = expected[:, window_positions].sum(axis=1)
    ratio = window_observed / np.maximum(window_expected, 1.0)

    totals = observed.sum(axis=1)

    # Shape similarity against the reference curve. This is what finds the
    # distant node that is not obvious: a node rising exactly when the show
    # starts carries the same signature at a fraction of the volume.
    similarity = np.array([pearson(residual[i], reference) for i in range(residual.shape[0])])

    seed_totals = totals[seed_mask]
    tau = float(np.median(seed_totals)) / 20.0 if seed_totals.size else 0.0
    if tau > 0:
        similarity = similarity * (totals / (totals + tau))
    # Without the shrinkage above, tiny noisy nodes reach high correlation by
    # chance alone.

    reference_peak = int(np.argmax(reference)) if reference.size else 0
    node_peaks = np.argmax(residual, axis=1)
    peak_align = np.maximum(
        0.0, 1.0 - np.abs(node_peaks - reference_peak) / PEAK_ALIGN_TOLERANCE
    )

    proximity = np.exp(-np.asarray(dist_m, dtype="float64") / max(proximity_length_m, 1.0))

    coverage_ratio = 1.0 - suppressed[:, hours].mean(axis=1)

    peak_hour = np.array([hours[int(p)] for p in node_peaks], dtype="int64")

    return {
        "excess": excess,
        "ratio": ratio,
        "similarity": similarity,
        "peak_align": peak_align,
        "proximity": proximity,
        "coverage_ratio": coverage_ratio,
        "peak_hour": peak_hour,
        "total_window": window_observed,
        "total_hours": totals,
        "residual": residual,
    }


# ==========================================
# 9.6 COMPOSITE SCORE
# ==========================================

def composite_score(
    metrics: Dict[str, np.ndarray],
    weights: Dict[str, float],
) -> Dict[str, np.ndarray]:
    """
    Combine the standardised signals into one score per node.

    Returns the score plus each weighted term, so the interface can say which
    signal drove a node in.
    """
    z_excess = robust_z(np.log1p(np.maximum(metrics["excess"], 0.0)))
    z_similarity = robust_z(metrics["similarity"])
    z_peak = robust_z(metrics["peak_align"])
    z_proximity = robust_z(metrics["proximity"])

    terms = {
        "excess": weights["w_excess"] * z_excess,
        "similarity": weights["w_similarity"] * z_similarity,
        "peak": weights["w_peak"] * z_peak,
        "proximity": weights["w_proximity"] * z_proximity,
    }
    score = terms["excess"] + terms["similarity"] + terms["peak"] + terms["proximity"]

    return {
        "score": score,
        "z_excess": z_excess,
        "z_similarity": z_similarity,
        "z_peak": z_peak,
        "z_proximity": z_proximity,
        "term_excess": terms["excess"],
        "term_similarity": terms["similarity"],
    }


def find_knee(scores: Sequence[float]) -> int:
    """
    Index of the knee of a descending score curve.

    The knee is the point furthest from the straight line joining the first
    and the last point. Returns the last index when the curve is too short
    or perfectly straight, so nothing is cut off by accident.
    """
    values = np.asarray(scores, dtype="float64")
    count = values.size
    if count <= 2:
        return count - 1

    x0, y0 = 0.0, float(values[0])
    x1, y1 = float(count - 1), float(values[-1])
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0:
        return count - 1

    # Signed distance, positive above the chord. The knee of a descending
    # curve is the last point of the high plateau; the absolute distance would
    # instead find the elbow at the bottom of the drop and cut far too deep.
    indices = np.arange(count, dtype="float64")
    above = (dx * (values - y0) - dy * (indices - x0)) / length

    if float(above.max()) <= 1e-12:
        # A straight line has no bend, so nothing is cut off.
        return count - 1
    return int(np.argmax(above))


# ==========================================
# 9.7 SELECTION CASCADE
# ==========================================

def neighbour_lists(xs: Sequence[int], ys: Sequence[int]) -> List[List[int]]:
    """
    Build the 8-neighbourhood adjacency of a set of tiles.

    The node grid is regular, so adjacency is pure arithmetic: two nodes touch
    when their tile indices differ by at most one on each axis.
    """
    lookup = {(int(x), int(y)): index for index, (x, y) in enumerate(zip(xs, ys))}
    result: List[List[int]] = [[] for _ in range(len(lookup))]

    for index, (x, y) in enumerate(zip(xs, ys)):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                other = lookup.get((int(x) + dx, int(y) + dy))
                if other is not None:
                    result[index].append(other)

    return result


def connected_components(selected: np.ndarray, neighbours: List[List[int]]) -> List[List[int]]:
    """Label the connected blocks of the current selection."""
    seen = set()
    components = []

    for start in range(len(selected)):
        if not selected[start] or start in seen:
            continue
        stack = [start]
        seen.add(start)
        component = []
        while stack:
            node = stack.pop()
            component.append(node)
            for other in neighbours[node]:
                if selected[other] and other not in seen:
                    seen.add(other)
                    stack.append(other)
        components.append(sorted(component))

    return components


def select_nodes(
    xs: Sequence[int],
    ys: Sequence[int],
    metrics: Dict[str, np.ndarray],
    scores: Dict[str, np.ndarray],
    seed_mask: np.ndarray,
    ring_mask: np.ndarray,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Decide which nodes make up the optimised polygon.

    A cascade rather than a fixed top-N: seeds first, then an absolute floor
    measured from the local noise, then a knee cut on the score, then spatial
    regularisation, then a minimum size target.

    Returns a dict with the selection mask, the per-node reason, the connected
    components and the warnings raised along the way.
    """
    excess = metrics["excess"]
    similarity = metrics["similarity"]
    score = scores["score"]
    count = len(score)

    selected = np.zeros(count, dtype=bool)
    reason = np.array(["excluded"] * count, dtype=object)
    warnings: List[Dict[str, str]] = []

    seed_excess = excess[seed_mask]
    median_seed_excess = float(np.median(seed_excess)) if seed_excess.size else 0.0

    # --- 1. Seeds -----------------------------------------------------------
    # A seed always stays selected. The tool points at the weak ones, it does
    # not overrule the person who drew the polygon.
    drop_threshold = SEED_DROP_SHARE * median_seed_excess if median_seed_excess > 0 else 0.0
    for index in np.flatnonzero(seed_mask):
        selected[index] = True
        if excess[index] > 0 and excess[index] >= drop_threshold:
            reason[index] = "seed_kept"
        else:
            reason[index] = "seed_dropped"

    # --- 2. Absolute floor for outside candidates ---------------------------
    noise_mask = ring_mask & (similarity < NOISE_SIMILARITY_CEILING) & (~seed_mask)
    noise_floor = 2.0 * mad(excess[noise_mask]) if noise_mask.sum() else 0.0
    floor = max(CANDIDATE_FLOOR_SHARE * median_seed_excess, noise_floor)

    eligible = np.flatnonzero((~seed_mask) & (excess > floor))

    # --- 3. Knee cut on the score curve -------------------------------------
    if eligible.size:
        order = eligible[np.argsort(-score[eligible])]
        knee = find_knee(score[order])
        for position, index in enumerate(order):
            if position > knee:
                continue
            selected[index] = True
            reason[index] = (
                "added_similarity"
                if scores["term_similarity"][index] > scores["term_excess"][index]
                else "added_excess"
            )

    # --- 4. Spatial regularisation ------------------------------------------
    neighbours = neighbour_lists(xs, ys)
    fill_threshold = int(params.get("fill_neighbour_threshold", 6))

    # Hole filling: a gap surrounded by selection is almost certainly part of
    # the same block.
    for index in range(count):
        if selected[index]:
            continue
        if sum(1 for other in neighbours[index] if selected[other]) >= fill_threshold:
            selected[index] = True
            reason[index] = "added_fill"

    # Noise removal: an isolated addition needs strong evidence to survive.
    # Seeds are exempt, for the same reason they are never dropped outright.
    for index in range(count):
        if not selected[index] or seed_mask[index]:
            continue
        if any(selected[other] for other in neighbours[index]):
            continue
        # A node as strong as the typical seed carries seed-level evidence and
        # stays. The comparison is inclusive on purpose: a distant node that
        # behaves exactly like the seeds lands right on the median, and a
        # strict test would throw away the very case this tool exists to find.
        if excess[index] >= median_seed_excess:
            continue
        selected[index] = False
        reason[index] = "excluded"

    # --- 5. Minimum size target ---------------------------------------------
    target = int(params.get("target_node_count", 10))
    if int(selected.sum()) < target:
        added = 0
        while int(selected.sum()) < target:
            adjacent = [
                index for index in range(count)
                if not selected[index] and any(selected[other] for other in neighbours[index])
            ]
            if not adjacent:
                break
            # Recomputed on every pass: each addition opens up a new ring of
            # neighbours, and taking a single snapshot would stop one ring out.
            best = max(adjacent, key=lambda index: score[index])
            selected[best] = True
            reason[best] = "added_to_reach_target"
            added += 1

        if added:
            warnings.append({
                "level": "info",
                "code": "added_to_reach_target",
                "message": (
                    "{} node(s) were added only to reach the {}-node minimum the platform "
                    "recommends for statistical quality. They are not backed by event "
                    "evidence.".format(added, target)
                ),
            })

        if int(selected.sum()) < target:
            warnings.append({
                "level": "warning",
                "code": "below_target",
                "message": (
                    "Only {} nodes could be selected, below the recommended minimum of "
                    "{}. Results for this area will be statistically thin.".format(
                        int(selected.sum()), target
                    )
                ),
            })

    # --- Connected components ------------------------------------------------
    components = connected_components(selected, neighbours)
    positive_excess = np.maximum(excess, 0.0)
    selected_excess = float(positive_excess[selected].sum())

    component_report = []
    min_share = float(params.get("min_component_share", 0.05))
    flagged = np.zeros(count, dtype=bool)

    for component in components:
        share = (
            float(positive_excess[component].sum()) / selected_excess
            if selected_excess > 0 else 0.0
        )
        below = share < min_share and len(components) > 1
        component_report.append({
            "size": len(component),
            "excess_share": round(share, 4),
            "flagged": below,
        })
        if below:
            flagged[component] = True

    if flagged.any():
        warnings.append({
            "level": "warning",
            "code": "weak_component",
            "message": (
                "{} node(s) sit in a detached block carrying less than {:.0%} of the "
                "selected excess. Review them on the map: they are proposed for removal "
                "but were kept, so the decision stays yours.".format(
                    int(flagged.sum()), min_share
                )
            ),
        })

    # --- 6. Upper guard ------------------------------------------------------
    seed_count = int(seed_mask.sum())
    if seed_count and int(selected.sum()) > 3 * seed_count:
        warnings.append({
            "level": "warning",
            "code": "suspicious_expansion",
            "message": (
                "The suggestion holds {} nodes against {} in your polygon, more than a "
                "threefold expansion. Check the input polygon, the event date and the "
                "collection radius before trusting it.".format(int(selected.sum()), seed_count)
            ),
        })

    return {
        "selected": selected,
        "reason": reason,
        "components": component_report,
        "component_flagged": flagged,
        "warnings": warnings,
        "floor": floor,
        "median_seed_excess": median_seed_excess,
    }


# ==========================================
# 9.8 QUALITY METRICS
# ==========================================

def coverage(excess: np.ndarray, mask: np.ndarray) -> float:
    """Share of the total positive event excess captured by a set of nodes."""
    positive = np.maximum(np.asarray(excess, dtype="float64"), 0.0)
    total = float(positive.sum())
    if total <= 0:
        return 0.0
    return float(positive[mask].sum() / total)


# ==========================================
# 9.9 FINAL GEOMETRY
# ==========================================

def build_geometry(
    xs: Sequence[int],
    ys: Sequence[int],
    lons: Sequence[float],
    lats: Sequence[float],
    selected: np.ndarray,
    closing_radius_m: float = 10.0,
    simplify_tolerance_m: float = 5.0,
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """
    Dissolve the selected tiles into the polygon that will be exported.

    Tiles tessellate, so adjacent nodes merge into one seamless block. The
    result is then closed to remove diagonal slits, de-holed and simplified,
    and finally checked in both directions: every selected node has to fall
    inside and no unselected node may. A polygon that drags in an unwanted
    node would silently contaminate the analysis the client runs afterwards,
    so on failure the tolerances are halved and, if that still fails, the raw
    union is returned with a warning.

    Returns:
        Tuple of (GeoJSON geometry dict, warnings)
    """
    warnings: List[Dict[str, str]] = []
    chosen = np.flatnonzero(selected)
    if chosen.size == 0:
        raise ValueError("No nodes are selected, so there is no geometry to build.")

    squares = [tile_polygon(int(xs[i]), int(ys[i])) for i in chosen]
    raw_union = unary_union(squares)

    centre_lat = float(np.mean(np.asarray(lats, dtype="float64")))
    centre_lon = float(np.mean(np.asarray(lons, dtype="float64")))
    utm_crs = get_utm_crs(centre_lat, centre_lon)
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_wgs = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)

    union_utm = shapely.ops.transform(lambda x, y: to_utm.transform(x, y), raw_union)
    tile_area = tile_width_m(centre_lat) ** 2

    closing = float(closing_radius_m)
    tolerance = float(simplify_tolerance_m)

    for attempt in range(GEOMETRY_RETRIES):
        candidate = union_utm
        if closing > 0:
            candidate = candidate.buffer(closing).buffer(-closing)
        candidate = _drop_small_holes(candidate, HOLE_TILE_AREA * tile_area)
        if tolerance > 0:
            candidate = candidate.simplify(tolerance, preserve_topology=True)

        geometry = shapely.ops.transform(lambda x, y: to_wgs.transform(x, y), candidate)
        if _containment_holds(geometry, lons, lats, selected):
            return mapping(geometry), warnings

        closing /= 2.0
        tolerance /= 2.0

    warnings.append({
        "level": "warning",
        "code": "geometry_fallback",
        "message": (
            "The cleaned outline could not keep every selected node in and every other "
            "node out, so the raw union of the tiles was exported instead. The polygon "
            "is correct, only less smooth."
        ),
    })
    return mapping(raw_union), warnings


def _drop_small_holes(geometry: Any, min_area: float) -> Any:
    """Fill interior rings smaller than the given area."""
    from shapely.geometry import MultiPolygon, Polygon

    def clean(polygon):
        interiors = [ring for ring in polygon.interiors if Polygon(ring).area >= min_area]
        return Polygon(polygon.exterior, interiors)

    if geometry.geom_type == "Polygon":
        return clean(geometry)
    if geometry.geom_type == "MultiPolygon":
        return MultiPolygon([clean(part) for part in geometry.geoms])
    return geometry


def _containment_holds(
    geometry: Any,
    lons: Sequence[float],
    lats: Sequence[float],
    selected: np.ndarray,
) -> bool:
    """Check the geometry in both directions against every candidate node."""
    from shapely.geometry import Point

    if geometry.is_empty or not geometry.is_valid:
        return False

    for index in range(len(selected)):
        inside = geometry.contains(Point(float(lons[index]), float(lats[index])))
        if bool(selected[index]) != inside:
            return False
    return True


# ==========================================
# ORCHESTRATION
# ==========================================

# The default weights, and what they become without a baseline day. Excess is
# less trustworthy then, so the shape of the curve carries more.
BASELINE_WEIGHTS = {
    "w_excess": 0.40, "w_similarity": 0.30, "w_peak": 0.15, "w_proximity": 0.15,
}
NO_BASELINE_WEIGHTS = {
    "w_excess": 0.30, "w_similarity": 0.35, "w_peak": 0.20, "w_proximity": 0.15,
}

# A node observed for less than this share of the valid hours is kept in the
# analysis but marked, because its metrics rest on very little.
LOW_CONFIDENCE_COVERAGE = 0.5


def resolve_weights(params: Dict[str, Any], has_baseline: bool) -> Dict[str, float]:
    """
    Pick the score weights, honouring an explicit choice in the Advanced panel.

    Without a baseline the defaults shift towards curve shape, but only when
    the caller left the baseline defaults untouched.
    """
    supplied = {key: float(params.get(key, BASELINE_WEIGHTS[key])) for key in BASELINE_WEIGHTS}
    if has_baseline:
        return supplied

    untouched = all(
        abs(supplied[key] - BASELINE_WEIGHTS[key]) < 1e-9 for key in BASELINE_WEIGHTS
    )
    return dict(NO_BASELINE_WEIGHTS) if untouched else supplied


def analyse(
    frame: Any,
    event_matrix: np.ndarray,
    event_suppressed: np.ndarray,
    baseline_matrix: Optional[np.ndarray],
    event_daily: Optional[Dict[str, np.ndarray]],
    baseline_daily: Optional[Dict[str, np.ndarray]],
    params: Dict[str, Any],
    window_override: Optional[Tuple[int, int]] = None,
    selection_override: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """
    Run the whole analysis and assemble the result payload.

    Args:
        frame: Candidate node table with node_id, x, y, lon, lat, in_seed,
               dist_m and in_outer_ring
        event_matrix: Event day arrivals, shaped (nodes, 24)
        event_suppressed: Suppression mask with the same shape
        baseline_matrix: Baseline day arrivals, or None
        event_daily: Daily totals per metric for the event day
        baseline_daily: Daily totals per metric for the baseline day
        params: Advanced panel values
        window_override: Event window forced by the user
        selection_override: Node ids the user toggled by hand

    Returns:
        The result dict the front end renders.
    """
    hours = sorted({int(h) for h in params.get("valid_hours", range(3, 23)) if 0 <= int(h) < 24})
    if not hours:
        hours = list(range(3, 23))

    seed_mask = frame["in_seed"].values.astype(bool)
    ring_mask = frame["in_outer_ring"].values.astype(bool)
    xs = frame["x"].values
    ys = frame["y"].values
    lons = frame["lon"].values
    lats = frame["lat"].values
    node_ids = [int(v) for v in frame["node_id"].values]
    dist_m = frame["dist_m"].values

    has_baseline = baseline_matrix is not None
    warnings: List[Dict[str, str]] = []

    scale = volume_scale(event_matrix, baseline_matrix, hours) if has_baseline else 1.0
    profile = None if has_baseline else background_profile(event_matrix, hours, ring_mask)

    if not has_baseline and profile is None:
        warnings.append({
            "level": "info",
            "code": "thin_outer_ring",
            "message": (
                "The outer ring has fewer than ten nodes, so the background level was "
                "estimated from the median of the area's own curve. The analysis is "
                "running in reduced mode."
            ),
        })

    # --- Event window --------------------------------------------------------
    delta = seed_delta(event_matrix, seed_mask, hours, baseline_matrix, scale, profile)
    detected_window, weak, smoothed = detect_event_window(delta, hours)

    if window_override:
        window = (int(window_override[0]), int(window_override[1]))
        window_source = "user"
    else:
        window = detected_window
        window_source = "detected"

    if weak:
        warnings.append({
            "level": "warning",
            "code": "weak_event_signal",
            "message": (
                "The event signal barely rises above the normal noise of the area. The "
                "window {}h–{}h was still used, but check the date and the location: "
                "the numbers may not describe an event at all.".format(*detected_window)
            ),
        })

    if 23 in hours:
        warnings.append({
            "level": "info",
            "code": "hour_23_included",
            "message": (
                "Hour 23 is part of the analysis. It is under-counted by construction, "
                "because a stay starting then has little time to reach the minimum "
                "duration before the day ends."
            ),
        })

    # --- Per-node metrics ----------------------------------------------------
    expected = expected_matrix(event_matrix, hours, baseline_matrix, scale, profile)
    reference = smoothed

    metrics = compute_node_metrics(
        event_matrix, hours, window, expected, reference, seed_mask, dist_m,
        event_suppressed, float(params.get("proximity_length_m", 400.0)),
    )

    weights = resolve_weights(params, has_baseline)
    scores = composite_score(metrics, weights)

    # --- Selection -----------------------------------------------------------
    decision = select_nodes(xs, ys, metrics, scores, seed_mask, ring_mask, params)
    selected = decision["selected"]
    reason = decision["reason"]
    warnings.extend(decision["warnings"])

    if selection_override is not None:
        wanted = {int(v) for v in selection_override}
        manual = np.array([node_id in wanted for node_id in node_ids], dtype=bool)
        for index in range(len(selected)):
            if manual[index] and not selected[index]:
                reason[index] = "added_manually"
            elif selected[index] and not manual[index]:
                reason[index] = "removed_manually"
        selected = manual
        decision["components"] = [
            {
                "size": len(component),
                "excess_share": round(
                    float(np.maximum(metrics["excess"], 0.0)[component].sum())
                    / max(float(np.maximum(metrics["excess"], 0.0)[selected].sum()), 1e-9),
                    4,
                ),
                "flagged": False,
            }
            for component in connected_components(selected, neighbour_lists(xs, ys))
        ]

    # --- Quality -------------------------------------------------------------
    excess = metrics["excess"]
    coverage_before = coverage(excess, seed_mask)
    coverage_after = coverage(excess, selected)

    low_confidence = metrics["coverage_ratio"] < LOW_CONFIDENCE_COVERAGE
    if low_confidence.any():
        warnings.append({
            "level": "info",
            "code": "low_confidence_nodes",
            "message": (
                "{} node(s) were observed for less than half of the valid hours because "
                "the platform suppressed their small counts. They are marked in the "
                "audit CSV.".format(int(low_confidence.sum()))
            ),
        })

    # --- Geometry ------------------------------------------------------------
    geometry, geometry_warnings = build_geometry(
        xs, ys, lons, lats, selected,
        float(params.get("closing_radius_m", 10.0)),
        float(params.get("simplify_tolerance_m", 5.0)),
    )
    warnings.extend(geometry_warnings)

    # --- Assemble ------------------------------------------------------------
    order = np.argsort(-scores["score"])
    rank = np.empty(len(order), dtype="int64")
    rank[order] = np.arange(1, len(order) + 1)

    reference_curve = np.zeros(HOURS_IN_DAY, dtype="float64")
    for position, hour in enumerate(hours):
        reference_curve[hour] = float(smoothed[position])

    seed_curve = np.zeros(HOURS_IN_DAY, dtype="float64")
    seed_curve[hours] = event_matrix[seed_mask][:, hours].sum(axis=0)

    baseline_curve = None
    if has_baseline:
        baseline_curve = np.zeros(HOURS_IN_DAY, dtype="float64")
        baseline_curve[hours] = scale * baseline_matrix[seed_mask][:, hours].sum(axis=0)

    daily_event = (event_daily or {})
    daily_baseline = (baseline_daily or {})

    nodes = []
    for index, node_id in enumerate(node_ids):
        nodes.append({
            "node_id": node_id,
            "x": int(xs[index]),
            "y": int(ys[index]),
            "lon": float(lons[index]),
            "lat": float(lats[index]),
            "sector_id": node_id,
            "in_seed": bool(seed_mask[index]),
            "in_outer_ring": bool(ring_mask[index]),
            "dist_m": round(float(dist_m[index]), 1),
            "total_event": round(float(metrics["total_hours"][index]), 2),
            "total_baseline": (
                round(float(daily_baseline.get("total_wanderers", np.zeros(1))[index]), 2)
                if has_baseline and "total_wanderers" in daily_baseline else None
            ),
            "total_event_daily": {
                metric: round(float(values[index]), 2) for metric, values in daily_event.items()
            },
            "excess": round(float(excess[index]), 2),
            "ratio": round(float(metrics["ratio"][index]), 3),
            "similarity": round(float(metrics["similarity"][index]), 3),
            "peak_hour": int(metrics["peak_hour"][index]),
            "peak_align": round(float(metrics["peak_align"][index]), 3),
            "proximity": round(float(metrics["proximity"][index]), 3),
            "coverage_ratio": round(float(metrics["coverage_ratio"][index]), 3),
            "low_confidence": bool(low_confidence[index]),
            "score": round(float(scores["score"][index]), 3),
            "rank": int(rank[index]),
            "selected": bool(selected[index]),
            "reason": str(reason[index]),
            "component_flagged": bool(decision["component_flagged"][index]),
            "hourly_event": [round(float(v), 2) for v in event_matrix[index]],
            "hourly_baseline": (
                [round(float(scale * v), 2) for v in baseline_matrix[index]]
                if has_baseline else None
            ),
        })

    summary = {
        "seed_count": int(seed_mask.sum()),
        "selected_count": int(selected.sum()),
        "added": int((selected & ~seed_mask).sum()),
        "dropped": int(sum(1 for r in reason if r == "seed_dropped")),
        "coverage_before": round(coverage_before, 4),
        "coverage_after": round(coverage_after, 4),
        "leaked_excess": round(1.0 - coverage_after, 4),
        "components": decision["components"],
        "has_baseline": has_baseline,
        "volume_scale": round(float(scale), 4),
        "candidate_count": len(node_ids),
        "eligibility_floor": round(float(decision["floor"]), 2),
        "median_seed_excess": round(float(decision["median_seed_excess"]), 2),
    }

    return {
        "event_window": [int(window[0]), int(window[1])],
        "detected_window": [int(detected_window[0]), int(detected_window[1])],
        "event_window_source": window_source,
        "valid_hours": hours,
        "weights": weights,
        "nodes": nodes,
        "summary": summary,
        "warnings": warnings,
        "reference_curve": [round(float(v), 2) for v in reference_curve],
        "seed_curve": [round(float(v), 2) for v in seed_curve],
        "baseline_curve": (
            [round(float(v), 2) for v in baseline_curve] if baseline_curve is not None else None
        ),
        "geometry": geometry,
    }
