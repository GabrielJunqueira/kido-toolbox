"""
Projection Node File Service
Upload, caching and spatial querying of the per-country projection node file.

The node file is too large to version inside the Space (143 MB as CSV), so the
user uploads it once per session. It is normalised, written to a parquet cache
under /tmp and kept in an in-process registry. The Space hibernates, so the
cache can vanish between sessions and the caller must be able to ask for the
file again.
"""

import gzip
import io
import os
import time
import zipfile
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from services.tiles import TILE_ZOOM, tile_range_for_bbox

# Where the normalised parquet caches live. Overridable for tests.
NODE_CACHE_DIR = os.environ.get("KIDO_NODE_CACHE_DIR", "/tmp/kido_nodes")

# Hard ceiling for an uploaded node file.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

# Columns we keep. `cusec` and the unnamed index column are dropped on read.
REQUIRED_COLUMNS = ["id", "longitude", "latitude", "x", "y"]

NODE_DTYPES = {
    "id": "int64",
    "longitude": "float32",
    "latitude": "float32",
    "x": "int32",
    "y": "int32",
}

# Registry of loaded countries: country_code -> metadata dict.
_registry: Dict[str, Dict[str, Any]] = {}

# Most recently used frames, keyed by country code. Bounded to keep the Space
# from holding several 50 MB frames at once.
_frames: Dict[str, pd.DataFrame] = {}
_MAX_CACHED_FRAMES = 2


class NodeFileError(ValueError):
    """Raised when an uploaded node file cannot be used."""


# ==========================================
# DECOMPRESSION
# ==========================================

