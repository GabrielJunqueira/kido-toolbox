"""Unit tests for the projection node file service."""

import gzip
import io
import zipfile

import pandas as pd
import pytest

from services import nodes
from services.nodes import NodeFileError
from services.tiles import node_id_from_xy, tile_bounds, tile_center

# A small synthetic grid around Sao Paulo, mirroring the real file layout.
BASE_X = 97095
BASE_Y = 148698
GRID = 5


def _build_frame():
    rows = []
    for i in range(GRID):
        for j in range(GRID):
            x, y = BASE_X + i, BASE_Y + j
            lon, lat = tile_center(x, y)
            rows.append({
                "Unnamed: 0": len(rows),
                "id": node_id_from_xy(x, y),
                "cusec": "3550308",
                "longitude": lon,
                "latitude": lat,
                "x": x,
                "y": y,
                "z": 18,
            })
    return pd.DataFrame(rows)


def _csv_bytes(df=None):
    df = _build_frame() if df is None else df
    return df.to_csv(index=False).encode("utf-8")


def _zip_bytes(csv_bytes, name="brazil_projection_nodes.csv", extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, csv_bytes)
        if extra:
            archive.writestr(extra, b"not the nodes\n")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Keep every test on its own cache directory and empty registry."""
    monkeypatch.setattr(nodes, "NODE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(nodes, "_registry", {})
    monkeypatch.setattr(nodes, "_frames", {})
    yield


# ==========================================
# CONTAINER DETECTION
# ==========================================

def test_loads_a_plain_csv():
    entry = nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")
    assert entry["rows"] == GRID * GRID
    assert entry["container"] == "csv"


def test_loads_a_gzipped_csv():
    entry = nodes.load_nodes(gzip.compress(_csv_bytes()), "br", "nodes.csv.gz")
    assert entry["rows"] == GRID * GRID
    assert entry["container"] == "gzip"


def test_loads_a_zip_holding_one_csv():
    entry = nodes.load_nodes(_zip_bytes(_csv_bytes()), "br", "nodes.zip")
    assert entry["rows"] == GRID * GRID
    assert entry["container"] == "zip"


def test_container_is_detected_by_content_not_extension():
    # A zip handed over with a .csv name must still be unwrapped.
    entry = nodes.load_nodes(_zip_bytes(_csv_bytes()), "br", "nodes.csv")
    assert entry["container"] == "zip"


def test_zip_with_several_csv_files_is_rejected():
    payload = _zip_bytes(_csv_bytes(), extra="other_nodes.csv")
    with pytest.raises(NodeFileError, match="exactly one CSV"):
        nodes.load_nodes(payload, "br", "nodes.zip")


def test_corrupted_zip_gets_an_actionable_message():
    payload = b"PK\x03\x04" + b"garbage" * 20
    with pytest.raises(NodeFileError, match="corrupted"):
        nodes.load_nodes(payload, "br", "nodes.zip")


def test_upload_above_the_size_limit_is_rejected(monkeypatch):
    monkeypatch.setattr(nodes, "MAX_UPLOAD_BYTES", 128)
    with pytest.raises(NodeFileError, match="above the"):
        nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")


# ==========================================
# CONTENT VALIDATION
# ==========================================

def test_missing_required_column_is_reported_by_name():
    df = _build_frame().drop(columns=["x"])
    with pytest.raises(NodeFileError, match="missing the column"):
        nodes.load_nodes(_csv_bytes(df), "br", "nodes.csv")


def test_wrong_zoom_level_is_rejected():
    df = _build_frame()
    df["z"] = 16
    with pytest.raises(NodeFileError, match="z = "):
        nodes.load_nodes(_csv_bytes(df), "br", "nodes.csv")


def test_cusec_and_index_column_are_not_kept():
    nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")
    df = nodes.read_nodes("br")
    assert set(df.columns) == {"id", "longitude", "latitude", "x", "y"}
    assert str(df["x"].dtype) == "int32"
    assert str(df["longitude"].dtype) == "float32"


# ==========================================
# CACHE BEHAVIOUR
# ==========================================

def test_nothing_is_reported_before_an_upload():
    assert nodes.describe("br") == {"loaded": False, "country_code": "br"}


def test_describe_reports_the_loaded_file():
    nodes.load_nodes(_csv_bytes(), "br", "nodes.zip")
    info = nodes.describe("br")
    assert info["loaded"] is True
    assert info["rows"] == GRID * GRID
    assert info["age_seconds"] >= 0


def test_a_wiped_tmp_directory_looks_like_no_upload(tmp_path):
    entry = nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")
    # The Space hibernated and /tmp was cleared.
    import os
    os.remove(entry["path"])
    assert nodes.describe("br")["loaded"] is False
    with pytest.raises(NodeFileError, match="hibernates"):
        nodes.read_nodes("br")


def test_reading_falls_back_to_the_parquet_cache():
    nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")
    nodes._frames.clear()
    df = nodes.read_nodes("br")
    assert len(df) == GRID * GRID


def test_clear_removes_the_cache():
    nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")
    nodes.clear("br")
    assert nodes.describe("br")["loaded"] is False


# ==========================================
# SPATIAL QUERY
# ==========================================

def test_query_bbox_returns_only_the_tiles_inside_the_box():
    nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")

    # A box spanning the centers of the 2x2 block at the grid origin.
    west, north = tile_center(BASE_X, BASE_Y)
    east, south = tile_center(BASE_X + 1, BASE_Y + 1)

    found = nodes.query_bbox("br", west, south, east, north)
    assert len(found) == 4
    assert set(found["x"]) == {BASE_X, BASE_X + 1}
    assert set(found["y"]) == {BASE_Y, BASE_Y + 1}


def test_query_bbox_is_inclusive_on_tile_edges():
    """
    A box edge landing exactly on a tile boundary pulls in the next tile.
    The tile range is deliberately generous: the caller narrows the result
    with a real point-in-polygon test afterwards.
    """
    nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")

    west, _, _, north = tile_bounds(BASE_X, BASE_Y)
    _, south, east, _ = tile_bounds(BASE_X + 1, BASE_Y + 1)

    found = nodes.query_bbox("br", west, south, east, north)
    assert {(BASE_X + i, BASE_Y + j) for i in range(2) for j in range(2)}.issubset(
        set(zip(found["x"], found["y"]))
    )
    assert len(found) == 9


def test_query_bbox_outside_the_grid_returns_nothing():
    nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")
    found = nodes.query_bbox("br", 2.0, 40.0, 2.1, 40.1)
    assert found.empty


def test_covers_bbox_detects_a_file_from_the_wrong_country():
    nodes.load_nodes(_csv_bytes(), "br", "nodes.csv")
    lon, lat = tile_center(BASE_X, BASE_Y)

    assert nodes.covers_bbox("br", lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01) is True
    # Madrid against a Brazilian node file.
    assert nodes.covers_bbox("br", -3.75, 40.35, -3.65, 40.45) is False
