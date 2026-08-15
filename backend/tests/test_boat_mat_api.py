"""End-to-end backend tests for EVA Boat Mat Digitizer.

Covers: health, projects CRUD, photo upload, CV process, preview, geometry
generators (text/svg/track), DXF export + file streaming, and soft delete.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
SYN = Path("/tmp/synthetic.jpg")


@pytest.fixture(scope="session")
def synthetic_image() -> Path:
    if not SYN.exists():
        subprocess.run(["python", "/tmp/test_pipeline.py"], check=True)
    assert SYN.exists() and SYN.stat().st_size > 0
    return SYN


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    yield sess
    sess.close()


# ---------- Health ----------
def test_health(s):
    r = s.get(f"{API}/")
    assert r.status_code == 200
    j = r.json()
    assert j.get("status") == "ok"


def test_patterns(s):
    r = s.get(f"{API}/patterns")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list) and len(data) >= 1
    assert "id" in data[0] and "type" in data[0]


# ---------- Projects CRUD ----------
class TestProjectLifecycle:
    project_id: str = ""

    def test_01_create(self, s):
        payload = {
            "name": "TEST_boatmat",
            "background_mode": "blue_on_white",
            "marker_diameter_mm": 20,
            "ref_width_mm": 900,
            "ref_height_mm": 700,
            "cut_side": "inner",
            "blade_offset_mm": 0,
        }
        r = s.post(f"{API}/projects", json=payload)
        assert r.status_code == 200, r.text
        j = r.json()
        assert "id" in j and j["name"] == "TEST_boatmat"
        assert j["status"] == "draft"
        assert j["ref_width_mm"] == 900
        TestProjectLifecycle.project_id = j["id"]

    def test_02_list_contains(self, s):
        r = s.get(f"{API}/projects")
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert TestProjectLifecycle.project_id in ids

    def test_03_get(self, s):
        pid = TestProjectLifecycle.project_id
        r = s.get(f"{API}/projects/{pid}")
        assert r.status_code == 200
        assert r.json()["id"] == pid

    def test_04_upload_photo(self, s, synthetic_image):
        pid = TestProjectLifecycle.project_id
        with open(synthetic_image, "rb") as f:
            r = s.post(
                f"{API}/projects/{pid}/photo",
                files={"file": ("synthetic.jpg", f, "image/jpeg")},
            )
        assert r.status_code == 200, r.text
        j = r.json()
        assert "photo_path" in j and j["photo_path"]
        assert j["photo_url"].startswith("/api/files/")
        # verify persisted status
        g = s.get(f"{API}/projects/{pid}").json()
        assert g["status"] == "captured"
        assert g.get("photo_path")

    def test_05_process(self, s):
        pid = TestProjectLifecycle.project_id
        r = s.post(f"{API}/projects/{pid}/process", timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "processed"
        q = j["quality"]
        # synthetic must expose 5 markers, tape, and valid=True
        assert q["markers_found"] >= 5, f"markers_found={q['markers_found']}"
        assert q["tape_detected"] is True
        assert q["valid"] is True, f"quality={q}"
        assert isinstance(j["contour_mm"], list) and len(j["contour_mm"]) >= 4
        assert j.get("rectified_url", "").startswith("/api/files/")

    def test_06_patch_updates(self, s):
        pid = TestProjectLifecycle.project_id
        payload = {
            "blade_offset_mm": 0.5,
            "fillet_radius_mm": 3,
            "elements": [
                {
                    "id": "el1",
                    "type": "text",
                    "layer": "ENGRAVE",
                    "polylines": [[[10, 10], [50, 10], [50, 30], [10, 30], [10, 10]]],
                    "params": {"text": "TEST"},
                }
            ],
        }
        r = s.patch(f"{API}/projects/{pid}", json=payload)
        assert r.status_code == 200, r.text
        # GET to verify persistence
        g = s.get(f"{API}/projects/{pid}").json()
        assert g["blade_offset_mm"] == 0.5
        assert g["fillet_radius_mm"] == 3
        assert len(g["elements"]) == 1

    def test_07_preview(self, s):
        pid = TestProjectLifecycle.project_id
        r = s.get(f"{API}/projects/{pid}/preview")
        assert r.status_code == 200, r.text
        j = r.json()
        assert "cut" in j and "engrave" in j
        assert j["cut_count"] >= 1
        assert j["engrave_count"] >= 1
        assert "bbox" in j
        assert j["perimeter_mm"] > 0

    def test_08_export_dxf(self, s):
        pid = TestProjectLifecycle.project_id
        r = s.post(f"{API}/projects/{pid}/export", timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["dxf_url"].endswith(".dxf")
        assert j["size"] > 0
        # stream the dxf back
        dxf_path = j["dxf_url"].replace("/api/files/", "")
        fr = s.get(f"{API}/files/{dxf_path}")
        assert fr.status_code == 200
        assert len(fr.content) == j["size"]
        assert fr.content[:10].lower().find(b"section") != -1 or b"0" in fr.content[:10]

    def test_09_delete(self, s):
        pid = TestProjectLifecycle.project_id
        r = s.delete(f"{API}/projects/{pid}")
        assert r.status_code == 200 and r.json().get("ok") is True
        # verify soft delete: GET should return 404
        g = s.get(f"{API}/projects/{pid}")
        assert g.status_code == 404
        # and not in list
        lst = [p["id"] for p in s.get(f"{API}/projects").json()]
        assert pid not in lst


# ---------- Geometry generators (independent) ----------
class TestGeometry:
    def test_text(self, s):
        r = s.post(f"{API}/geometry/text", json={"text": "AB", "height_mm": 20, "x": 0, "y": 0})
        assert r.status_code == 200
        polys = r.json()["polylines"]
        assert isinstance(polys, list) and len(polys) >= 1
        assert len(polys[0]) >= 2

    def test_track(self, s):
        r = s.post(
            f"{API}/geometry/track",
            json={"x": 0, "y": 0, "width_mm": 100, "height_mm": 50, "spacing_mm": 10, "angle_deg": 45},
        )
        assert r.status_code == 200
        polys = r.json()["polylines"]
        assert len(polys) >= 2

    def test_svg(self, s):
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            '<path d="M10 10 L 90 10 L 90 90 L 10 90 Z"/></svg>'
        )
        r = s.post(f"{API}/geometry/svg", json={"svg": svg, "width_mm": 50, "x": 0, "y": 0})
        assert r.status_code == 200, r.text
        polys = r.json()["polylines"]
        assert len(polys) >= 1

    def test_svg_invalid(self, s):
        r = s.post(f"{API}/geometry/svg", json={"svg": "<svg/>", "width_mm": 50, "x": 0, "y": 0})
        assert r.status_code == 422


# ---------- Error handling ----------
def test_get_project_invalid_id(s):
    r = s.get(f"{API}/projects/not-an-oid")
    assert r.status_code == 400


def test_get_project_missing(s):
    r = s.get(f"{API}/projects/507f1f77bcf86cd799439011")
    assert r.status_code == 404
