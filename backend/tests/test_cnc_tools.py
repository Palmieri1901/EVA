"""CNC multi-tool feature tests.

Coverage:
  - GET /api/tools returns 4 tools (FUGA, CONTORNO, TAGLIO, SVASO) with full settings
  - PUT /api/tools persists modifications (round-trip via GET)
  - POST /api/projects/{id}/export produces a 4-layer DXF with configured colors
  - POST /api/boats/{id}/nested-dxf produces the 4-layer DXF
  - POST /api/projects/{id}/export/dxf, /api/boats/{id}/export/dxf & legacy svg/pdf
  - PATCH /api/projects/{id} accepts elements[].tool field
"""
from __future__ import annotations

import io
import os
import uuid
import pytest
import requests
import ezdxf

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://tappo-dxf.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

EXISTING_BOAT_ID = "6a849a5fd824444bccd581e5"
EXISTING_PROJECT_ID = "6a849a7dd824444bccd581e6"
TOOL_IDS = ["FUGA", "CONTORNO", "TAGLIO", "SVASO"]
TOOL_KEYS = {"id", "name", "color_aci", "color_hex", "depth_mm",
             "feed_mm_min", "spindle_rpm", "tool_no", "bit_diameter_mm", "passes"}


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _download_dxf(client, url):
    if url.startswith("/"):
        url = BASE_URL + url
    r = client.get(url, timeout=60)
    assert r.status_code == 200, f"file download failed: {r.status_code} {r.text[:200]}"
    return ezdxf.read(io.StringIO(r.content.decode("utf-8")))


# ----- /api/tools --------------------------------------------------------
class TestTools:
    def test_get_tools_returns_4_defaults(self, api_client):
        r = api_client.get(f"{API}/tools")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "tools" in data
        tools = data["tools"]
        assert len(tools) == 4
        ids = [t["id"] for t in tools]
        assert set(ids) == set(TOOL_IDS)
        for t in tools:
            missing = TOOL_KEYS - set(t.keys())
            assert not missing, f"missing keys on {t.get('id')}: {missing}"
            assert isinstance(t["color_hex"], str) and t["color_hex"].startswith("#")
            assert isinstance(t["color_aci"], int) and 1 <= t["color_aci"] <= 255
            assert t["depth_mm"] > 0 and t["feed_mm_min"] > 0 and t["spindle_rpm"] > 0
            assert t["bit_diameter_mm"] > 0 and t["passes"] >= 1

    def test_put_tools_persists(self, api_client):
        # snapshot
        original = api_client.get(f"{API}/tools").json()["tools"]
        modified = [dict(t) for t in original]
        for t in modified:
            if t["id"] == "FUGA":
                t["depth_mm"] = 3.7
                t["feed_mm_min"] = 3123.0
                t["color_aci"] = 4
                t["color_hex"] = "#06B6D4"
        r = api_client.put(f"{API}/tools", json={"tools": modified})
        assert r.status_code == 200, r.text
        # round-trip GET
        r2 = api_client.get(f"{API}/tools").json()["tools"]
        fuga = next(t for t in r2 if t["id"] == "FUGA")
        assert abs(fuga["depth_mm"] - 3.7) < 1e-6
        assert abs(fuga["feed_mm_min"] - 3123.0) < 1e-6
        assert fuga["color_aci"] == 4
        # restore
        rr = api_client.put(f"{API}/tools", json={"tools": original})
        assert rr.status_code == 200
        fuga_r = next(t for t in api_client.get(f"{API}/tools").json()["tools"] if t["id"] == "FUGA")
        assert abs(fuga_r["depth_mm"] - 2.0) < 1e-6
        assert abs(fuga_r["feed_mm_min"] - 2500.0) < 1e-6


# ----- Exports produce 4-layer DXF --------------------------------------
def _assert_four_layers(doc, tools):
    layer_names = {l.dxf.name for l in doc.layers}
    for tid in TOOL_IDS:
        assert tid in layer_names, f"missing layer {tid}; got {layer_names}"
    aci_by_id = {t["id"]: int(t["color_aci"]) for t in tools}
    for tid in TOOL_IDS:
        layer = doc.layers.get(tid)
        assert layer.color == aci_by_id[tid], f"{tid} color {layer.color} != {aci_by_id[tid]}"


