"""
Unit tests for parsing the stays response.

The metric column arrives as text and suppressed cells come back as the
literal string "<10". Getting this wrong silently turns a suppressed cell
into a crash or, worse, into a number.
"""

import numpy as np
import pandas as pd
import pytest

from services.polygon_optimizer import (
    HOURS_IN_DAY,
    OptimizerError,
    _node_id_from_zone_name,
    _v1_base,
    _v2_ondemand_base,
    build_daily_totals,
    build_hourly_matrix,
    parse_metric_column,
    suppression_share,
)

NODE_A = 97097148700
NODE_B = 97098148696


def _hourly_frame(metric="total_wanderers"):
    """A miniature version of the real extraction: full grid, some suppressed."""
    rows = []
    for node in (NODE_A, NODE_B):
        for hour in range(HOURS_IN_DAY):
            if node == NODE_B and hour < 6:
                value = "<10"
            else:
                value = "{:.2f}".format(100.0 + hour)
            rows.append({
                "start_date": "2026-06-22",
                "end_date": "2026-06-22",
                "arrival": hour,
                "sector": node,
                "sector_name": "buffer_{}".format(node),
                metric: value,
            })
    return pd.DataFrame(rows)


# ==========================================
# COLUMN PARSING
# ==========================================

def test_suppressed_cells_become_zero_and_are_flagged():
    series = pd.Series(["9050.75", "<10", "0", "12"])
    values, suppressed = parse_metric_column(series)

    assert values.tolist() == [9050.75, 0.0, 0.0, 12.0]
    assert suppressed.tolist() == [False, True, False, False]


def test_metric_column_arriving_as_text_is_not_coerced_by_dtype():
    # A float dtype would have thrown on "<10"; this must not.
    series = pd.Series(["<10"] * 3, dtype="object")
    values, suppressed = parse_metric_column(series)
    assert values.tolist() == [0.0, 0.0, 0.0]
    assert suppressed.all()


def test_missing_values_count_as_zero_but_not_as_suppression():
    series = pd.Series(["10", None, "abc"])
    values, suppressed = parse_metric_column(series)
    assert values.tolist() == [10.0, 0.0, 0.0]
    # Only the "<10" form is suppression; anything else is just unusable.
    assert suppressed.tolist() == [False, False, False]


# ==========================================
# MATRIX BUILDING
# ==========================================

def test_hourly_matrix_places_every_node_and_hour():
    values, suppressed = build_hourly_matrix(_hourly_frame(), [NODE_A, NODE_B], "total_wanderers")

    assert values.shape == (2, HOURS_IN_DAY)
    assert values[0, 0] == pytest.approx(100.0)
    assert values[0, 23] == pytest.approx(123.0)
    # Node B is suppressed for the first six hours.
    assert values[1, :6].tolist() == [0.0] * 6
    assert suppressed[1, :6].all()
    assert not suppressed[1, 6:].any()
    assert not suppressed[0].any()


def test_missing_combination_is_treated_like_a_suppressed_cell():
    frame = _hourly_frame()
    frame = frame[~((frame["sector"] == NODE_A) & (frame["arrival"] == 12))]

    values, suppressed = build_hourly_matrix(frame, [NODE_A, NODE_B], "total_wanderers")
    assert values[0, 12] == 0.0
    assert suppressed[0, 12]


def test_node_absent_from_the_response_is_fully_suppressed():
    ghost = 99999999999
    values, suppressed = build_hourly_matrix(
        _hourly_frame(), [NODE_A, NODE_B, ghost], "total_wanderers"
    )
    assert values[2].sum() == 0.0
    assert suppressed[2].all()


def test_empty_response_is_fully_suppressed():
    values, suppressed = build_hourly_matrix(pd.DataFrame(), [NODE_A], "total_wanderers")
    assert values.shape == (1, HOURS_IN_DAY)
    assert suppressed.all()


def test_missing_metric_column_is_reported_clearly():
    frame = _hourly_frame().drop(columns=["total_wanderers"])
    with pytest.raises(OptimizerError, match="missing the column"):
        build_hourly_matrix(frame, [NODE_A], "total_wanderers")


def test_daily_totals_sum_each_metric_per_node():
    frame = pd.DataFrame([
        {"sector": NODE_A, "total_wanderers": "1200.5", "total_visitors": "<10",
         "total_passerbys": "3000"},
        {"sector": NODE_B, "total_wanderers": "<10", "total_visitors": "50",
         "total_passerbys": "80"},
    ])
    totals = build_daily_totals(
        frame, [NODE_A, NODE_B], ["total_wanderers", "total_visitors", "total_passerbys"]
    )
    assert totals["total_wanderers"].tolist() == [1200.5, 0.0]
    assert totals["total_visitors"].tolist() == [0.0, 50.0]
    assert totals["total_passerbys"].tolist() == [3000.0, 80.0]


# ==========================================
# SUPPRESSION SHARE
# ==========================================

def test_suppression_share_only_looks_at_the_valid_hours():
    _, suppressed = build_hourly_matrix(_hourly_frame(), [NODE_A, NODE_B], "total_wanderers")

    # Node B is suppressed for hours 0-5, all of which sit outside 6..22.
    assert suppression_share(suppressed, list(range(6, 23))) == pytest.approx(0.0)
    # Hours 3..22 catch three suppressed cells of node B out of forty.
    assert suppression_share(suppressed, list(range(3, 23))) == pytest.approx(3 / 40.0)


def test_suppression_share_of_an_empty_matrix_is_total():
    assert suppression_share(np.zeros((0, HOURS_IN_DAY), dtype=bool), [3]) == 1.0


# ==========================================
# URL AND NAME HELPERS
# ==========================================

def test_urls_are_derived_from_any_stored_root():
    for root in [
        "https://api.claro-br.kidodynamics.com/v1/",
        "https://api.claro-br.kidodynamics.com/v1",
        "https://api.claro-br.kidodynamics.com/v2/",
    ]:
        assert _v1_base(root) == "https://api.claro-br.kidodynamics.com/v1/"
        assert _v2_ondemand_base(root) == "https://api.claro-br.kidodynamics.com/v2/on-demand/"


def test_zone_names_map_back_to_node_ids():
    assert _node_id_from_zone_name("buffer_97097148700") == NODE_A
    assert _node_id_from_zone_name("97097148700") == NODE_A
    assert _node_id_from_zone_name("something else") is None
