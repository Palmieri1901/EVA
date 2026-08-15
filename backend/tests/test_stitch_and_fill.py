"""Iteration 2 backend tests: /geometry/fill, multi-shot stitching, delete shot,
and single-shot regression flow."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

SYN = Path("/tmp/synthetic.jpg")
SHOT1 = Path("/tmp/shot1.jpg")
SHOT2 = Path("/tmp/shot2.jpg")


@pytest.fixture(scope="session")
def synthetic_image() -> Path:
    if not SYN.exists():
        subprocess.run(["python", "/tmp/test_pipeline.py"], check=True)
    assert SYN.exists() and SYN.stat().st_size > 0
    return SYN


@pytest.fixture(scope="session")
def stitch_images():
    if not SHOT1.exists() or not SHOT2.exists():
        subprocess.run(["python", "/tmp/test_stitch.py"], check=True)
    assert SHOT1.exists() and SHOT2.exists()
    return SHOT1, SHOT2


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    yield sess
    sess.close()


# =========================================================================
# /api/geometry/fill  — new endpoint
# =========================================================================
class TestGeometryFill:
    CONTOUR = [[0.0, 0.0], [800.0, 0.0], [800.0, 500.0], [0.0, 500.0]]

    def test_fill_diamond_semplice(self, s):
        r = s.post(f"{API}/geometry/fill", json={
            "contour": self.CONTOUR, "spacing_mm": 20, "angle_deg": 45,
            "pattern": "diamond", "style": "semplice", "border_mm": 0,
        })
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["border_count"] == 0
        assert j["line_count"] > 0
        assert len(j["polylines"]) == j["line_count"]

    def test_fill_diamond_bordato(self, s):
        r = s.post(f"{API}/geometry/fill", json={
            "contour": self.CONTOUR, "spacing_mm": 25, "angle_deg": 45,
            "pattern": "diamond", "style": "bordato", "border_mm": 30,
        })
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["border_count"] > 0, "bordato should produce >=1 border ring"
        assert j["line_count"] > 0
        assert len(j["polylines"]) == j["border_count"] + j["line_count"]

    def test_fill_cross_bordato(self, s):
        r = s.post(f"{API}/geometry/fill", json={
            "contour": self.CONTOUR, "spacing_mm": 30, "angle_deg": 0,
            "pattern": "cross", "style": "bordato", "border_mm": 25,
        })
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["border_count"] >= 1 and j["line_count"] > 0

    def test_fill_lines_semplice(self, s):
        r = s.post(f"{API}/geometry/fill", json={
            "contour": self.CONTOUR, "spacing_mm": 15, "angle_deg": 0,
            "pattern": "lines", "style": "semplice", "border_mm": 0,
        })
        assert r.status_code == 200
        assert r.json()["line_count"] > 0

    def test_fill_invalid_contour(self, s):
        r = s.post(f"{API}/geometry/fill", json={
            "contour": [[0, 0], [10, 0]], "spacing_mm": 10, "angle_deg": 0,
            "pattern": "diamond", "style": "semplice", "border_mm": 0,
        })
        assert r.status_code == 422


# =========================================================================
# Multi-shot flow: create -> add 2 shots -> list -> stitch
# =========================================================================
class TestMultiShotFlow:
    project_id: str = ""
    shot_ids: list = []

    def test_01_create_multi_project(self, s):
        payload = {
            "name": "TEST_multishot",
            "background_mode": "blue_on_white",
            "marker_diameter_mm": 20,
            "ref_width_mm": 1200,
            "ref_height_mm": 700,
            "cut_side": "inner",
            "capture_mode": "multi",
        }
        r = s.post(f"{API}/projects", json=payload)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("capture_mode") == "multi"
        TestMultiShotFlow.project_id = j["id"]

    def test_02_add_two_shots(self, s, stitch_images):
        pid = TestMultiShotFlow.project_id
        for i, path in enumerate(stitch_images, start=1):
            with open(path, "rb") as f:
                r = s.post(
                    f"{API}/projects/{pid}/shots",
                    files={"file": (f"shot{i}.jpg", f, "image/jpeg")},
                )
            assert r.status_code == 200, r.text
            j = r.json()
            assert "id" in j and j["n_markers"] >= 4
            assert j["order"] == i - 1
            TestMultiShotFlow.shot_ids.append(j["id"])
        assert len(TestMultiShotFlow.shot_ids) == 2

    def test_03_list_shots(self, s):
        pid = TestMultiShotFlow.project_id
        r = s.get(f"{API}/projects/{pid}/shots")
        assert r.status_code == 200
        shots = r.json()
        assert len(shots) == 2
        for sh in shots:
            assert sh["n_markers"] >= 4
            assert sh["photo_url"].startswith("/api/files/")

    def test_04_stitch(self, s):
        pid = TestMultiShotFlow.project_id
        r = s.post(f"{API}/projects/{pid}/stitch", timeout=90)
        assert r.status_code == 200, r.text
        j = r.json()
        assert len(j["anchored"]) == 2, f"anchored={j['anchored']}"
        assert j["unanchored"] == []
        assert j["contour_points"] >= 4
        assert j["plane_w_mm"] > 0 and j["plane_h_mm"] > 0
        assert j["rectified_url"].startswith("/api/files/")

    def test_05_delete_one_shot(self, s):
        pid = TestMultiShotFlow.project_id
        sid = TestMultiShotFlow.shot_ids[0]
        r = s.delete(f"{API}/projects/{pid}/shots/{sid}")
        assert r.status_code == 200 and r.json()["ok"] is True
        # verify only 1 remains
        g = s.get(f"{API}/projects/{pid}/shots").json()
        assert len(g) == 1
        assert g[0]["id"] != sid

    def test_99_cleanup(self, s):
        pid = TestMultiShotFlow.project_id
        if pid:
            s.delete(f"{API}/projects/{pid}")


# =========================================================================
# Single-shot regression: create -> photo -> process -> preview -> export
# =========================================================================
class TestSingleShotRegression:
    project_id: str = ""

    def test_01_create(self, s):
        r = s.post(f"{API}/projects", json={
            "name": "TEST_regression_single",
            "background_mode": "blue_on_white",
            "marker_diameter_mm": 20,
            "ref_width_mm": 900,
            "ref_height_mm": 700,
            "cut_side": "inner",
        })
        assert r.status_code == 200
        TestSingleShotRegression.project_id = r.json()["id"]

    def test_02_photo_process(self, s, synthetic_image):
        pid = TestSingleShotRegression.project_id
        with open(synthetic_image, "rb") as f:
            r = s.post(f"{API}/projects/{pid}/photo",
                       files={"file": ("synthetic.jpg", f, "image/jpeg")})
        assert r.status_code == 200
        r = s.post(f"{API}/projects/{pid}/process", timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "processed"
        assert j["quality"]["markers_found"] >= 4
        assert len(j["contour_mm"]) >= 4

    def test_03_preview(self, s):
        pid = TestSingleShotRegression.project_id
        r = s.get(f"{API}/projects/{pid}/preview")
        assert r.status_code == 200
        j = r.json()
        assert j["cut_count"] >= 1

    def test_04_export(self, s):
        pid = TestSingleShotRegression.project_id
        r = s.post(f"{API}/projects/{pid}/export", timeout=60)
        assert r.status_code == 200
        assert r.json()["size"] > 0

    def test_99_cleanup(self, s):
        pid = TestSingleShotRegression.project_id
        if pid:
            s.delete(f"{API}/projects/{pid}")
