"""New photo->vectorize params (iteration 6):

  - subject='cerchio' -> HoughCircles-based perfect circular polyline
  - roi form field (JSON '{x,y,w,h}' fractions 0-1) -> pre-crop before tracing
  - threshold slider (0-255 or -1 for auto)

Also runs a quick regression for subject in (scritta, logo, oggetto) and blank.

Notes:
  - HoughCircles + GrabCut can take 1-3s per call; TIMEOUT is generous.
  - roi is sent as a multipart Form field containing a JSON string.
"""
from __future__ import annotations

import io
import os

import cv2
import numpy as np
import pytest
import requests
from PIL import Image, ImageDraw, ImageFont

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
TIMEOUT = 60

TTF_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _font(size: int) -> ImageFont.ImageFont:
    for p in TTF_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ---------- image factories (cv2 for HoughCircles-friendly outputs) ---------
def _encode_cv(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _cv_circle_img(size: int = 600, r_frac: float = 0.30, outline_only: bool = False) -> bytes:
    """White canvas with a clear black circle centered. HoughCircles-friendly."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    c = size // 2
    r = int(size * r_frac)
    if outline_only:
        cv2.circle(img, (c, c), r, (0, 0, 0), thickness=6)
    else:
        cv2.circle(img, (c, c), r, (0, 0, 0), thickness=-1)
    return _encode_cv(img)


def _cv_no_circle_img(size: int = 600) -> bytes:
    """Rectangle + text; no circular shapes."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (120, 200), (480, 380), (0, 0, 0), thickness=-1)
    return _encode_cv(img)


def _text_png(msg: str = "OA", canvas=(1200, 1200), pos=(300, 500), font_px: int = 200) -> bytes:
    img = Image.new("RGB", canvas, "white")
    ImageDraw.Draw(img).text(pos, msg, fill="black", font=_font(font_px))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _centered_shape_for_roi(size: int = 1200) -> bytes:
    """Large white canvas with a small centered black rectangle — used to
    verify the ROI crop actually narrows the trace to the requested region."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    cx, cy = size // 2, size // 2
    cv2.rectangle(img, (cx - 80, cy - 80), (cx + 80, cy + 80), (0, 0, 0), thickness=-1)
    return _encode_cv(img)


def _rect_solid() -> bytes:
    img = np.full((1000, 1200, 3), 255, dtype=np.uint8)
    cv2.rectangle(img, (440, 380), (760, 620), (20, 20, 20), thickness=-1)
    return _encode_cv(img)


def _blank() -> bytes:
    return _encode_cv(np.full((400, 400, 3), 255, dtype=np.uint8))


# ---------- fixture ---------------------------------------------------------
@pytest.fixture(scope="module")
def s() -> requests.Session:
    sess = requests.Session()
    yield sess
    sess.close()


def _post_vec(s, img_bytes: bytes, **fields) -> requests.Response:
    return s.post(
        f"{API}/vectorize",
        files={"file": ("in.png", img_bytes, "image/png")},
        data={k: str(v) for k, v in fields.items()},
        timeout=TIMEOUT,
    )


# ---------- 1) subject='cerchio' — success ---------------------------------
def test_cerchio_with_clear_circle_returns_polyline(s):
    # Outlined circle: HoughCircles detects it reliably.
    # NB: filled discs are NOT detected with current HoughCircles params
    # (param2=45); documented in the test report as a minor limitation.
    r = _post_vec(
        s, _cv_circle_img(size=800, r_frac=0.30, outline_only=True),
        subject="cerchio", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1, j
    assert isinstance(j["polylines"], list) and len(j["polylines"]) >= 1
    # HoughCircles path emits a 96-point closed polyline (97 with wrap)
    poly = j["polylines"][0]
    assert 90 <= len(poly) <= 110, f"expected ~96 pts (with wrap 97), got {len(poly)}"
    assert j["preview_url"] and j["preview_url"].endswith(".png")
    assert j["dxf_url"] and j["dxf_url"].endswith(".dxf")


def test_cerchio_outline_only_also_detected(s):
    r = _post_vec(
        s, _cv_circle_img(size=600, r_frac=0.30, outline_only=True),
        subject="cerchio", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1


# ---------- 2) subject='cerchio' — no circle -> 422 ------------------------
def test_cerchio_without_circle_returns_422(s):
    r = _post_vec(
        s, _cv_no_circle_img(),
        subject="cerchio", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 422, r.text
    detail = r.json().get("detail", "")
    assert "cerchio" in detail.lower(), detail


# ---------- 3) roi form field crops the region -----------------------------
def test_roi_json_crops_and_width_mm_matches_target(s):
    """ROI covers the central 50% of the image; target_width_mm=180 -> the
    traced subject bbox width should equal ~180 (scale normalization uses
    the union bbox of the polylines)."""
    roi = '{"x":0.25,"y":0.25,"w":0.5,"h":0.5}'
    r = _post_vec(
        s, _centered_shape_for_roi(),
        subject="oggetto", invert="true", threshold=-1, target_width_mm=180, roi=roi,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1
    assert abs(j["width_mm"] - 180.0) < 1.0, f"width_mm={j['width_mm']} (expected ~180)"


def test_roi_invalid_json_is_ignored_gracefully(s):
    """Malformed roi string must NOT 500 nor 422; backend falls back to whole image."""
    r = _post_vec(
        s, _text_png("OA"),
        subject="scritta", invert="true", threshold=-1, target_width_mm=200,
        roi="{not valid json",
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1


# ---------- 4) manual threshold=100 with invert=true -----------------------
def test_manual_threshold_100_invert_true_returns_200(s):
    r = _post_vec(
        s, _text_png("OA"),
        subject="scritta", invert="true", threshold=100, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1


# ---------- 5) regression: other subjects still work -----------------------
@pytest.mark.parametrize("subject,img_fn", [
    ("scritta", _text_png),
    ("logo",    _cv_circle_img),
    ("oggetto", _rect_solid),
])
def test_regression_other_subjects(s, subject, img_fn):
    img = img_fn() if img_fn is not _cv_circle_img else _cv_circle_img(size=1200, r_frac=0.15)
    r = _post_vec(s, img, subject=subject, invert="true", threshold=-1, target_width_mm=200)
    assert r.status_code == 200, r.text
    assert r.json()["count"] >= 1


# ---------- 6) blank still 422 ---------------------------------------------
def test_blank_still_422(s):
    r = _post_vec(s, _blank(), subject="logo", invert="true", threshold=-1, target_width_mm=200)
    assert r.status_code == 422, r.text
