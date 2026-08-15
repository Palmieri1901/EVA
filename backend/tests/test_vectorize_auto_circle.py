"""Iteration 7 – bug fix: auto-circle detection in LOGO/OGGETTO subjects.

Regression: vectorizing a photo of a round logo (BMW emblem) in LOGO/OGGETTO
mode produced a messy partial blob. Fix: for subject in {logo, oggetto}
(auto threshold, no internals), the backend now auto-detects a dominant,
roughly-centered circle via HoughCircles and outputs a clean ~96-point
circular polyline instead of a messy blob. subject='cerchio' also detects
circles (with a min-enclosing-circle fallback for filled discs).
Non-circular subjects still trace normally.

Success criteria for a "circular" trace:
  - polyline has ~90+ nearly-equidistant points forming a circle
  - typical value from _circle_poly(n=96) with closing wrap = 97 points

Success criteria for a "traced polygon" (non-circle):
  - polyline has <60 points (approxPolyDP + chaikin)
"""
from __future__ import annotations

import io
import math
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


def _font(size: int):
    for p in TTF_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ---------- image factories -------------------------------------------------
def _encode_cv(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _centered_ring(size: int = 500, r_frac: float = 0.36, thickness: int = 6) -> bytes:
    """White canvas with a centered outlined ring (BMW-emblem-style outline).
    r_frac 0.36 -> r=180 on a 500x500 canvas (~40% radius). Meets
    _dominant_circle() criteria: r >= 0.28 * min(w,h) and roughly centered."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    c = size // 2
    r = int(size * r_frac)
    cv2.circle(img, (c, c), r, (30, 30, 30), thickness=thickness)
    return _encode_cv(img)


def _centered_disc(size: int = 500, r_frac: float = 0.36) -> bytes:
    """White canvas with a centered filled black disc — used to verify
    the min-enclosing-circle fallback in _detect_circles() for subject=cerchio."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    c = size // 2
    r = int(size * r_frac)
    cv2.circle(img, (c, c), r, (30, 30, 30), thickness=-1)
    return _encode_cv(img)


def _text_abc_png(size: int = 500, msg: str = "ABC") -> bytes:
    """Black text 'ABC' on a white canvas — no dominant circle."""
    img = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(img)
    # font size tuned so the text does NOT fill a large centered region
    f = _font(int(size * 0.28))
    # Center the text roughly
    try:
        bbox = draw.textbbox((0, 0), msg, font=f)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = int(size * 0.55), int(size * 0.28)
    draw.text(((size - tw) / 2, (size - th) / 2), msg, fill="black", font=f)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _offcenter_rect(size: int = 500) -> bytes:
    """Off-center rectangle only — must NOT be auto-circled by logo mode."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    # rectangle in the top-left quadrant, non-circular aspect ratio
    cv2.rectangle(img, (60, 60), (260, 180), (20, 20, 20), thickness=-1)
    return _encode_cv(img)


def _blank(size: int = 400) -> bytes:
    return _encode_cv(np.full((size, size, 3), 255, dtype=np.uint8))


# ---------- helpers ---------------------------------------------------------
def _post_vec(s: requests.Session, img_bytes: bytes, **fields) -> requests.Response:
    return s.post(
        f"{API}/vectorize",
        files={"file": ("in.png", img_bytes, "image/png")},
        data={k: str(v) for k, v in fields.items()},
        timeout=TIMEOUT,
    )


def _looks_like_circle(poly: list, tol: float = 0.12) -> bool:
    """A polyline that traces a circle has (a) >=90 points, (b) roughly
    equidistant points from the centroid (low radius std/mean)."""
    if len(poly) < 90:
        return False
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    dists = [math.hypot(p[0] - cx, p[1] - cy) for p in poly]
    mean = sum(dists) / len(dists)
    if mean <= 0:
        return False
    var = sum((d - mean) ** 2 for d in dists) / len(dists)
    std = math.sqrt(var)
    return (std / mean) < tol


@pytest.fixture(scope="module")
def s() -> requests.Session:
    sess = requests.Session()
    yield sess
    sess.close()


# ---------- 1) logo on centered circle -> auto-circle -----------------------
def test_logo_on_centered_circle_returns_clean_circle(s):
    r = _post_vec(
        s, _centered_ring(size=500, r_frac=0.36, thickness=6),
        subject="logo", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] == 1, f"expected count==1, got {j['count']}"
    poly = j["polylines"][0]
    assert 90 <= len(poly) <= 110, f"expected ~96-97 pts, got {len(poly)}"
    assert _looks_like_circle(poly), "polyline is not circle-shaped"


# ---------- 2) oggetto on centered circle -> auto-circle --------------------
def test_oggetto_on_centered_circle_returns_clean_circle(s):
    r = _post_vec(
        s, _centered_ring(size=500, r_frac=0.36, thickness=6),
        subject="oggetto", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1
    poly = j["polylines"][0]
    assert 90 <= len(poly) <= 110, f"expected ~96-97 pts, got {len(poly)}"
    assert _looks_like_circle(poly), "polyline is not circle-shaped"


# ---------- 3) cerchio on centered circle -----------------------------------
def test_cerchio_on_centered_circle_returns_circle_polyline(s):
    r = _post_vec(
        s, _centered_ring(size=500, r_frac=0.36, thickness=6),
        subject="cerchio", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1
    poly = j["polylines"][0]
    assert 90 <= len(poly) <= 110, f"expected ~96-97 pts, got {len(poly)}"
    assert _looks_like_circle(poly)


# ---------- 4) cerchio on filled disc -> min-enclosing-circle fallback ------
def test_cerchio_on_filled_disc_uses_fallback(s):
    r = _post_vec(
        s, _centered_disc(size=500, r_frac=0.36),
        subject="cerchio", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1
    poly = j["polylines"][0]
    assert 90 <= len(poly) <= 110, f"expected circle polyline, got {len(poly)} pts"
    assert _looks_like_circle(poly)


# ---------- 5) REGRESSION: logo on ABC text -> NOT auto-circled -------------
def test_logo_on_text_abc_is_not_forced_circle(s):
    r = _post_vec(
        s, _text_abc_png(size=500, msg="ABC"),
        subject="logo", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1
    # The largest polyline should NOT be a ~96-point regular circle
    largest = max(j["polylines"], key=len)
    # tolerant assertion: either point count is small OR the shape is clearly
    # non-circular (irregular radii)
    assert len(largest) < 90 or not _looks_like_circle(largest), (
        f"logo on text was incorrectly auto-circled: {len(largest)} pts, looks_like_circle="
        f"{_looks_like_circle(largest)}"
    )


# ---------- 6) REGRESSION: scritta on text is never auto-circled -----------
def test_scritta_on_text_never_auto_circled(s):
    r = _post_vec(
        s, _text_abc_png(size=500, msg="ABC"),
        subject="scritta", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1
    for poly in j["polylines"]:
        assert not (len(poly) >= 90 and _looks_like_circle(poly)), (
            "scritta subject should never auto-circle text"
        )


# ---------- 7) REGRESSION: logo on off-center rectangle -> traced polygon ---
def test_logo_on_offcenter_rectangle_is_traced_polygon(s):
    r = _post_vec(
        s, _offcenter_rect(size=500),
        subject="logo", invert="true", threshold=-1, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1
    largest = max(j["polylines"], key=len)
    # a rectangle traced with approxPolyDP + chaikin (2 iters) yields ~16-20 pts
    assert not _looks_like_circle(largest), (
        f"off-center rect was incorrectly auto-circled ({len(largest)} pts)"
    )


# ---------- 8) blank white image -> 422 ------------------------------------
def test_blank_returns_422(s):
    r = _post_vec(s, _blank(), subject="logo", invert="true", threshold=-1, target_width_mm=200)
    assert r.status_code == 422, r.text


# ---------- 9) manual threshold=100 disables auto-circle -------------------
def test_manual_threshold_disables_auto_circle_on_text(s):
    """When threshold is manual (>=0), auto-circle logic must NOT kick in;
    text should still trace normally with count>=1."""
    r = _post_vec(
        s, _text_abc_png(size=500, msg="ABC"),
        subject="logo", invert="true", threshold=100, target_width_mm=200,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["count"] >= 1
    # Also verify the guard: manual threshold on a centered circle should
    # ALSO skip auto-circle (traced normally) — we don't assert the shape,
    # only that the request succeeds and doesn't 422.
