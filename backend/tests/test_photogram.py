"""Tests for markerless photogrammetry pipeline (iter11).

Covers:
  * POST /api/projects/{id}/photogram/photos (multipart upload)
  * GET  /api/projects/{id}/photogram/photos
  * DELETE /api/projects/{id}/photogram/photos/{pid}
  * POST /api/projects/{id}/photogram/stitch (200 with photos, 400 without)
  * POST /api/projects/{id}/photogram/extract (line + rect happy paths, error cases)
"""
from __future__ import annotations

import io
import os

import cv2
import numpy as np
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------
def _jpg_bytes(w: int = 640, h: int = 480, seed: int = 0) -> bytes:
    """Return synthetic JPEG bytes with a distinctive coloured pattern."""
    rng = np.random.RandomState(seed)
    img = rng.randint(20, 235, size=(h, w, 3), dtype=np.uint8)
    # Big central rectangle so grabCut has a piece to segment
    cv2.rectangle(img, (int(w * 0.15), int(h * 0.15)),
                  (int(w * 0.85), int(h * 0.85)), (30, 30, 30), -1)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    assert ok
    return buf.tobytes()


@pytest.fixture(scope="module")
def sess() -> requests.Session:
    s = requests.Session()
    return s


@pytest.fixture(scope="module")
def project_id(sess: requests.Session) -> str:
    """Create a fresh project for the whole module and clean up at the end."""
    payload = {"name": "TEST_photogram_iter11"}
    r = sess.post(f"{API}/projects", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    yield pid
    try:
        sess.delete(f"{API}/projects/{pid}", timeout=15)
    except Exception:
        pass


@pytest.fixture(scope="module")
def empty_project_id(sess: requests.Session) -> str:
    """A second project we deliberately keep photo-less for 400 checks."""
    r = sess.post(f"{API}/projects", json={"name": "TEST_photogram_empty"}, timeout=30)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    yield pid
    try:
        sess.delete(f"{API}/projects/{pid}", timeout=15)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Photos CRUD
# ---------------------------------------------------------------------------
class TestPhotos:
    def test_upload_photo_returns_id_and_url(self, sess, project_id):
        files = {"file": ("shot1.jpg", _jpg_bytes(seed=1), "image/jpeg")}
        r = sess.post(f"{API}/projects/{project_id}/photogram/photos",
                      files=files, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "id" in data and data["id"]
        assert "photo_url" in data and data["photo_url"].startswith("/api/files/")
        assert data["order"] == 0

    def test_upload_second_photo_increments_order(self, sess, project_id):
        files = {"file": ("shot2.jpg", _jpg_bytes(seed=2), "image/jpeg")}
        r = sess.post(f"{API}/projects/{project_id}/photogram/photos",
                      files=files, timeout=30)
        assert r.status_code == 200
        assert r.json()["order"] == 1

    def test_list_photos(self, sess, project_id):
        r = sess.get(f"{API}/projects/{project_id}/photogram/photos", timeout=15)
        assert r.status_code == 200
        lst = r.json()
        assert isinstance(lst, list)
        assert len(lst) >= 2
        for p in lst:
            assert p["photo_url"] and p["photo_url"].startswith("/api/files/")

    def test_photo_file_is_downloadable(self, sess, project_id):
        lst = sess.get(f"{API}/projects/{project_id}/photogram/photos").json()
        url = f"{BASE_URL}{lst[0]['photo_url']}"
        r = sess.get(url, timeout=20)
        assert r.status_code == 200
        assert len(r.content) > 100

    def test_delete_photo_removes_it_and_reorders(self, sess, project_id):
        # Add a 3rd photo, delete the middle one, expect list of 2 with reindexed order
        files = {"file": ("shot3.jpg", _jpg_bytes(seed=3), "image/jpeg")}
        sess.post(f"{API}/projects/{project_id}/photogram/photos",
                  files=files, timeout=30)
        lst = sess.get(f"{API}/projects/{project_id}/photogram/photos").json()
        assert len(lst) == 3
        mid_id = lst[1]["id"]
        r = sess.delete(f"{API}/projects/{project_id}/photogram/photos/{mid_id}",
                        timeout=15)
        assert r.status_code == 200
        assert r.json()["count"] == 2
        after = sess.get(f"{API}/projects/{project_id}/photogram/photos").json()
        assert len(after) == 2
        assert [p["order"] for p in after] == [0, 1]
        assert mid_id not in [p["id"] for p in after]


# ---------------------------------------------------------------------------
# Stitch
# ---------------------------------------------------------------------------
class TestStitch:
    def test_stitch_without_photos_returns_400(self, sess, empty_project_id):
        r = sess.post(f"{API}/projects/{empty_project_id}/photogram/stitch",
                      timeout=60)
        assert r.status_code == 400, r.text
        assert "foto" in r.json().get("detail", "").lower()

    def test_stitch_with_photos_returns_mosaic(self, sess, project_id):
        r = sess.post(f"{API}/projects/{project_id}/photogram/stitch", timeout=120)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["mosaic_url"] and j["mosaic_url"].startswith("/api/files/")
        assert j["w"] > 0 and j["h"] > 0
        # warning may or may not be present -- both are acceptable
        assert "warning" in j
        # mosaic file must be fetchable
        fr = sess.get(f"{BASE_URL}{j['mosaic_url']}", timeout=30)
        assert fr.status_code == 200 and len(fr.content) > 1000


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------
class TestExtract:
    def test_extract_before_stitch_returns_400(self, sess):
        # Fresh project, no stitch yet
        pid = sess.post(f"{API}/projects", json={"name": "TEST_pg_nostitch"},
                        timeout=15).json()["id"]
        try:
            r = sess.post(f"{API}/projects/{pid}/photogram/extract",
                          json={"type": "line", "points": [[0, 0], [10, 0]],
                                "length_mm": 100}, timeout=30)
            assert r.status_code == 400, r.text
        finally:
            sess.delete(f"{API}/projects/{pid}")

    def test_extract_line_happy_path(self, sess, project_id):
        body = {"type": "line",
                "points": [[100, 100], [400, 100]],
                "length_mm": 150.0}
        r = sess.post(f"{API}/projects/{project_id}/photogram/extract",
                      json=body, timeout=90)
        assert r.status_code == 200, r.text
        proj = r.json()
        assert proj["status"] == "processed"
        assert proj["mm_per_px"] > 0
        assert isinstance(proj["contour_mm"], list) and len(proj["contour_mm"]) >= 3
        assert proj["rectified_url"] and proj["rectified_url"].startswith("/api/files/")
        assert "detected" in proj  # bool
        # Persisted: GET back should match
        g = sess.get(f"{API}/projects/{project_id}").json()
        assert g["status"] == "processed"
        assert g["mm_per_px"] == pytest.approx(proj["mm_per_px"], rel=1e-6)

    def test_extract_rect_happy_path(self, sess, project_id):
        body = {"type": "rect",
                "points": [[80, 80], [500, 80], [500, 350], [80, 350]],
                "width_mm": 210.0, "height_mm": 297.0}
        r = sess.post(f"{API}/projects/{project_id}/photogram/extract",
                      json=body, timeout=120)
        assert r.status_code == 200, r.text
        proj = r.json()
        assert proj["status"] == "processed"
        assert proj["mm_per_px"] > 0
        assert len(proj["contour_mm"]) >= 3
        assert proj["rectified_url"]

    # ---- error cases ------------------------------------------------------
    def test_extract_line_wrong_point_count(self, sess, project_id):
        r = sess.post(f"{API}/projects/{project_id}/photogram/extract",
                      json={"type": "line", "points": [[0, 0]], "length_mm": 100},
                      timeout=30)
        assert r.status_code == 422, r.text

    def test_extract_line_zero_length(self, sess, project_id):
        r = sess.post(f"{API}/projects/{project_id}/photogram/extract",
                      json={"type": "line", "points": [[0, 0], [10, 10]],
                            "length_mm": 0}, timeout=30)
        assert r.status_code == 422

    def test_extract_rect_missing_dims(self, sess, project_id):
        r = sess.post(f"{API}/projects/{project_id}/photogram/extract",
                      json={"type": "rect",
                            "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
                            "width_mm": 0, "height_mm": 297}, timeout=30)
        assert r.status_code == 422

    def test_extract_rect_wrong_point_count(self, sess, project_id):
        r = sess.post(f"{API}/projects/{project_id}/photogram/extract",
                      json={"type": "rect",
                            "points": [[0, 0], [10, 0], [10, 10]],
                            "width_mm": 210, "height_mm": 297}, timeout=30)
        assert r.status_code == 422

    def test_extract_unknown_type(self, sess, project_id):
        r = sess.post(f"{API}/projects/{project_id}/photogram/extract",
                      json={"type": "banana", "points": [[0, 0]]}, timeout=30)
        assert r.status_code == 422
