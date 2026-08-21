"""Iteration 15 backend tests: per-tool G-code + BORDO tool + bordo/fuga split.

Covers:
- GET /api/tools returns 5 tools including BORDO (cyan #06B6D4, aci 4)
- POST /api/projects/{id}/export/gcode returns G-code sectioned per tool
  (M6 T<n>, M3 S<rpm>, M5 between tool changes, per-tool feed/depth)
- POST /api/boats/{boat_id}/export/gcode (nested) produces the same tool-sectioned G-code
- POST /api/boats/{boat_id}/nested-dxf and POST /api/projects/{id}/export
  produce DXF with correct per-tool layers (including BORDO when present)
- Element.tool='BORDO' routes to the BORDO layer in DXF export
"""
import os
import re
import io
import uuid
import requests
import pytest
import ezdxf

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://tappo-dxf.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

RECT_CONTOUR = [[0, 0], [600, 0], [600, 400], [0, 400], [0, 0]]


def _abs(url: str) -> str:
    """Backend sometimes returns relative /api/files/... URLs — prepend BASE_URL."""
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return BASE_URL + url


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


@pytest.fixture(scope="module")
def throwaway_boat(s):
    r = s.post(f"{API}/boats", json={"name": f"TEST_iter15_{uuid.uuid4().hex[:6]}"})
    assert r.status_code in (200, 201), r.text
    boat = r.json()
    boat_id = boat["id"]
    yield boat_id
    try:
        s.delete(f"{API}/boats/{boat_id}")
    except Exception:
        pass


@pytest.fixture(scope="module")
def throwaway_piece(s, throwaway_boat):
    # create a project attached to the boat
    r = s.post(f"{API}/projects", json={"name": "TEST_iter15_piece", "boat_id": throwaway_boat})
    assert r.status_code in (200, 201), r.text
    proj = r.json()
    pid = proj["id"]
    # patch a rectangular contour so exports have geometry
    r2 = s.patch(f"{API}/projects/{pid}", json={"contour_mm": RECT_CONTOUR, "boat_id": throwaway_boat})
    assert r2.status_code == 200, r2.text
    yield pid


# ---------- GET /api/tools with BORDO ----------
class TestToolsList:
    def test_five_tools_including_bordo(self, s):
        r = s.get(f"{API}/tools")
        assert r.status_code == 200
        body = r.json()
        tools = body.get("tools") if isinstance(body, dict) else body
        ids = [t["id"] for t in tools]
        assert set(ids) >= {"FUGA", "BORDO", "CONTORNO", "TAGLIO", "SVASO"}
        bordo = next(t for t in tools if t["id"] == "BORDO")
        assert bordo["color_hex"].upper() == "#06B6D4"
        assert int(bordo["color_aci"]) == 4
        assert bordo["tool_no"]  # e.g. T5


# ---------- BORDO element -> BORDO layer in DXF ----------
class TestBordoElementRoutesToLayer:
    def test_element_tool_bordo_creates_bordo_layer_polyline(self, s, throwaway_piece):
        # Add a fill element with tool=BORDO to the piece
        square = [[50, 50], [550, 50], [550, 350], [50, 350], [50, 50]]
        el = {
            "id": uuid.uuid4().hex,
            "type": "fill",
            "layer": "ENGRAVE",
            "tool": "BORDO",
            "polylines": [square],
            "params": {"role": "border"},
        }
        r = s.patch(f"{API}/projects/{throwaway_piece}", json={"elements": [el]})
        assert r.status_code == 200, r.text
        # verify persisted
        g = s.get(f"{API}/projects/{throwaway_piece}")
        assert g.status_code == 200
        got_els = g.json().get("elements") or []
        assert any(x.get("tool") == "BORDO" for x in got_els)

        # export DXF and validate layer routing
        r = s.post(f"{API}/projects/{throwaway_piece}/export/dxf", json={})
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        raw = requests.get(_abs(url)).content
        doc = ezdxf.read(io.StringIO(raw.decode("utf-8")))
        layers = {ent.dxf.layer for ent in doc.modelspace()}
        assert "BORDO" in layers
        # verify BORDO layer defined with cyan aci=4
        assert doc.layers.get("BORDO").color == 4


