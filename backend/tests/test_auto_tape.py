"""Iter13 backend tests — auto tape detection + SCATTO SINGOLO.

Covers:
  * SCATTO SINGOLO auto-tape branch of /api/projects/{id}/process
    - tape_color='auto' with a synthetic "tape band + inner mat" image
    - tape_color='blu','giallo','verde','rosso' with matching coloured bands
    - EXPECTS: HTTP 200, status='processed', rectified_url non-null,
               contour_mm >=4 pts, quality.messages mentions "Nastro" /
               "automaticamente" and bbox roughly near (900x700 mm)
  * No-tape / no-marker plain photo -> 200 with rectified image AND a
    provisional contour_mm (>=4 pts). MUST NOT be null. MUST NOT 500.
  * REGRESSION marker-based single (5 black dots + blue tape band).
  * REGRESSION photogram: photos -> stitch -> extract(rect) then extract(line).
  * Error cases:
      - /process with no photo uploaded -> 400
      - /photogram/extract before stitch -> 400
      - /photogram/extract with wrong point count -> 422
      - Backend remains up (GET /api/ = 200) after all calls.
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

# Reference interasse used everywhere in this file
REF_W_MM = 900
REF_H_MM = 700


# ---------------------------------------------------------------------------
# Synthetic image helpers (BGR)
# ---------------------------------------------------------------------------
# HSV means / BGR translations of tape colours we test.
# NB: cv2 stores images as BGR.
COLOR_BGR = {
    # a bright cyan/azzurro clearly inside cv_pipeline blu range H in [90,135]
    "blu":    (230, 170,  30),   # BGR ~ #1EAAE6 azzurro
    "giallo": ( 30, 220, 235),   # BGR ~ yellow
    "verde":  ( 60, 190,  70),   # BGR ~ green
    "rosso":  ( 40,  40, 220),   # BGR ~ red
}


def _tape_band_image(color: str, w: int = 1200, h: int = 900) -> bytes:
    """Light background with a THICK coloured rectangular TAPE BAND enclosing
    a lighter inner mat region (a "hole"). This is exactly what the auto-tape
    branch expects: a coloured band that encloses a large inner area.
    """
    # near-white background
    img = np.full((h, w, 3), 245, dtype=np.uint8)
    # slight noise so JPEG doesn't collapse to a single colour and Otsu works
    noise = np.random.RandomState(0).randint(-6, 6, (h, w, 3), dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    # tape rectangle: outer 8% margin, band thickness ~7% of min dim
    m = int(min(w, h) * 0.08)          # outer margin
    t = max(24, int(min(w, h) * 0.07))  # band thickness
    x0, y0 = m, m
    x1, y1 = w - m, h - m
    bgr = COLOR_BGR[color]
    # Outer filled rectangle in the tape colour
    cv2.rectangle(img, (x0, y0), (x1, y1), bgr, thickness=-1)
    # Inner hole (mat) — a bit lighter than background so tape/mat contrast well
    inner = (250, 250, 250)
    cv2.rectangle(img, (x0 + t, y0 + t), (x1 - t, y1 - t), inner, thickness=-1)

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    assert ok
    return buf.tobytes()


def _plain_image(w: int = 1200, h: int = 900) -> bytes:
    """A plain photo: no coloured border, no dots. Just a soft gradient."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        v = int(180 + 40 * (y / max(1, h - 1)))  # 180..220
        img[y, :, :] = (v, v, v)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    assert ok
    return buf.tobytes()