def _unwrap_upload(file_bytes: bytes, filename: str = "") -> Tuple[bytes, str]:
    """
    Detect the container format by content and return the raw CSV bytes.

    Accepts a zip holding a single csv, a gzipped csv, or a plain csv.
    The filename is only used to improve error messages.

    Returns:
        Tuple of (csv_bytes, detected_format)
    """
    if not file_bytes:
        raise NodeFileError("The uploaded file is empty. Select the node file and try again.")

    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise NodeFileError(
            "The uploaded file is {:.0f} MB, above the {:.0f} MB limit. "
            "Upload the zipped node file instead, it is around 24 MB.".format(
                len(file_bytes) / 1048576, MAX_UPLOAD_BYTES / 1048576
            )
        )

    # ZIP magic number.
    if file_bytes[:4] == b"PK\x03\x04":
        try:
            archive = zipfile.ZipFile(io.BytesIO(file_bytes))
        except zipfile.BadZipFile:
            raise NodeFileError(
                "The zip file '{}' is corrupted and could not be opened. "
                "Download it again and retry.".format(filename or "upload")
            )

        members = [
            n for n in archive.namelist()
            if not n.endswith("/") and not os.path.basename(n).startswith(".")
        ]
        csv_members = [n for n in members if n.lower().endswith((".csv", ".txt"))]

        if len(csv_members) == 1:
            target = csv_members[0]
        elif len(members) == 1:
            target = members[0]
        elif not members:
            raise NodeFileError("The zip file is empty. It must contain one CSV with the nodes.")
        else:
            raise NodeFileError(
                "The zip file holds {} files ({}). It must contain exactly one CSV.".format(
                    len(members), ", ".join(members[:5])
                )
            )

        return archive.read(target), "zip"

    # GZIP magic number.
    if file_bytes[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(file_bytes), "gzip"
        except OSError:
            raise NodeFileError(
                "The gzip file '{}' is corrupted and could not be decompressed.".format(
                    filename or "upload"
                )
            )

    return file_bytes, "csv"


# ==========================================
# PARSING AND VALIDATION
# ==========================================

def _resolve_columns(csv_bytes: bytes) -> Dict[str, str]:
    """
    Map the required column names onto the actual header of the file.

    Returns:
        Dict of required_name -> actual_header_name

    Raises:
        NodeFileError when a required column is missing.
    """
    try:
        header = pd.read_csv(io.BytesIO(csv_bytes), nrows=0)
    except Exception as exc:
        raise NodeFileError(
            "The file could not be read as CSV ({}). Expected a comma separated "
            "file with columns id, longitude, latitude, x, y.".format(exc)
        )

    lookup = {}
    for actual in header.columns:
        lookup[str(actual).strip().lower()] = actual

    mapping = {}
    missing = []
    for required in REQUIRED_COLUMNS:
        if required in lookup:
            mapping[required] = lookup[required]
        else:
            missing.append(required)

    if missing:
        raise NodeFileError(
            "The node file is missing the column(s) {}. Found: {}. "
            "Use the projection node export, which has id, cusec, longitude, "
            "latitude, x, y and z.".format(
                ", ".join(missing), ", ".join(str(c) for c in header.columns)
            )
        )

    if "z" in lookup:
        mapping["z"] = lookup["z"]

    return mapping


def _read_nodes_csv(csv_bytes: bytes) -> pd.DataFrame:
    """Read the node CSV into a lean frame, validating z along the way."""
    mapping = _resolve_columns(csv_bytes)
    usecols = list(mapping.values())
    dtype = {mapping[k]: v for k, v in NODE_DTYPES.items()}
    if "z" in mapping:
        dtype[mapping["z"]] = "int16"

    try:
        df = pd.read_csv(io.BytesIO(csv_bytes), usecols=usecols, dtype=dtype)
    except ValueError as exc:
        raise NodeFileError(
            "The node file has unexpected values in id, x, y, longitude or "
            "latitude ({}). Those columns must be numeric.".format(exc)
        )

    df = df.rename(columns={v: k for k, v in mapping.items()})

    if "z" in df.columns:
        levels = df["z"].dropna().unique()
        if len(levels) != 1 or int(levels[0]) != TILE_ZOOM:
            raise NodeFileError(
                "The node file has z = {} but this tool only works with the "
                "z = {} projection grid.".format(sorted(int(v) for v in levels), TILE_ZOOM)
            )
        df = df.drop(columns=["z"])

    df = df.dropna(subset=REQUIRED_COLUMNS)
    if df.empty:
        raise NodeFileError("The node file has no usable rows after dropping empty coordinates.")

    return df.reset_index(drop=True)


# ==========================================
# CACHE
# ==========================================

def _parquet_path(country_code: str) -> str:
    return os.path.join(NODE_CACHE_DIR, "{}.parquet".format(country_code.lower().strip()))


def _remember_frame(country_code: str, df: pd.DataFrame) -> None:
    _frames[country_code] = df
    while len(_frames) > _MAX_CACHED_FRAMES:
        oldest = next(iter(_frames))
        if oldest == country_code:
            break
        _frames.pop(oldest, None)


def load_nodes(file_bytes: bytes, country_code: str, filename: str = "") -> Dict[str, Any]:
    """
    Parse an uploaded node file, cache it as parquet and register it.

    Args:
        file_bytes: Raw upload bytes (zip, gzip or plain CSV)
        country_code: Two-letter country code the file belongs to
        filename: Original file name, used in error messages only

    Returns:
        Registry entry dict with path, rows, uploaded_at and bbox
    """
    country_code = country_code.lower().strip()
    csv_bytes, container = _unwrap_upload(file_bytes, filename)
    df = _read_nodes_csv(csv_bytes)

    os.makedirs(NODE_CACHE_DIR, exist_ok=True)
    path = _parquet_path(country_code)
    df.to_parquet(path, index=False)

    entry = {
        "country_code": country_code,
        "path": path,
        "rows": int(len(df)),
        "uploaded_at": time.time(),
        "filename": filename,
        "container": container,
        "bbox": [
            float(df["longitude"].min()),
            float(df["latitude"].min()),
            float(df["longitude"].max()),
            float(df["latitude"].max()),
        ],
    }
    _registry[country_code] = entry
    _remember_frame(country_code, df)
    return entry


def get_entry(country_code: str) -> Optional[Dict[str, Any]]:
    """
    Return the registry entry for a country, or None when nothing is cached.

    The parquet file is checked too: the Space hibernates and wipes /tmp while
    the registry may still hold a stale entry.
    """
    country_code = country_code.lower().strip()
    entry = _registry.get(country_code)
    if entry is None:
        return None
    if not os.path.exists(entry["path"]):
        _registry.pop(country_code, None)
        _frames.pop(country_code, None)
        return None
    return entry


def describe(country_code: str) -> Dict[str, Any]:
    """Return a UI-friendly description of the cached node file."""
    entry = get_entry(country_code)
    if entry is None:
        return {"loaded": False, "country_code": country_code.lower().strip()}
    return {
        "loaded": True,
        "country_code": entry["country_code"],
        "rows": entry["rows"],
        "bbox": entry["bbox"],
        "age_seconds": max(0.0, time.time() - entry["uploaded_at"]),
        "filename": entry.get("filename", ""),
    }


def read_nodes(country_code: str) -> pd.DataFrame:
    """
    Return the full node frame for a country.

    Raises:
        NodeFileError when no node file is cached for that country.
    """
    country_code = country_code.lower().strip()
    entry = get_entry(country_code)
    if entry is None:
        raise NodeFileError(
            "No node file is loaded for {}. The Space hibernates and clears its "
            "temporary storage, so the file has to be uploaded again.".format(
                country_code.upper()
            )
        )

    df = _frames.get(country_code)
    if df is None:
        df = pd.read_parquet(entry["path"])
        _remember_frame(country_code, df)
    return df


def clear(country_code: str) -> None:
    """Drop the cached node file for a country."""
    country_code = country_code.lower().strip()
    entry = _registry.pop(country_code, None)
    _frames.pop(country_code, None)
    if entry and os.path.exists(entry["path"]):
        try:
            os.remove(entry["path"])
        except OSError:
            pass


# ==========================================
# SPATIAL QUERY
# ==========================================

def query_bbox(
    country_code: str,
    west: float,
    south: float,
    east: float,
    north: float,
) -> pd.DataFrame:
    """
    Return the nodes whose tile falls inside a geographic bounding box.

    The node grid is regular, so the box is converted into tile index ranges
    and filtered numerically. That beats any spatial index at this size.
    """
    df = read_nodes(country_code)
    x_min, x_max, y_min, y_max = tile_range_for_bbox(west, south, east, north)

    x = df["x"].values
    y = df["y"].values
    mask = (x >= x_min) & (x <= x_max) & (y >= y_min) & (y <= y_max)
    return df[mask].reset_index(drop=True)


def covers_bbox(
    country_code: str,
    west: float,
    south: float,
    east: float,
    north: float,
) -> bool:
    """Return True when the cached node file overlaps the given bounding box."""
    entry = get_entry(country_code)
    if entry is None:
        return False
    n_west, n_south, n_east, n_north = entry["bbox"]
    return not (east < n_west or west > n_east or north < n_south or south > n_north)
