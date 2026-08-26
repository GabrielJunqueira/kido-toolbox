"""
End-to-end test of the job pipeline against a fake Kido platform.

Exercises the real order — validate, price, create, wait, query, score — plus
the "<10" suppression path, the rejected-zone handling and the final geometry
check, without touching the network.
"""

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import shape

from services import nodes as node_service
from services import polygon_optimizer as optimizer
from services.tiles import lonlat_to_tile, node_id_from_xy, tile_center

# Maracana, Rio de Janeiro.
CENTER_LON, CENTER_LAT = -43.2302, -22.9121
EVENT_HOURS = (19, 20, 21)


@pytest.fixture
def node_file(tmp_path, monkeypatch):
    """A 41x41 synthetic node grid around the venue."""
    monkeypatch.setattr(node_service, "NODE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(node_service, "_registry", {})
    monkeypatch.setattr(node_service, "_frames", {})

    cx, cy = lonlat_to_tile(CENTER_LON, CENTER_LAT)
    rows = []
    for i in range(-20, 21):
        for j in range(-20, 21):
            x, y = cx + i, cy + j
            lon, lat = tile_center(x, y)
            rows.append({"id": node_id_from_xy(x, y), "longitude": lon,
                         "latitude": lat, "x": x, "y": y, "z": 18})

    csv = pd.DataFrame(rows).to_csv(index=False).encode()
    node_service.load_nodes(csv, "br", "nodes.csv")
    return cx, cy


def _input_geojson():
    """A rectangle roughly 300 m on a side around the venue."""
    d = 0.0015
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [CENTER_LON - d, CENTER_LAT - d],
                [CENTER_LON + d, CENTER_LAT - d],
                [CENTER_LON + d, CENTER_LAT + d],
                [CENTER_LON - d, CENTER_LAT + d],
                [CENTER_LON - d, CENTER_LAT - d],
            ]],
        },
    }


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class FakePlatform:
    """
    A stand-in for the Kido API.

    The event lives on the seed nodes plus one deliberately distant node, so
    the run has something real to find. Every zone gets a flat background, and
    a handful of cells come back as the literal "<10" the platform uses for
    suppressed counts.
    """

    def __init__(self, event_extra_nodes=(), reject=()):
        self.event_extra_nodes = set(event_extra_nodes)
        self.reject = set(reject)
        self.created = None
        self.calls = []
        self.seed_ids = set()

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(url)

        if "projects/validate" in url:
            features = [
                f for f in json["features"]
                if f["properties"]["name"] not in self.reject
            ]
            return FakeResponse({
                "valid": True,
                "reason": None,
                "warnings": ["min_num_nodes"] * len(features),
                "rejected_names": sorted(self.reject),
                "polygons": {"type": "FeatureCollection", "features": features},
                "frontend_params": [],
            })

        if "projects/price" in url:
            return FakeResponse({
                "plan_name": "test", "cores": len(json["features"]),
                "peripheries": 0, "days": 1, "total_amount": 0,
            })

        if "projects/create" in url:
            self.created = json
            self.zone_ids = [f["properties"]["id"] for f in json["geojson"]["features"]]
            return FakeResponse({
                "id": "11111111-2222-3333-4444-555555555555",
                "name": json["name"], "internal_name": json["name"],
                "status": "READY", "available_credits": 0,
                "validation_warnings": ["min_num_nodes"] * len(self.zone_ids),
                "geojson": json["geojson"],
            })

        raise AssertionError("unexpected POST to {}".format(url))

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)

        if "projects/" in url and "search_term" in url:
            return FakeResponse({"data": [{"name": url.split("search_term=")[1].split("&")[0],
                                           "status": "READY"}]})

        grouped = [v for k, v in (params or []) if k == "groupby"]
        metrics = [v for k, v in (params or []) if k == "metric"]
        rows = []

        for zone_id in self.zone_ids:
            is_event = zone_id in self.seed_ids or zone_id in self.event_extra_nodes

            if "arrival" in grouped:
                for hour in range(24):
                    value = 40.0
                    if is_event and hour in EVENT_HOURS:
                        value += 900.0
                    # Small counts are suppressed by the platform.
                    cell = "<10" if value < 10 else "{:.2f}".format(value)
                    if hour in (2, 4) and not is_event:
                        cell = "<10"
                    rows.append({"arrival": hour, "sector": zone_id,
                                 "sector_name": "buffer_{}".format(zone_id),
                                 metrics[0]: cell})
            else:
                row = {"sector": zone_id, "sector_name": "buffer_{}".format(zone_id)}
                for metric in metrics:
                    total = 40.0 * 24 + (900.0 * len(EVENT_HOURS) if is_event else 0.0)
                    row[metric] = "{:.2f}".format(total)
                rows.append(row)

        return FakeResponse({"data": rows,
                             "metadata": {"num_records": len(rows), "page_num": 1,
                                          "page_size": len(rows)}})


