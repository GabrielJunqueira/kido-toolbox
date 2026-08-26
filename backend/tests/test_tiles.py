"""Unit tests for the z=18 Mercator tile math."""

import math

import pytest

from services.tiles import (
    TILE_ZOOM,
    are_adjacent,
    lonlat_to_tile,
    neighbours,
    node_id_from_xy,
    tile_bounds,
    tile_center,
    tile_polygon,
    tile_range_for_bbox,
    tile_width_m,
    xy_from_node_id,
)

# Node id taken from a real production stays extraction, where the `sector`
# column came back as 97097148700 with name buffer_97097148700.
SAMPLE_NODE_ID = 97097148700
SAMPLE_X = 97097
SAMPLE_Y = 148700


def test_node_id_packing_matches_the_node_file_convention():
    assert node_id_from_xy(SAMPLE_X, SAMPLE_Y) == SAMPLE_NODE_ID
    assert xy_from_node_id(SAMPLE_NODE_ID) == (SAMPLE_X, SAMPLE_Y)


def test_world_tile_covers_the_whole_mercator_extent():
    west, south, east, north = tile_bounds(0, 0, z=0)
    assert west == pytest.approx(-180.0)
    assert east == pytest.approx(180.0)
    assert north == pytest.approx(85.0511287798, abs=1e-6)
    assert south == pytest.approx(-85.0511287798, abs=1e-6)


def test_tile_bounds_are_ordered_and_contain_the_center():
    west, south, east, north = tile_bounds(SAMPLE_X, SAMPLE_Y)
    lon, lat = tile_center(SAMPLE_X, SAMPLE_Y)

    assert west < east
    assert south < north
    assert west < lon < east
    assert south < lat < north

    # The stored center must be the x + 0.5 / y + 0.5 point of the tile.
    assert lon == pytest.approx((west + east) / 2.0)


def test_tile_center_round_trips_back_to_the_same_tile():
    for x, y in [(SAMPLE_X, SAMPLE_Y), (0, 0), (131072, 131072), (262143, 200000)]:
        lon, lat = tile_center(x, y)
        assert lonlat_to_tile(lon, lat) == (x, y)


def test_tile_width_matches_the_documented_calibration_table():
    assert tile_width_m(0) == pytest.approx(153, abs=1)
    assert tile_width_m(23) == pytest.approx(141, abs=1)
    assert tile_width_m(40) == pytest.approx(117, abs=1)
    assert tile_width_m(60) == pytest.approx(76, abs=1)


def test_sample_node_sits_at_the_expected_latitude_and_tile_size():
    lon, lat = tile_center(SAMPLE_X, SAMPLE_Y)
    # Sao Paulo, around 23.5 degrees south.
    assert -47.0 < lon < -46.0
    assert -24.0 < lat < -23.0
    assert tile_width_m(lat) == pytest.approx(140, abs=2)


def test_shrunk_tile_polygon_stays_inside_the_full_tile():
    full = tile_polygon(SAMPLE_X, SAMPLE_Y)
    shrunk = tile_polygon(SAMPLE_X, SAMPLE_Y, shrink=0.8)

    assert full.contains(shrunk)
    # Area scales with the square of the shrink factor.
    assert shrunk.area == pytest.approx(full.area * 0.64, rel=1e-6)

    # A shrunk zone must not reach any neighbouring tile.
    for nx, ny in neighbours(SAMPLE_X, SAMPLE_Y):
        assert not shrunk.intersects(tile_polygon(nx, ny, shrink=0.8))


def test_adjacency_uses_the_eight_neighbourhood():
    assert are_adjacent(10, 10, 11, 11) is True
    assert are_adjacent(10, 10, 10, 11) is True
    assert are_adjacent(10, 10, 12, 10) is False
    assert are_adjacent(10, 10, 10, 10) is False
    assert len(neighbours(10, 10)) == 8


def test_tile_range_for_bbox_brackets_the_tiles_inside_it():
    west, south, east, north = tile_bounds(SAMPLE_X, SAMPLE_Y)
    # Grow the box by roughly two tiles on each side.
    pad = (east - west) * 2
    x_min, x_max, y_min, y_max = tile_range_for_bbox(
        west - pad, south - pad, east + pad, north + pad
    )

    assert x_min <= SAMPLE_X <= x_max
    assert y_min <= SAMPLE_Y <= y_max
    # Tile rows grow southwards, so the range must still be ordered.
    assert y_min < y_max
    assert x_min < x_max


def test_default_zoom_is_the_projection_node_zoom():
    assert TILE_ZOOM == 18
    assert tile_bounds(SAMPLE_X, SAMPLE_Y) == tile_bounds(SAMPLE_X, SAMPLE_Y, z=18)
