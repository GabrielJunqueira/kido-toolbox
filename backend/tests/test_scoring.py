"""Unit tests for the event window detection, selection cascade and geometry."""

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, shape

from services import polygon_scoring as scoring
from services.tiles import node_id_from_xy, tile_center

HOURS = list(range(3, 23))
BASE_X, BASE_Y = 99590, 148217


def _frame(coords, seed_flags, dist=None, ring=None):
    """Build a candidate table from (x, y) offsets relative to the grid origin."""
    rows = []
    for index, (dx, dy) in enumerate(coords):
        x, y = BASE_X + dx, BASE_Y + dy
        lon, lat = tile_center(x, y)
        rows.append({
            "node_id": node_id_from_xy(x, y),
            "x": x, "y": y, "lon": lon, "lat": lat,
            "in_seed": bool(seed_flags[index]),
            "dist_m": 0.0 if seed_flags[index] else (dist[index] if dist else 200.0),
            "in_outer_ring": bool(ring[index]) if ring else False,
        })
    return pd.DataFrame(rows)


def _flat_day(count, level=100.0):
    return np.full((count, 24), level, dtype="float64")


# ==========================================
# EVENT WINDOW DETECTION
# ==========================================

def test_window_detection_finds_a_synthetic_evening_event():
    count = 20
    event = _flat_day(count)
    baseline = _flat_day(count)
    seed = np.zeros(count, dtype=bool)
    seed[:4] = True

    # A show running from 19:00 to 21:00.
    for hour in (19, 20, 21):
        event[seed, hour] += 1000.0

    scale = scoring.volume_scale(event, baseline, HOURS)
    delta = scoring.seed_delta(event, seed, HOURS, baseline, scale)
    window, weak, _ = scoring.detect_event_window(delta, HOURS)

    # The three-hour smoothing plus the one-hour widening on each side.
    assert window == (18, 22)
    assert weak is False


def _wavy_background(amplitude=10.0):
    """A slow daily wave that survives the three-hour smoothing untouched."""
    return amplitude * np.sin(np.linspace(0, 2 * np.pi, len(HOURS)))


def test_a_bump_no_bigger_than_the_local_noise_is_flagged_as_weak():
    delta = _wavy_background()
    delta[10:13] += 20.0  # only about twice the background swing

    window, weak, _ = scoring.detect_event_window(delta, HOURS)
    assert weak is True, "a bump this small must not be sold as a detected event"
    # The window is still returned, so the run continues with a warning.
    assert HOURS[0] <= window[0] <= window[1] <= HOURS[-1]


def test_a_bump_well_above_the_local_noise_is_not_weak():
    delta = _wavy_background()
    delta[10:13] += 40.0

    window, weak, _ = scoring.detect_event_window(delta, HOURS)
    assert weak is False
    # Hours 13-15 carry the bump; the window widens by one hour on each side.
    assert window == (12, 16)


def test_a_day_that_is_uniformly_high_is_a_level_shift_not_an_event():
    _, weak, _ = scoring.detect_event_window(np.full(len(HOURS), 5.0), HOURS)
    assert weak is True


def test_window_detection_without_a_baseline_uses_the_outer_ring_profile():
    count = 30
    event = _flat_day(count)
    seed = np.zeros(count, dtype=bool)
    seed[:5] = True
    ring = np.zeros(count, dtype=bool)
    ring[15:] = True  # 15 ring nodes, above the ten-node minimum

    for hour in (20, 21):
        event[seed, hour] += 800.0

    profile = scoring.background_profile(event, HOURS, ring)
    assert profile is not None
    assert profile.sum() == pytest.approx(1.0)

    delta = scoring.seed_delta(event, seed, HOURS, profile=profile)
    window, _, _ = scoring.detect_event_window(delta, HOURS)
    assert window[0] <= 20 and window[1] >= 21


def test_a_thin_outer_ring_gives_no_profile():
    count = 12
    ring = np.zeros(count, dtype=bool)
    ring[:9] = True  # one short of the ten-node minimum
    assert scoring.background_profile(_flat_day(count), HOURS, ring) is None


# ==========================================
# SELECTION CASCADE
# ==========================================

def _selection_inputs(count, seed_count, excess, similarity=None, score=None):
    seed = np.zeros(count, dtype=bool)
    seed[:seed_count] = True
    ring = np.zeros(count, dtype=bool)
    ring[seed_count:] = True

    metrics = {
        "excess": np.asarray(excess, dtype="float64"),
        "similarity": np.asarray(
            similarity if similarity is not None else np.zeros(count), dtype="float64"
        ),
    }
    score_values = np.asarray(
        score if score is not None else metrics["excess"], dtype="float64"
    )
    scores = {
        "score": score_values,
        "term_excess": score_values,
        "term_similarity": np.zeros(count),
    }
    return seed, ring, metrics, scores