class TestExports:
    def test_project_export_single_piece_dxf(self, api_client):
        r = api_client.post(f"{API}/projects/{EXISTING_PROJECT_ID}/export")
        assert r.status_code == 200, r.text
        j = r.json()
        assert "dxf_url" in j and j["size"] > 0
        tools = api_client.get(f"{API}/tools").json()["tools"]
        doc = _download_dxf(api_client, j["dxf_url"])
        _assert_four_layers(doc, tools)
        # SVASO must have at least the outer perimeter polyline
        msp = doc.modelspace()
        by_layer = {tid: 0 for tid in TOOL_IDS}
        for e in msp.query("LWPOLYLINE"):
            if e.dxf.layer in by_layer:
                by_layer[e.dxf.layer] += 1
        assert by_layer["SVASO"] >= 1, f"expected outer perimeter on SVASO, counts={by_layer}"

    def test_project_export_dxf_format(self, api_client):
        r = api_client.post(f"{API}/projects/{EXISTING_PROJECT_ID}/export/dxf", json={})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ext"] == "dxf" and j["size"] > 0
        tools = api_client.get(f"{API}/tools").json()["tools"]
        doc = _download_dxf(api_client, j["url"])
        _assert_four_layers(doc, tools)

    def test_project_export_svg_still_works(self, api_client):
        r = api_client.post(f"{API}/projects/{EXISTING_PROJECT_ID}/export/svg", json={})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ext"] == "svg" and j["size"] > 0

    def test_project_export_pdf_still_works(self, api_client):
        r = api_client.post(f"{API}/projects/{EXISTING_PROJECT_ID}/export/pdf", json={})
        assert r.status_code == 200, r.text
        assert r.json()["ext"] == "pdf"

    def test_boat_nested_dxf_four_layers(self, api_client):
        r = api_client.post(f"{API}/boats/{EXISTING_BOAT_ID}/nested-dxf")
        assert r.status_code == 200, r.text
        j = r.json()
        assert "dxf_url" in j and j["size"] > 0 and j["count"] >= 1
        tools = api_client.get(f"{API}/tools").json()["tools"]
        doc = _download_dxf(api_client, j["dxf_url"])
        _assert_four_layers(doc, tools)

    def test_boat_export_dxf_four_layers(self, api_client):
        r = api_client.post(f"{API}/boats/{EXISTING_BOAT_ID}/export/dxf", json={})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ext"] == "dxf"
        tools = api_client.get(f"{API}/tools").json()["tools"]
        doc = _download_dxf(api_client, j["url"])
        _assert_four_layers(doc, tools)


# ----- Element.tool via PATCH ------------------------------------------
class TestElementToolPatch:
    """Uses a throwaway boat + piece (not the real user data)."""

    @pytest.fixture(scope="class")
    def throwaway_project(self, api_client):
        # create boat + project
        b = api_client.post(f"{API}/boats", json={"name": f"TEST_CNC_{uuid.uuid4().hex[:6]}"})
        assert b.status_code == 200, b.text
        boat_id = b.json()["id"]
        p = api_client.post(f"{API}/projects", json={
            "name": "TEST_piece", "boat_id": boat_id, "piece_name": "TEST_p1",
            "ref_width_mm": 400, "ref_height_mm": 300,
        })
        assert p.status_code == 200, p.text
        pid = p.json()["id"]
        yield {"boat_id": boat_id, "project_id": pid}
        # cleanup
        try:
            api_client.delete(f"{API}/boats/{boat_id}")
        except Exception:
            pass

    def test_patch_element_tool_persists(self, api_client, throwaway_project):
        pid = throwaway_project["project_id"]
        elements = [
            {"id": "e1", "type": "text", "layer": "ENGRAVE", "tool": "CONTORNO",
             "polylines": [[[0, 0], [10, 0], [10, 10], [0, 10]]], "params": {}},
            {"id": "e2", "type": "fill", "layer": "ENGRAVE", "tool": "FUGA",
             "polylines": [[[0, 0], [50, 0]]], "params": {}},
            {"id": "e3", "type": "polyline", "layer": "CUT", "tool": "TAGLIO",
             "polylines": [[[5, 5], [8, 8]]], "params": {}},
            {"id": "e4", "type": "polyline", "layer": "CUT", "tool": "SVASO",
             "polylines": [[[1, 1], [2, 2]]], "params": {}},
        ]
        # give it a contour so exports work later if needed
        contour = [[0, 0], [400, 0], [400, 300], [0, 300]]
        r = api_client.patch(f"{API}/projects/{pid}",
                             json={"contour_mm": contour, "elements": elements})
        assert r.status_code == 200, r.text
        saved = r.json()
        by_id = {e["id"]: e for e in saved["elements"]}
        assert by_id["e1"]["tool"] == "CONTORNO"
        assert by_id["e2"]["tool"] == "FUGA"
        assert by_id["e3"]["tool"] == "TAGLIO"
        assert by_id["e4"]["tool"] == "SVASO"
        # GET to verify persistence
        got = api_client.get(f"{API}/projects/{pid}").json()
        by_id2 = {e["id"]: e for e in got["elements"]}
        for k in ("e1", "e2", "e3", "e4"):
            assert by_id2[k]["tool"] == by_id[k]["tool"]

    def test_export_routes_elements_by_tool(self, api_client, throwaway_project):
        pid = throwaway_project["project_id"]
        r = api_client.post(f"{API}/projects/{pid}/export")
        assert r.status_code == 200, r.text
        doc = _download_dxf(api_client, r.json()["dxf_url"])
        counts = {tid: 0 for tid in TOOL_IDS}
        for e in doc.modelspace().query("LWPOLYLINE"):
            if e.dxf.layer in counts:
                counts[e.dxf.layer] += 1
        # e1->CONTORNO, e2->FUGA, e3->TAGLIO, e4->SVASO (+outer contour->SVASO)
        assert counts["CONTORNO"] >= 1
        assert counts["FUGA"] >= 1
        assert counts["TAGLIO"] >= 1
        assert counts["SVASO"] >= 2  # outer perimeter + explicit e4