# ---------- G-code per-tool export (project) ----------
class TestProjectGcodePerTool:
    @pytest.fixture(scope="class")
    def piece_with_multi_tool(self, s, throwaway_boat):
        r = s.post(f"{API}/projects", json={"name": "TEST_iter15_gcode", "boat_id": throwaway_boat})
        assert r.status_code in (200, 201)
        pid = r.json()["id"]
        s.patch(f"{API}/projects/{pid}", json={"contour_mm": RECT_CONTOUR, "boat_id": throwaway_boat})

        els = [
            {"id": uuid.uuid4().hex, "type": "fill", "layer": "ENGRAVE", "tool": "FUGA",
             "polylines": [[[100, 100], [500, 100], [500, 300], [100, 300], [100, 100]]],
             "params": {}},
            {"id": uuid.uuid4().hex, "type": "fill", "layer": "ENGRAVE", "tool": "BORDO",
             "polylines": [[[60, 60], [540, 60], [540, 340], [60, 340], [60, 60]]],
             "params": {"role": "border"}},
            {"id": uuid.uuid4().hex, "type": "text", "layer": "ENGRAVE", "tool": "CONTORNO",
             "polylines": [[[200, 200], [400, 200], [400, 250], [200, 250], [200, 200]]],
             "params": {}},
        ]
        s.patch(f"{API}/projects/{pid}", json={"elements": els})
        return pid

    def test_gcode_export_has_sections_and_tool_changes(self, s, piece_with_multi_tool):
        r = s.post(f"{API}/projects/{piece_with_multi_tool}/export/gcode", json={})
        assert r.status_code == 200, r.text
        url = r.json()["url"]
        gcode = requests.get(_abs(url)).text
        # sanity — multi-tool markers
        assert "=====" in gcode, "expected per-tool section separators (=====)"
        # each of the tools we assigned should appear in a section header
        for tid in ("FUGA", "BORDO", "CONTORNO", "SVASO"):
            assert re.search(rf"=====\s*{tid}", gcode), f"missing {tid} section header"
        # tool change opcodes and spindle control
        assert re.search(r"^M6 T\d+", gcode, re.M), "missing M6 T<n> tool change"
        assert re.search(r"^M3 S\d+", gcode, re.M), "missing M3 S<rpm>"
        # spindle stop BETWEEN tool changes (i.e. M5 appears before at least one M6)
        m5_positions = [m.start() for m in re.finditer(r"^M5\b", gcode, re.M)]
        m6_positions = [m.start() for m in re.finditer(r"^M6 T\d+", gcode, re.M)]
        assert len(m6_positions) >= 2, "expected at least 2 tool changes"
        # at least one M5 should occur strictly between two M6 opcodes
        between = any(m6_positions[0] < p < m6_positions[-1] for p in m5_positions)
        assert between, "expected M5 between tool changes"
        # ends with spindle-off + program end
        assert re.search(r"M5\b", gcode.splitlines()[-3:] and "\n".join(gcode.splitlines()[-3:]))
        assert re.search(r"M(2|30)\s*$", gcode.strip())

    def test_gcode_uses_per_tool_feed_and_depth(self, s, piece_with_multi_tool):
        # load current tools to know expected feeds
        tools = s.get(f"{API}/tools").json()
        tools = tools["tools"] if isinstance(tools, dict) else tools
        by_id = {t["id"]: t for t in tools}

        r = s.post(f"{API}/projects/{piece_with_multi_tool}/export/gcode", json={})
        assert r.status_code == 200
        gcode = requests.get(_abs(r.json()["url"])).text
        # split into per-tool blocks by the '=====' section headers
        blocks = re.split(r";\s*=====\s*", gcode)
        # first block is the preamble; the rest each start with "<TID> ..."
        for blk in blocks[1:]:
            head = blk.strip().split()[0].strip(";").strip()
            tid = head.strip()
            if tid not in by_id:
                continue
            expected_feed = int(by_id[tid]["feed_mm_min"])
            expected_rpm = int(by_id[tid]["spindle_rpm"])
            expected_depth = float(by_id[tid]["depth_mm"])
            # spindle line in this block
            assert re.search(rf"M3 S{expected_rpm}\b", blk), f"{tid}: bad spindle rpm"
            # feed appears on G1 XY lines in this block
            feeds = set(int(m.group(1)) for m in re.finditer(r"G1 X[-\d.]+ Y[-\d.]+ F(\d+)", blk))
            assert expected_feed in feeds, f"{tid}: expected feed {expected_feed} not found (got {feeds})"
            # depth: max |Z| in G1 Z lines within this block
            zs = [abs(float(m.group(1))) for m in re.finditer(r"G1 Z(-?\d+\.\d+)", blk)]
            if zs:
                assert abs(max(zs) - expected_depth) < 0.5, f"{tid}: expected depth ~{expected_depth}, got {max(zs)}"