def test_a_strong_isolated_node_survives_noise_removal():
    # Four seeds in a row, plus one far node carrying more excess than the
    # median seed. That is exactly the distant node the tool exists to find.
    coords = [(0, 0), (1, 0), (2, 0), (3, 0), (20, 20)]
    excess = [100.0, 100.0, 100.0, 100.0, 5000.0]
    seed, ring, metrics, scores = _selection_inputs(5, 4, excess)
    frame = _frame(coords, seed)

    result = scoring.select_nodes(
        frame["x"].values, frame["y"].values, metrics, scores, seed, ring,
        {"fill_neighbour_threshold": 6, "target_node_count": 1},
    )

    assert result["selected"][4], "the strong isolated node must be kept"
    assert result["reason"][4] == "added_excess"


def test_a_weak_isolated_node_is_removed_as_noise():
    coords = [(0, 0), (1, 0), (2, 0), (3, 0), (20, 20)]
    # Above the eligibility floor, but well below the median seed excess.
    excess = [100.0, 100.0, 100.0, 100.0, 30.0]
    seed, ring, metrics, scores = _selection_inputs(5, 4, excess)
    frame = _frame(coords, seed)

    result = scoring.select_nodes(
        frame["x"].values, frame["y"].values, metrics, scores, seed, ring,
        {"fill_neighbour_threshold": 6, "target_node_count": 1},
    )

    assert not result["selected"][4], "the weak isolated node must be dropped"
    assert result["reason"][4] == "excluded"


def test_an_isolated_node_exactly_as_strong_as_the_seeds_survives():
    """
    The canonical case: a far node that behaves exactly like the seeds lands
    right on the median seed excess. A strict comparison would drop it.
    """
    coords = [(0, 0), (1, 0), (2, 0), (3, 0), (20, 20)]
    excess = [100.0, 100.0, 100.0, 100.0, 100.0]
    seed, ring, metrics, scores = _selection_inputs(5, 4, excess)
    frame = _frame(coords, seed)

    result = scoring.select_nodes(
        frame["x"].values, frame["y"].values, metrics, scores, seed, ring,
        {"fill_neighbour_threshold": 6, "target_node_count": 1},
    )

    assert result["selected"][4]


def test_a_seed_with_no_excess_stays_selected_but_is_flagged():
    coords = [(0, 0), (1, 0), (2, 0)]
    excess = [100.0, 100.0, -50.0]
    seed, ring, metrics, scores = _selection_inputs(3, 3, excess)
    frame = _frame(coords, seed)

    result = scoring.select_nodes(
        frame["x"].values, frame["y"].values, metrics, scores, seed, ring,
        {"target_node_count": 1},
    )

    assert result["selected"][2], "the tool never removes a seed on its own"
    assert result["reason"][2] == "seed_dropped"
    assert result["reason"][0] == "seed_kept"


def test_a_hole_surrounded_by_selection_is_filled():
    # A 3x3 block with the middle tile left out.
    coords = [(dx, dy) for dx in range(3) for dy in range(3)]
    middle = coords.index((1, 1))
    excess = [100.0] * 9
    excess[middle] = 0.0

    seed = np.array([index != middle for index in range(9)], dtype=bool)
    ring = np.zeros(9, dtype=bool)
    metrics = {"excess": np.array(excess), "similarity": np.zeros(9)}
    scores = {"score": np.array(excess), "term_excess": np.array(excess),
              "term_similarity": np.zeros(9)}
    frame = _frame(coords, seed)

    result = scoring.select_nodes(
        frame["x"].values, frame["y"].values, metrics, scores, seed, ring,
        {"fill_neighbour_threshold": 6, "target_node_count": 1},
    )

    assert result["selected"][middle]
    assert result["reason"][middle] == "added_fill"


def test_an_over_expanded_selection_raises_the_guard():
    coords = [(dx, 0) for dx in range(12)]
    excess = [1000.0] * 12
    seed, ring, metrics, scores = _selection_inputs(12, 2, excess)
    frame = _frame(coords, seed)

    result = scoring.select_nodes(
        frame["x"].values, frame["y"].values, metrics, scores, seed, ring,
        {"target_node_count": 1},
    )
    codes = [w["code"] for w in result["warnings"]]
    assert "suspicious_expansion" in codes


def test_selection_grows_to_the_target_count():
    coords = [(dx, 0) for dx in range(12)]
    excess = [1000.0, 1000.0] + [1.0] * 10
    seed, ring, metrics, scores = _selection_inputs(12, 2, excess)
    frame = _frame(coords, seed)

    result = scoring.select_nodes(
        frame["x"].values, frame["y"].values, metrics, scores, seed, ring,
        {"target_node_count": 10},
    )

    assert int(result["selected"].sum()) == 10
    assert "added_to_reach_target" in list(result["reason"])


# ==========================================
# GEOMETRY AND THE TWO-WAY CHECK
# ==========================================