def _marker_and_tape_image(w: int = 1200, h: int = 900) -> bytes:
    """5 black circular dots at the 4 corners + center, PLUS a blue tape band
    inside them. Regression case for the marker-based single-shot pipeline.
    """
    img = np.full((h, w, 3), 245, dtype=np.uint8)
    # 5 black dots (TL, TR, BR, BL, center) inside a small margin
    margin = int(min(w, h) * 0.06)
    r = 18
    pts = [
        (margin, margin),
        (w - margin, margin),
        (w - margin, h - margin),
        (margin, h - margin),
        (w // 2, h // 2),
    ]
    for (x, y) in pts:
        cv2.circle(img, (x, y), r, (0, 0, 0), thickness=-1)

    # Blue tape band well inside the marker rectangle
    inset = int(min(w, h) * 0.12)
    x0, y0 = margin + inset, margin + inset
    x1, y1 = w - margin - inset, h - margin - inset
    t = max(22, int(min(w, h) * 0.06))
    cv2.rectangle(img, (x0, y0), (x1, y1), COLOR_BGR["blu"], thickness=-1)
    cv2.rectangle(img, (x0 + t, y0 + t), (x1 - t, y1 - t), (250, 250, 250), thickness=-1)

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    assert ok
    return buf.tobytes()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sess() -> requests.Session:
    return requests.Session()


def _create_project(sess: requests.Session, tape_color: str = "auto",
                    capture_mode: str = "single") -> str:
    payload = {
        "name": f"TEST_iter13_{tape_color}_{capture_mode}",
        "capture_mode": capture_mode,
        "tape_color": tape_color,
        "background_mode": tape_color if tape_color != "auto" else "blue_on_white",
        "ref_width_mm": float(REF_W_MM),
        "ref_height_mm": float(REF_H_MM),
        "cut_side": "inner",
    }
    r = sess.post(f"{API}/projects", json=payload, timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload_photo(sess: requests.Session, pid: str, jpg_bytes: bytes,
                  name: str = "shot.jpg") -> dict:
    files = {"file": (name, jpg_bytes, "image/jpeg")}
    r = sess.post(f"{API}/projects/{pid}/photo", files=files, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup(sess: requests.Session, pid: str) -> None:
    try:
        sess.delete(f"{API}/projects/{pid}", timeout=15)
    except Exception:
        pass


def _bbox_mm(contour_mm) -> tuple:
    arr = np.array(contour_mm, dtype=float)
    return float(arr[:, 0].min()), float(arr[:, 1].min()), \
           float(arr[:, 0].max()), float(arr[:, 1].max())


# ---------------------------------------------------------------------------
# 1) SCATTO SINGOLO auto-tape + specific colours
# ---------------------------------------------------------------------------
class TestSingleAutoTape:
    @pytest.mark.parametrize("tape_color", ["auto", "blu", "giallo", "verde", "rosso"])
    def test_single_auto_tape(self, sess, tape_color):
        # Build a synthetic image matching the project's tape colour.
        colour_for_image = "blu" if tape_color == "auto" else tape_color
        jpg = _tape_band_image(colour_for_image)
        pid = _create_project(sess, tape_color=tape_color, capture_mode="single")
        try:
            _upload_photo(sess, pid, jpg, name=f"{tape_color}.jpg")

            r = sess.post(f"{API}/projects/{pid}/process", timeout=120)
            assert r.status_code == 200, r.text
            p = r.json()
            assert p["status"] == "processed", p
            assert p.get("rectified_url"), f"rectified_url missing: {p}"
            assert p["rectified_url"].startswith("/api/files/")
            contour = p.get("contour_mm") or []
            assert len(contour) >= 4, f"contour_mm too small: {contour}"

            # BBox should be roughly the interasse (900x700) — allow generous
            # tolerance because tape thickness eats into the inner rectangle.
            xmin, ymin, xmax, ymax = _bbox_mm(contour)
            bw = xmax - xmin
            bh = ymax - ymin
            assert 500 <= bw <= 1200, f"bbox width {bw} not near {REF_W_MM}"
            assert 400 <= bh <= 1000, f"bbox height {bh} not near {REF_H_MM}"

            # quality.messages mentions automatic tape detection (italian).
            msgs = " ".join(p.get("quality", {}).get("messages") or []).lower()
            assert ("nastro" in msgs and "automatic" in msgs) or "rilevato automaticamente" in msgs, \
                f"quality messages missing auto-tape wording: {msgs}"

            # Rectified image is downloadable
            fr = sess.get(f"{BASE_URL}{p['rectified_url']}", timeout=30)
            assert fr.status_code == 200 and len(fr.content) > 1000
        finally:
            _cleanup(sess, pid)


# ---------------------------------------------------------------------------
# 2) No tape / no markers -> still 200 with rectified + provisional contour
# ---------------------------------------------------------------------------
class TestNoTapeNoMarker:
    def test_plain_photo_still_returns_rectified_and_contour(self, sess):
        pid = _create_project(sess, tape_color="auto", capture_mode="single")
        try:
            _upload_photo(sess, pid, _plain_image(), name="plain.jpg")
            r = sess.post(f"{API}/projects/{pid}/process", timeout=120)
            assert r.status_code == 200, r.text
            p = r.json()
            # MUST NOT be null / MUST NOT 500
            assert p.get("rectified_url"), f"rectified_url missing: {p}"
            assert p["rectified_url"].startswith("/api/files/")
            contour = p.get("contour_mm") or []
            assert len(contour) >= 4, f"provisional contour missing: {contour}"
            # Downloadable
            fr = sess.get(f"{BASE_URL}{p['rectified_url']}", timeout=30)
            assert fr.status_code == 200 and len(fr.content) > 500
        finally:
            _cleanup(sess, pid)


# ---------------------------------------------------------------------------
# 3) REGRESSION marker-based single shot
# ---------------------------------------------------------------------------
class TestMarkerBasedRegression:
    def test_5dots_plus_blue_tape(self, sess):
        pid = _create_project(sess, tape_color="blu", capture_mode="single")
        try:
            _upload_photo(sess, pid, _marker_and_tape_image(), name="markers.jpg")
            r = sess.post(f"{API}/projects/{pid}/process", timeout=120)
            assert r.status_code == 200, r.text
            p = r.json()
            assert p["status"] == "processed"
            assert p.get("rectified_url"), f"rectified_url missing: {p}"
            contour = p.get("contour_mm") or []
            assert len(contour) >= 4, f"contour_mm empty: {contour}"
        finally:
            _cleanup(sess, pid)


# ---------------------------------------------------------------------------
# 4) REGRESSION photogram (photos -> stitch -> extract rect + line)
# ---------------------------------------------------------------------------
class TestPhotogramRegression:
    def test_photogram_flow(self, sess):
        pid = _create_project(sess, tape_color="auto", capture_mode="photogram")
        try:
            # Upload 3 photos (one with a real coloured tape mat).
            imgs = [
                _tape_band_image("blu", 1000, 800),
                _plain_image(1000, 800),
                _plain_image(1000, 800),
            ]
            for i, b in enumerate(imgs):
                files = {"file": (f"p{i}.jpg", b, "image/jpeg")}
                r = sess.post(f"{API}/projects/{pid}/photogram/photos",
                              files=files, timeout=60)
                assert r.status_code == 200, r.text

            # Stitch
            r = sess.post(f"{API}/projects/{pid}/photogram/stitch", timeout=120)
            assert r.status_code == 200, r.text
            j = r.json()
            assert j.get("mosaic_url", "").startswith("/api/files/")
            assert j["w"] > 0 and j["h"] > 0

            W, H = j["w"], j["h"]

            # Extract rect — tap the 4 outer corners of the mosaic
            body_rect = {
                "type": "rect",
                "points": [[10, 10], [W - 10, 10], [W - 10, H - 10], [10, H - 10]],
                "width_mm": float(REF_W_MM),
                "height_mm": float(REF_H_MM),
            }
            r = sess.post(f"{API}/projects/{pid}/photogram/extract",
                          json=body_rect, timeout=120)
            assert r.status_code == 200, r.text
            p = r.json()
            assert p.get("detected") is True, f"detected not true: {p.get('detected')}"
            assert p.get("rectified_url", "").startswith("/api/files/")
            assert len(p.get("contour_mm") or []) >= 3

            # Extract line — 200
            body_line = {"type": "line",
                         "points": [[100, 100], [W - 100, 100]],
                         "length_mm": 500.0}
            r = sess.post(f"{API}/projects/{pid}/photogram/extract",
                          json=body_line, timeout=120)
            assert r.status_code == 200, r.text
        finally:
            _cleanup(sess, pid)


# ---------------------------------------------------------------------------
# 5) Error cases + backend liveness
# ---------------------------------------------------------------------------
class TestErrorsAndLiveness:
    def test_process_without_photo_returns_400(self, sess):
        pid = _create_project(sess, tape_color="auto")
        try:
            r = sess.post(f"{API}/projects/{pid}/process", timeout=30)
            assert r.status_code == 400, r.text
        finally:
            _cleanup(sess, pid)

    def test_photogram_extract_before_stitch_returns_400(self, sess):
        pid = _create_project(sess, tape_color="auto", capture_mode="photogram")
        try:
            r = sess.post(f"{API}/projects/{pid}/photogram/extract",
                          json={"type": "rect",
                                "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
                                "width_mm": 100, "height_mm": 100},
                          timeout=30)
            assert r.status_code == 400, r.text
        finally:
            _cleanup(sess, pid)

    def test_photogram_extract_wrong_point_count_returns_422(self, sess):
        # Need a project WITH a stitched mosaic first (400 comes from missing mosaic)
        pid = _create_project(sess, tape_color="auto", capture_mode="photogram")
        try:
            files = {"file": ("s.jpg", _plain_image(600, 400), "image/jpeg")}
            r = sess.post(f"{API}/projects/{pid}/photogram/photos",
                          files=files, timeout=60)
            assert r.status_code == 200
            r = sess.post(f"{API}/projects/{pid}/photogram/stitch", timeout=120)
            assert r.status_code == 200
            # wrong point count for rect
            r = sess.post(f"{API}/projects/{pid}/photogram/extract",
                          json={"type": "rect",
                                "points": [[0, 0], [10, 0], [10, 10]],
                                "width_mm": 100, "height_mm": 100},
                          timeout=30)
            assert r.status_code == 422, r.text
        finally:
            _cleanup(sess, pid)

    def test_backend_still_up(self, sess):
        r = sess.get(f"{API}/", timeout=15)
        assert r.status_code == 200
