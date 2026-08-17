"""Tests for ArUco multi-photo reconstruction pipeline (iter12).

Covers:
  * GET /api/aruco/sheet.pdf                                 -> PDF, non-empty
  * POST /api/projects/{id}/photogram/aruco (pre-seeded)     -> processed, contour_mm
  * POST /api/projects/{id}/photogram/aruco no markers       -> 422 (italian), backend UP
  * POST /api/projects/{id}/photogram/aruco no photos        -> 400
  * REGRESSION /photogram/stitch                             -> {mosaic_url, w, h, warning?}
  * REGRESSION /photogram/extract line + rect                -> status processed
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

PRESEEDED_ARUCO_PROJECT = "6a82a5c817fe4d8f4b6783f0"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _plain_jpg(w: int = 640, h: int = 480, seed: int = 0) -> bytes:
    """Synthetic JPEG WITHOUT any ArUco markers -> aruco pipeline must reject."""
    rng = np.random.RandomState(seed)
    img = rng.randint(20, 235, size=(h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (int(w * 0.15), int(h * 0.15)),
                  (int(w * 0.85), int(h * 0.85)), (30, 30, 30), -1)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    assert ok
    return buf.tobytes()


def _retry_request(method, url, tries: int = 3, **kw):
    """Small retry helper because dev backend has a periodic ~6-min reload."""
    last = None
    for i in range(tries):
        try:
            r = requests.request(method, url, **kw)
            if r.status_code not in (502, 503, 504):
                return r
            last = r
        except requests.RequestException as e:  # noqa: BLE001
            last = e
        import time
        time.sleep(2 + i)
    if isinstance(last, requests.Response):
        return last
    raise last  # type: ignore[misc]


@pytest.fixture(scope="module")
def sess() -> requests.Session:
    return requests.Session()


# ---------------------------------------------------------------------------
# 1) Marker sheet PDF
# ---------------------------------------------------------------------------
class TestArucoSheet:
    def test_sheet_pdf_default_returns_pdf(self, sess):
        r = _retry_request("GET", f"{API}/aruco/sheet.pdf?mm=40", timeout=60)
        assert r.status_code == 200, r.text[:200]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        assert len(r.content) > 1000, "PDF body suspiciously small"
        # PDF magic header
        assert r.content[:4] == b"%PDF", "Not a valid PDF header"

    def test_sheet_pdf_custom_mm(self, sess):
        r = _retry_request("GET", f"{API}/aruco/sheet.pdf?mm=60", timeout=60)
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"
        assert len(r.content) > 1000


# ---------------------------------------------------------------------------
# 2) ArUco pipeline (pre-seeded project)
# ---------------------------------------------------------------------------
class TestArucoPreseeded:
    def test_preseeded_project_exists(self, sess):
        r = _retry_request("GET", f"{API}/projects/{PRESEEDED_ARUCO_PROJECT}", timeout=15)
        assert r.status_code == 200, r.text[:200]

    def test_aruco_on_preseeded_project_processed(self, sess):
        body = {"marker_mm": 50}
        r = _retry_request("POST", f"{API}/projects/{PRESEEDED_ARUCO_PROJECT}/photogram/aruco",
                           json=body, timeout=180)
        assert r.status_code == 200, r.text[:500]
        proj = r.json()
        assert proj["status"] == "processed", f"expected processed, got {proj.get('status')}"
        assert proj["mm_per_px"] > 0
        assert isinstance(proj["contour_mm"], list) and len(proj["contour_mm"]) >= 3, (
            f"contour_mm={proj.get('contour_mm')}"
        )
        assert proj["rectified_url"] and proj["rectified_url"].startswith("/api/files/")
        assert proj.get("photos_used", 0) >= 1
        assert proj.get("markers_found", 0) >= 1
        # rectified file downloadable
        fr = _retry_request("GET", f"{BASE_URL}{proj['rectified_url']}", timeout=30)
        assert fr.status_code == 200 and len(fr.content) > 1000


# ---------------------------------------------------------------------------
# 3) Error paths (no markers / no photos)
# ---------------------------------------------------------------------------
class TestArucoErrors:
    def test_aruco_no_photos_returns_400(self, sess):
        r = _retry_request("POST", f"{API}/projects",
                           json={"name": "TEST_aruco_empty"}, timeout=15)
        pid = r.json()["id"]
        try:
            r = _retry_request("POST", f"{API}/projects/{pid}/photogram/aruco",
                               json={"marker_mm": 50}, timeout=30)
            assert r.status_code == 400, r.text[:200]
            assert "foto" in r.json().get("detail", "").lower()
        finally:
            sess.delete(f"{API}/projects/{pid}", timeout=15)

    def test_aruco_no_markers_returns_422_and_backend_alive(self, sess):
        # Create project + upload 2 markerless photos
        pid = _retry_request("POST", f"{API}/projects",
                             json={"name": "TEST_aruco_nomarkers"}, timeout=15).json()["id"]
        try:
            for i in range(2):
                files = {"file": (f"p{i}.jpg", _plain_jpg(seed=10 + i), "image/jpeg")}
                up = _retry_request("POST", f"{API}/projects/{pid}/photogram/photos",
                                    files=files, timeout=30)
                assert up.status_code == 200, up.text[:200]

            r = _retry_request("POST", f"{API}/projects/{pid}/photogram/aruco",
                               json={"marker_mm": 50}, timeout=120)
            assert r.status_code == 422, f"expected 422 (Italian error), got {r.status_code}: {r.text[:200]}"
            detail = r.json().get("detail", "")
            assert isinstance(detail, str) and len(detail) > 5
            # Italian keyword sanity check
            low = detail.lower()
            assert any(k in low for k in ("marker", "foto", "piano", "riconosc", "collegabili")), (
                f"detail doesn't look Italian marker error: {detail}"
            )

            # Backend must remain UP
            hr = _retry_request("GET", f"{API}/", timeout=15)
            assert hr.status_code == 200, "Backend not responding after markerless aruco call"
        finally:
            sess.delete(f"{API}/projects/{pid}", timeout=15)


# ---------------------------------------------------------------------------
# 4) REGRESSION: /photogram/stitch (single/sharpest photo, never crashes)
# ---------------------------------------------------------------------------
class TestStitchRegression:
    def test_stitch_returns_mosaic_and_backend_stays_up(self, sess):
        pid = _retry_request("POST", f"{API}/projects",
                             json={"name": "TEST_stitch_reg"}, timeout=15).json()["id"]
        try:
            for i in range(2):
                files = {"file": (f"p{i}.jpg", _plain_jpg(seed=30 + i), "image/jpeg")}
                _retry_request("POST", f"{API}/projects/{pid}/photogram/photos",
                               files=files, timeout=30)

            r = _retry_request("POST", f"{API}/projects/{pid}/photogram/stitch", timeout=120)
            assert r.status_code == 200, r.text[:200]
            j = r.json()
            assert j["mosaic_url"] and j["mosaic_url"].startswith("/api/files/")
            assert j["w"] > 0 and j["h"] > 0
            assert "warning" in j  # may be None or a string

            # backend still alive
            hr = _retry_request("GET", f"{API}/", timeout=15)
            assert hr.status_code == 200
        finally:
            sess.delete(f"{API}/projects/{pid}", timeout=15)


# ---------------------------------------------------------------------------
# 5) REGRESSION: /photogram/extract line + rect
# ---------------------------------------------------------------------------
class TestExtractRegression:
    @pytest.fixture(scope="class")
    def stitched_project(self, sess):
        pid = _retry_request("POST", f"{API}/projects",
                             json={"name": "TEST_extract_reg"}, timeout=15).json()["id"]
        for i in range(1):
            files = {"file": (f"p{i}.jpg", _plain_jpg(seed=50 + i), "image/jpeg")}
            _retry_request("POST", f"{API}/projects/{pid}/photogram/photos",
                           files=files, timeout=30)
        sr = _retry_request("POST", f"{API}/projects/{pid}/photogram/stitch", timeout=120)
        assert sr.status_code == 200
        yield pid
        try:
            sess.delete(f"{API}/projects/{pid}", timeout=15)
        except Exception:
            pass

    def test_extract_line(self, sess, stitched_project):
        body = {"type": "line",
                "points": [[100, 100], [400, 100]],
                "length_mm": 150.0}
        r = _retry_request("POST", f"{API}/projects/{stitched_project}/photogram/extract",
                           json=body, timeout=120)
        assert r.status_code == 200, r.text[:200]
        p = r.json()
        assert p["status"] == "processed"
        assert p["mm_per_px"] > 0
        assert isinstance(p["contour_mm"], list) and len(p["contour_mm"]) >= 3
        assert p["rectified_url"] and p["rectified_url"].startswith("/api/files/")

    def test_extract_rect(self, sess, stitched_project):
        body = {"type": "rect",
                "points": [[80, 80], [500, 80], [500, 350], [80, 350]],
                "width_mm": 210.0, "height_mm": 297.0}
        r = _retry_request("POST", f"{API}/projects/{stitched_project}/photogram/extract",
                           json=body, timeout=120)
        assert r.status_code == 200, r.text[:200]
        p = r.json()
        assert p["status"] == "processed"
        assert p["mm_per_px"] > 0
        assert len(p["contour_mm"]) >= 3
        assert p["rectified_url"]