def test_two_adjacent_nodes_merge_into_one_seamless_polygon():
    coords = [(0, 0), (1, 0), (10, 10)]
    frame = _frame(coords, [True, True, False])
    selected = np.array([True, True, False])

    geometry, warnings = scoring.build_geometry(
        frame["x"].values, frame["y"].values, frame["lon"].values, frame["lat"].values, selected
    )
    polygon = shape(geometry)

    assert polygon.geom_type == "Polygon", "adjacent tiles must dissolve into one block"
    assert warnings == []
    assert polygon.contains(Point(frame["lon"][0], frame["lat"][0]))
    assert polygon.contains(Point(frame["lon"][1], frame["lat"][1]))
    assert not polygon.contains(Point(frame["lon"][2], frame["lat"][2]))


def test_two_separate_nodes_stay_a_multipolygon():
    coords = [(0, 0), (10, 10)]
    frame = _frame(coords, [True, True])
    selected = np.array([True, True])

    geometry, warnings = scoring.build_geometry(
        frame["x"].values, frame["y"].values, frame["lon"].values, frame["lat"].values, selected
    )
    polygon = shape(geometry)

    assert polygon.geom_type == "MultiPolygon"
    assert warnings == []
    assert len(polygon.geoms) == 2


def test_the_geometry_never_swallows_an_unselected_neighbour():
    # The hardest case: the excluded node touches the selected block.
    coords = [(0, 0), (1, 0), (2, 0), (3, 0)]
    frame = _frame(coords, [True, True, True, False])
    selected = np.array([True, True, True, False])

    geometry, _ = scoring.build_geometry(
        frame["x"].values, frame["y"].values, frame["lon"].values, frame["lat"].values, selected,
        closing_radius_m=10.0, simplify_tolerance_m=5.0,
    )
    polygon = shape(geometry)

    for index in range(4):
        inside = polygon.contains(Point(frame["lon"][index], frame["lat"][index]))
        assert inside == bool(selected[index]), "node {} landed on the wrong side".format(index)


def test_building_a_geometry_with_nothing_selected_is_an_error():
    frame = _frame([(0, 0)], [True])
    with pytest.raises(ValueError, match="No nodes are selected"):
        scoring.build_geometry(
            frame["x"].values, frame["y"].values, frame["lon"].values, frame["lat"].values,
            np.array([False]),
        )


# ==========================================
# QUALITY METRICS AND HELPERS
# ==========================================

def test_coverage_only_counts_positive_excess():
    excess = np.array([100.0, 50.0, -80.0, 50.0])
    seed = np.array([True, False, True, False])
    selected = np.array([True, True, True, False])

    assert scoring.coverage(excess, seed) == pytest.approx(100.0 / 200.0)
    assert scoring.coverage(excess, selected) == pytest.approx(150.0 / 200.0)


def test_the_knee_falls_where_the_curve_bends():
    assert scoring.find_knee([10.0, 9.5, 9.0, 2.0, 1.5, 1.4, 1.3]) == 2
    # A straight line has no bend, so nothing is cut off.
    assert scoring.find_knee([5.0, 4.0, 3.0, 2.0, 1.0]) == 4
    assert scoring.find_knee([3.0, 3.0, 3.0, 3.0]) == 3
    assert scoring.find_knee([1.0]) == 0


def test_weights_shift_when_there_is_no_baseline():
    defaults = dict(scoring.BASELINE_WEIGHTS)
    assert scoring.resolve_weights(defaults, has_baseline=True) == scoring.BASELINE_WEIGHTS
    assert scoring.resolve_weights(defaults, has_baseline=False) == scoring.NO_BASELINE_WEIGHTS

    # An explicit choice in the Advanced panel is respected either way.
    custom = {"w_excess": 0.7, "w_similarity": 0.1, "w_peak": 0.1, "w_proximity": 0.1}
    assert scoring.resolve_weights(custom, has_baseline=False) == custom


def test_similarity_shrinks_towards_zero_for_tiny_nodes():
    hours = HOURS
    count = 6
    event = _flat_day(count, 0.0)
    seed = np.array([True, True, False, False, False, False])

    # Seeds carry a big evening bump; node 2 copies the shape at 1/1000 of the
    # volume, node 3 is flat.
    for hour in (20, 21):
        event[0, hour] = 5000.0
        event[1, hour] = 5000.0
        event[2, hour] = 5.0

    expected = np.zeros((count, len(hours)))
    reference = np.zeros(len(hours))
    for position, hour in enumerate(hours):
        reference[position] = event[seed][:, hour].sum()

    metrics = scoring.compute_node_metrics(
        event, hours, (20, 21), expected, reference, seed,
        np.zeros(count), np.zeros((count, 24), dtype=bool), 400.0,
    )

    # Same shape, but the volume shrinkage keeps it well below the seeds.
    assert metrics["similarity"][2] < metrics["similarity"][0]
    assert metrics["similarity"][2] < 0.5