# ---------- G-code per-tool export (boat nested) ----------
class TestBoatNestedExports:
    def test_boat_nested_gcode_has_tool_sections(self, s, throwaway_boat, throwaway_piece):
        # ensure the piece has at least a fill+BORDO element
        el = {
            "id": uuid.uuid4().hex,
            "type": "fill",
            "layer": "ENGRAVE",
            "tool": "BORDO",
            "polylines": [[[50, 50], [550, 50], [550, 350], [50, 350], [50, 50]]],
            "params": {"role": "border"},
        }
        s.patch(f"{API}/projects/{throwaway_piece}", json={"elements": [el]})

        r = s.post(f"{API}/boats/{throwaway_boat}/export/gcode", json={})
        assert r.status_code == 200, r.text
        gcode = requests.get(_abs(r.json()["url"])).text
        assert "=====" in gcode
        assert re.search(r"^M6 T\d+", gcode, re.M)
        assert re.search(r"^M3 S\d+", gcode, re.M)
        # BORDO should be one of the sections since piece has a BORDO element
        assert re.search(r"=====\s*BORDO", gcode), "BORDO section missing in nested gcode"

    def test_boat_nested_dxf_has_bordo_layer(self, s, throwaway_boat):
        r = s.post(f"{API}/boats/{throwaway_boat}/nested-dxf", json={})
        assert r.status_code == 200, r.text
        url = r.json().get("dxf_url") or r.json().get("url")
        raw = requests.get(_abs(url)).content
        doc = ezdxf.read(io.StringIO(raw.decode("utf-8")))
        layers_defined = {name.upper() for name in doc.layers.entries}
        # all 5 layers must be defined
        for tid in ("FUGA", "BORDO", "CONTORNO", "TAGLIO", "SVASO"):
            assert tid in layers_defined, f"layer {tid} not defined in nested dxf"
        # colors
        assert doc.layers.get("BORDO").color == 4  # cyan aci
        assert doc.layers.get("FUGA").color == 5
        # BORDO polylines actually present since the piece has a BORDO element
        used = {ent.dxf.layer for ent in doc.modelspace()}
        assert "BORDO" in used


# ---------- Legacy formats still work ----------
class TestLegacyExports:
    def test_project_dxf_export_ok(self, s, throwaway_piece):
        r = s.post(f"{API}/projects/{throwaway_piece}/export/dxf", json={})
        assert r.status_code == 200
        assert r.json()["ext"] == "dxf"

    def test_project_svg_export_ok(self, s, throwaway_piece):
        r = s.post(f"{API}/projects/{throwaway_piece}/export/svg", json={})
        assert r.status_code == 200
        assert r.json()["ext"] == "svg"