def _run(monkeypatch, platform, baseline_date=None):
    monkeypatch.setattr(optimizer, "requests", platform)

    request = {
        "token": "fake-token",
        "root_url": "https://api.claro-br.kidodynamics.com/v1/",
        "country_code": "br",
        "geojson": _input_geojson(),
        "event_date": "2026-06-22",
        "baseline_date": baseline_date,
        "buffer_m": 500.0,
        "primary_metric": "total_wanderers",
        "params": {
            "valid_hours": list(range(3, 23)),
            "w_excess": 0.40, "w_similarity": 0.30, "w_peak": 0.15, "w_proximity": 0.15,
            "proximity_length_m": 400.0,
            "fill_neighbour_threshold": 6,
            "min_component_share": 0.05,
            "target_node_count": 10,
            "closing_radius_m": 10.0,
            "simplify_tolerance_m": 5.0,
        },
    }

    job_id = optimizer.create_job(request)

    # The fake platform needs to know which zones are the seeds, which is only
    # known once the nodes have been collected.
    original = optimizer.build_diagnostic_geojson

    def capture(frame):
        platform.seed_ids = {int(v) for v in frame[frame["in_seed"]]["node_id"].values}
        return original(frame)

    monkeypatch.setattr(optimizer, "build_diagnostic_geojson", capture)
    optimizer.run_job(job_id)
    return optimizer.get_job(job_id)


# ==========================================
# HAPPY PATH
# ==========================================

def test_the_pipeline_runs_end_to_end_and_finds_the_distant_node(node_file, monkeypatch):
    cx, cy = node_file
    # A node four tiles away — outside the drawn polygon but inside the 500 m
    # collection radius — that nonetheless recorded the event. This is the
    # case the tool exists for.
    distant = node_id_from_xy(cx + 4, cy)
    platform = FakePlatform(event_extra_nodes=[distant])

    job = _run(monkeypatch, platform)

    assert job["state"] == "done", job["error"]
    result = job["result"]

    # The order of the platform calls is fixed.
    order = [c for c in platform.calls if "projects/" in c or "stays/" in c]
    assert "validate" in order[0]
    assert "price" in order[1]
    assert "create" in order[2]

    # The GeoJSON sent to create is the cleaned one from the validation.
    assert platform.created["is_geoinsight"] is False
    assert platform.created["with_traffic"] is False

    # The window covers the show, widened by an hour on each side.
    assert result["event_window"][0] <= 19
    assert result["event_window"][1] >= 21
    assert result["event_window_source"] == "detected"

    selected_ids = {n["node_id"] for n in result["nodes"] if n["selected"]}
    assert distant in selected_ids, "the distant node that recorded the event must be found"

    summary = result["summary"]
    assert summary["coverage_after"] > summary["coverage_before"]
    assert summary["selected_count"] >= summary["seed_count"]

    # Every step reported a result.
    states = {s["key"]: s["state"] for s in job["steps"]}
    assert states["query_baseline"] == "skipped"
    assert all(v in ("done", "skipped") for v in states.values()), states


def test_the_final_geometry_holds_the_selection_and_nothing_else(node_file, monkeypatch):
    cx, cy = node_file
    platform = FakePlatform(event_extra_nodes=[node_id_from_xy(cx + 4, cy)])
    job = _run(monkeypatch, platform)
    result = job["result"]

    polygon = shape(result["geometry"])
    from shapely.geometry import Point

    for node in result["nodes"]:
        inside = polygon.contains(Point(node["lon"], node["lat"]))
        assert inside == node["selected"], "node {} landed on the wrong side".format(
            node["node_id"]
        )


