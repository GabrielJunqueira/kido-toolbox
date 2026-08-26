"""
Web Mercator Tile Service
Math for the z=18 projection node grid used by the Kido platform.

Projection nodes are Mercator tiles at zoom 18. Each node has integer tile
coordinates (x, y) and the latitude/longitude stored in the node file is the
CENTER of the tile, not its corner. Node ids are built as x * 1_000_000 + y.
"""

import math
from typing import List, Tuple

from shapely.geometry import Polygon

# All projection nodes live at this zoom level.
TILE_ZOOM = 18

# Node ids are packed as x * NODE_ID_FACTOR + y.
NODE_ID_FACTOR = 1_000_000

# Circumference of the Earth at the equator, in meters (Web Mercator).
EARTH_CIRCUMFERENCE_M = 40075016.686


def tile_bounds(x: int, y: int, z: int = TILE_ZOOM) -> Tuple[float, float, float, float]:
    """
    Return the geographic bounds of a Mercator tile.

    Args:
        x: Tile column
        y: Tile row (increases southwards)
        z: Zoom level

    Returns:
        Tuple of (west, south, east, north) in EPSG:4326 degrees
    """
    n = 2.0 ** z

    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0

    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))

    return west, south, east, north


def tile_center(x: int, y: int, z: int = TILE_ZOOM) -> Tuple[float, float]:
    """
    Return the (longitude, latitude) of the tile center.

    This is what the `longitude` and `latitude` columns of the node file hold,
    which is why the conversion uses x + 0.5 and y + 0.5.
    """
    n = 2.0 ** z
    lon = (x + 0.5) / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / n))))
    return lon, lat


def lonlat_to_tile(lon: float, lat: float, z: int = TILE_ZOOM) -> Tuple[int, int]:
    """
    Return the tile (x, y) containing a geographic point.

    Latitude is clamped to the Web Mercator limits so that points near the
    poles do not produce out-of-range tile rows.
    """
    n = 2.0 ** z
    lat = max(min(lat, 85.05112878), -85.05112878)

    x = int(math.floor((lon + 180.0) / 360.0 * n))
    lat_rad = math.radians(lat)
    y = int(math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n))

    # Guard against the rightmost/bottom edge landing outside the grid.
    x = max(0, min(int(n) - 1, x))
    y = max(0, min(int(n) - 1, y))
    return x, y


def tile_width_m(lat: float, z: int = TILE_ZOOM) -> float:
    """
    Approximate ground width of a tile, in meters, at a given latitude.

    At z=18 this is about 153 m at the equator, 141 m at 23 degrees,
    117 m at 40 degrees and 76 m at 60 degrees. Used to size tolerances
    that must behave the same way regardless of latitude.
    """
    return EARTH_CIRCUMFERENCE_M * math.cos(math.radians(lat)) / (2.0 ** z)


def node_id_from_xy(x: int, y: int) -> int:
    """Pack tile coordinates into the node id used by the node file."""
    return int(x) * NODE_ID_FACTOR + int(y)


def xy_from_node_id(node_id: int) -> Tuple[int, int]:
    """Unpack a node id back into tile coordinates."""
    node_id = int(node_id)
    return node_id // NODE_ID_FACTOR, node_id % NODE_ID_FACTOR


def tile_polygon(x: int, y: int, z: int = TILE_ZOOM, shrink: float = 1.0) -> Polygon:
    """
    Build the tile square as a shapely Polygon in EPSG:4326.

    Args:
        x: Tile column
        y: Tile row
        z: Zoom level
        shrink: Scale factor around the tile center. 1.0 is the full tile,
                0.8 shrinks it to 80 percent of its side. Shrinking is how
                diagnostic zones guarantee they contain exactly their own node
                and no neighbour, at any latitude.

    Returns:
        Shapely Polygon
    """
    west, south, east, north = tile_bounds(x, y, z)

    if shrink != 1.0:
        cx = (west + east) / 2.0
        cy = (south + north) / 2.0
        half_w = (east - west) / 2.0 * shrink
        half_h = (north - south) / 2.0 * shrink
        west, east = cx - half_w, cx + half_w
        south, north = cy - half_h, cy + half_h

    return Polygon([
        (west, south),
        (east, south),
        (east, north),
        (west, north),
        (west, south),
    ])


def are_adjacent(x1: int, y1: int, x2: int, y2: int) -> bool:
    """
    Return True when two tiles touch under 8-neighbourhood adjacency.

    A tile is not adjacent to itself.
    """
    dx = abs(int(x1) - int(x2))
    dy = abs(int(y1) - int(y2))
    if dx == 0 and dy == 0:
        return False
    return dx <= 1 and dy <= 1


def tile_range_for_bbox(
    west: float,
    south: float,
    east: float,
    north: float,
    z: int = TILE_ZOOM,
) -> Tuple[int, int, int, int]:
    """
    Convert a geographic bounding box into inclusive tile index ranges.

    Returns:
        Tuple of (x_min, x_max, y_min, y_max). Note that tile rows grow
        southwards, so the northern edge produces y_min.
    """
    x_min, y_min = lonlat_to_tile(west, north, z)
    x_max, y_max = lonlat_to_tile(east, south, z)
    return x_min, x_max, y_min, y_max


def neighbours(x: int, y: int) -> List[Tuple[int, int]]:
    """Return the eight tile coordinates surrounding a tile."""
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            out.append((int(x) + dx, int(y) + dy))
    return out
