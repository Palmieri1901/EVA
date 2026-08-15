"""Tests for multi-format export (project & boat) + photo vectorize + elements append.

Covers new capabilities added in the EVA Boat Mat Digitizer:
  - POST /api/projects/{id}/export/{fmt}  for dxf, svg, pdf, png, gcode
  - cut_only:true removes engrave polylines from the DXF payload
  - gcode with mach3 flavor + include_engrave:false returns .nc text
  - POST /api/boats/{id}/export/{fmt} for all 5 formats + cut_only on nested sheet
  - POST /api/vectorize multipart returns polylines + preview_url + dxf_url
  - POST /api/vectorize error case (blank white image) -> 422
  - POST /api/projects/{id}/elements appends a polyline element and sets status=edited
"""
from __future__ import annotations

import io
import os
from typing import Tuple

import pytest
import requests
from PIL import Image, ImageDraw, ImageFont

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


# ---------- fixtures --------------------------------------------------------
@pytest.fixture(scope="session")
def s() -> requests.Session:
    sess = requests.Session()
    yield sess
    sess.close()


@pytest.fixture(scope="module")
def boat_and_piece(s: requests.Session) -> Tuple[str, str]:
    """Create a fresh boat + piece with a contour + one engrave element, cleaned up at teardown."""
    b = s.post(f"{API}/boats", json={"name": "TEST_exports_boat"})
    assert b.status_code == 200, b.text
    boat_id = b["json"]() if False else b.json()["id"]

    p = s.post(
        f"{API}/projects",
        json={
            "name": "TEST_exports_piece",
            "boat_id": boat_id,
            "piece_name": "Pezzo 1",
            "background_mode": "blue_on_white",
            "marker_diameter_mm": 20,
            "ref_width_mm": 500,
            "ref_height_mm": 300,
            "cut_side": "inner",
            "blade_offset_mm": 0,
        },
    )
    assert p.status_code == 200, p.text
    piece_id = p.json()["id"]

    # PATCH a rectangle contour_mm
    r = s.patch(
        f"{API}/projects/{piece_id}",
        json={"contour_mm": [[0, 0], [500, 0], [500, 300], [0, 300], [0, 0]]},
    )
    assert r.status_code == 200, r.text

    # Add an ENGRAVE polyline element so we can verify cut_only strips it
    r = s.post(
        f"{API}/projects/{piece_id}/elements",
        json={
            "type": "polyline",
            "layer": "ENGRAVE",
            "polylines": [[[50, 50], [200, 50], [200, 150], [50, 150], [50, 50]]],
            "params": {"source": "test"},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "edited"
    assert len(r.json()["elements"]) >= 1

    yield boat_id, piece_id

    # Cleanup
    s.delete(f"{API}/boats/{boat_id}")


# ---------- project exports -------------------------------------------------
@pytest.mark.parametrize("fmt,ext,mime_check", [
    ("dxf", "dxf", b"SECTION"),
    ("svg", "svg", b"<svg"),
    ("pdf", "pdf", b"%PDF"),
    ("png", "png", b"\x89PNG"),
    ("gcode", "nc", b"G21"),
])
def test_project_export_format(s, boat_and_piece, fmt, ext, mime_check):
    _, piece_id = boat_and_piece
    r = s.post(f"{API}/projects/{piece_id}/export/{fmt}", json={})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["format"] == fmt
    assert j["ext"] == ext
    assert j["size"] > 0
    assert j["url"].startswith("/api/files/") and j["url"].endswith(f".{ext}")

    # Fetch file and validate signature
    fr = s.get(f"{BASE_URL}{j['url']}")
    assert fr.status_code == 200
    assert len(fr.content) == j["size"]
    # magic check
    if ext == "svg":
        assert mime_check in fr.content[:200]
    elif ext == "nc":
        assert mime_check in fr.content[:100]
    elif ext == "dxf":
        assert mime_check.lower() in fr.content[:400].lower()
    else:
        assert fr.content.startswith(mime_check) or mime_check in fr.content[:8]


def test_project_export_dxf_cut_only_omits_engrave(s, boat_and_piece):
    _, piece_id = boat_and_piece
    full = s.post(f"{API}/projects/{piece_id}/export/dxf", json={})
    assert full.status_code == 200, full.text
    r1 = s.get(f"{BASE_URL}{full.json()['url']}")
    body_full = r1.content.decode("utf-8", errors="ignore")

    cut = s.post(f"{API}/projects/{piece_id}/export/dxf", json={"cut_only": True})
    assert cut.status_code == 200, cut.text
    r2 = s.get(f"{BASE_URL}{cut.json()['url']}")
    body_cut = r2.content.decode("utf-8", errors="ignore")

    # ENGRAVE layer name is declared in the DXF TABLES section either way; what
    # matters is that ENGRAVE entities exist in full but not in cut_only.
    n_full = body_full.count("ENGRAVE")
    n_cut = body_cut.count("ENGRAVE")
    assert n_full > n_cut, f"ENGRAVE occurrences full={n_full} cut={n_cut}"
    assert "CUT" in body_full and "CUT" in body_cut
    # cut_only should be smaller (fewer entities)
    assert cut.json()["size"] < full.json()["size"]


def test_project_export_gcode_mach3_no_engrave(s, boat_and_piece):
    _, piece_id = boat_and_piece
    r = s.post(
        f"{API}/projects/{piece_id}/export/gcode",
        json={"gcode": {"flavor": "mach3", "include_engrave": False, "cut_depth_mm": 5}},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ext"] == "nc"
    fr = s.get(f"{BASE_URL}{j['url']}")
    assert fr.status_code == 200
    text = fr.content.decode("utf-8", errors="ignore")
    assert "G21" in text and "G90" in text
    assert "flavor=mach3" in text
    assert "cut_depth=5" in text
    assert "M30" in text  # mach3 program end
    # engrave section header must be absent
    assert "--- ENGRAVE ---" not in text
    assert "--- CUT ---" in text


# ---------- boat (nested sheet) exports -------------------------------------
@pytest.mark.parametrize("fmt,ext", [
    ("dxf", "dxf"), ("svg", "svg"), ("pdf", "pdf"), ("png", "png"), ("gcode", "nc"),
])
def test_boat_export_format(s, boat_and_piece, fmt, ext):
    boat_id, _ = boat_and_piece
    r = s.post(f"{API}/boats/{boat_id}/export/{fmt}", json={})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["format"] == fmt and j["ext"] == ext
    assert j["count"] >= 1
    assert "overflow" in j
    fr = s.get(f"{BASE_URL}{j['url']}")
    assert fr.status_code == 200 and len(fr.content) == j["size"]


def test_boat_export_dxf_cut_only(s, boat_and_piece):
    boat_id, _ = boat_and_piece
    full = s.post(f"{API}/boats/{boat_id}/export/dxf", json={})
    cut = s.post(f"{API}/boats/{boat_id}/export/dxf", json={"cut_only": True})
    assert full.status_code == 200 and cut.status_code == 200
    body_full = s.get(f"{BASE_URL}{full.json()['url']}").content.decode("utf-8", errors="ignore")
    body_cut = s.get(f"{BASE_URL}{cut.json()['url']}").content.decode("utf-8", errors="ignore")
    n_full = body_full.count("ENGRAVE")
    n_cut = body_cut.count("ENGRAVE")
    assert n_full > n_cut, f"ENGRAVE occurrences full={n_full} cut={n_cut}"
    assert cut.json()["size"] < full.json()["size"]


# ---------- vectorize -------------------------------------------------------
def _make_text_png(text: str = "TEAK") -> bytes:
    img = Image.new("RGB", (640, 240), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("DejaVuSans-Bold.ttf", 160)
    except Exception:
        f = ImageFont.load_default()
    # roughly center
    d.text((30, 20), text, fill="black", font=f)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_blank_png() -> bytes:
    img = Image.new("RGB", (400, 400), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_vectorize_success(s):
    png = _make_text_png("TEAK")
    r = s.post(
        f"{API}/vectorize",
        files={"file": ("logo.png", png, "image/png")},
        data={"threshold": "-1", "invert": "true", "target_width_mm": "300"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert isinstance(j["polylines"], list) and len(j["polylines"]) > 0
    assert j["count"] > 0
    assert j["width_mm"] > 0 and j["height_mm"] > 0
    # width should be very close to target
    assert abs(j["width_mm"] - 300.0) < 0.5
    assert j["preview_url"] and j["preview_url"].endswith(".png")
    assert j["dxf_url"] and j["dxf_url"].endswith(".dxf")
    # both should be fetchable
    for u in (j["preview_url"], j["dxf_url"]):
        fr = s.get(f"{BASE_URL}{u}")
        assert fr.status_code == 200 and len(fr.content) > 0


def test_vectorize_blank_returns_422(s):
    png = _make_blank_png()
    r = s.post(
        f"{API}/vectorize",
        files={"file": ("blank.png", png, "image/png")},
        data={"threshold": "-1", "invert": "true", "target_width_mm": "200"},
    )
    assert r.status_code == 422, r.text
    assert "detail" in r.json()


# ---------- elements append -------------------------------------------------
def test_add_element_sets_edited_and_appends(s):
    # Standalone piece (no boat) to keep this test independent
    p = s.post(
        f"{API}/projects",
        json={
            "name": "TEST_elements_piece",
            "background_mode": "blue_on_white",
            "marker_diameter_mm": 20,
            "ref_width_mm": 200,
            "ref_height_mm": 150,
            "cut_side": "inner",
            "blade_offset_mm": 0,
        },
    )
    assert p.status_code == 200, p.text
    pid = p.json()["id"]
    try:
        before = s.get(f"{API}/projects/{pid}").json()
        n0 = len(before.get("elements") or [])

        r = s.post(
            f"{API}/projects/{pid}/elements",
            json={
                "type": "polyline",
                "layer": "CUT",
                "polylines": [[[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]]],
                "params": {},
            },
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "edited"
        assert len(j["elements"]) == n0 + 1
        last = j["elements"][-1]
        assert last["type"] == "polyline"
        assert last["layer"] == "CUT"
        assert len(last["polylines"][0]) == 5

        # Verify via GET
        g = s.get(f"{API}/projects/{pid}").json()
        assert g["status"] == "edited"
        assert len(g["elements"]) == n0 + 1
    finally:
        s.delete(f"{API}/projects/{pid}")