def test_suppressed_cells_survive_as_coverage_not_as_a_crash(node_file, monkeypatch):
    cx, cy = node_file
    platform = FakePlatform(event_extra_nodes=[node_id_from_xy(cx + 4, cy)])
    job = _run(monkeypatch, platform)

    # Background nodes have hours 2 and 4 suppressed; hour 4 is inside the
    # valid range, so their coverage must be below one but well above zero.
    coverages = [n["coverage_ratio"] for n in job["result"]["nodes"] if not n["in_seed"]]
    assert min(coverages) < 1.0
    assert min(coverages) > 0.9


# ==========================================
# BASELINE MODE
# ==========================================

def test_a_baseline_day_is_queried_and_reported(node_file, monkeypatch):
    cx, cy = node_file
    platform = FakePlatform(event_extra_nodes=[node_id_from_xy(cx + 4, cy)])
    job = _run(monkeypatch, platform, baseline_date="2026-05-25")

    assert job["state"] == "done", job["error"]
    result = job["result"]

    assert result["summary"]["has_baseline"] is True
    assert result["baseline_curve"] is not None
    states = {s["key"]: s["state"] for s in job["steps"]}
    assert states["query_baseline"] == "done"


# ==========================================
# REJECTED ZONES
# ==========================================

def test_zones_rejected_by_the_platform_are_dropped_with_a_warning(node_file, monkeypatch):
    cx, cy = node_file
    distant = node_id_from_xy(cx + 4, cy)
    rejected = ["buffer_{}".format(node_id_from_xy(cx + 8, cy + dy)) for dy in range(3)]
    platform = FakePlatform(event_extra_nodes=[distant], reject=rejected)

    job = _run(monkeypatch, platform)
    assert job["state"] == "done", job["error"]

    codes = [w["code"] for w in job["result"]["warnings"]]
    assert "nodes_rejected_by_platform" in codes

    present = {n["node_id"] for n in job["result"]["nodes"]}
    for name in rejected:
        assert int(name.split("_")[1]) not in present


def test_mass_rejection_stops_the_run_and_blames_the_node_file(node_file, monkeypatch):
    cx, cy = node_file
    all_ids = []
    for i in range(-20, 21):
        for j in range(-20, 21):
            all_ids.append("buffer_{}".format(node_id_from_xy(cx + i, cy + j)))

    platform = FakePlatform(reject=all_ids)
    job = _run(monkeypatch, platform)

    assert job["state"] == "error"
    assert "node file" in job["error"]


# ==========================================
# RESCORE AND MANUAL EDITING
# ==========================================

def test_rescore_uses_a_new_window_without_calling_the_platform(node_file, monkeypatch):
    cx, cy = node_file
    platform = FakePlatform(event_extra_nodes=[node_id_from_xy(cx + 4, cy)])
    job = _run(monkeypatch, platform)

    before = len(platform.calls)
    result = optimizer.score_job(job["job_id"], window_override=(10, 12), finish=False)

    assert len(platform.calls) == before, "rescore must not touch the Kido API"
    assert result["event_window"] == [10, 12]
    assert result["event_window_source"] == "user"


def test_toggling_nodes_rebuilds_the_polygon_around_them(node_file, monkeypatch):
    cx, cy = node_file
    platform = FakePlatform(event_extra_nodes=[node_id_from_xy(cx + 4, cy)])
    job = _run(monkeypatch, platform)

    chosen = [n["node_id"] for n in job["result"]["nodes"] if n["selected"]][:6]
    payload = optimizer.geometry_for_nodes(job["job_id"], chosen)

    assert payload["node_count"] == len(chosen)
    polygon = shape(payload["geometry"])
    from shapely.geometry import Point

    kept = {n["node_id"]: n for n in job["result"]["nodes"]}
    for node_id in chosen:
        node = kept[node_id]
        assert polygon.contains(Point(node["lon"], node["lat"]))


def test_a_hand_drawn_area_reports_the_nodes_it_contains(node_file, monkeypatch):
    cx, cy = node_file
    platform = FakePlatform(event_extra_nodes=[node_id_from_xy(cx + 4, cy)])
    job = _run(monkeypatch, platform)

    found = optimizer.nodes_in_geometry(job["job_id"], _input_geojson())
    seeds = {n["node_id"] for n in job["result"]["nodes"] if n["in_seed"]}
    assert set(found) == seeds
