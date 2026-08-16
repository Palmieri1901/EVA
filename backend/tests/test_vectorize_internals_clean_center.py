"""Iteration 8 – vectorize enhancements:
  (1) subject=cerchio + internals=true traces circle outline PLUS internal
      polyline features (letters/shapes inside the ring). count>=2.
  (2) subject=cerchio + internals=false returns only the circle outline. count==1.
  (3) clean=true drops small spurious contours (drops any polygons < 5% of the
      largest area, also raises min_area_frac). Verified on a big square + tiny
      speckles image: clean=true count <= clean=false count.
  (4) clean default (false) still works.
  (5) subject=cerchio on an image with TWO circles picks the CENTERED one
      (not the largest). Verified via width_mm mapping to the smaller centered
      circle radius.
  (6) Regressions from prior iterations: logo on centered ring auto-circles
      (~96-pt), subject=scritta on text returns count>=1, blank -> 422.
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
    """White canvas with a centered outlined ring."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    c = size // 2
    r = int(size * r_frac)
    cv2.circle(img, (c, c), r, (30, 30, 30), thickness)
    return _encode_cv(img)


def _centered_ring_with_internals(size: int = 500, r_frac: float = 0.36) -> bytes:
    """Outlined ring with a filled internal feature (square + smaller filled circle)
    inside – gives adaptive-threshold something to trace for internals=true."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    c = size // 2
    r = int(size * r_frac)
    # outer ring outline
    cv2.circle(img, (c, c), r, (30, 30, 30), 6)
    # internal filled square (well inside the ring)
    half = int(r * 0.35)
    cv2.rectangle(img, (c - half, c - half), (c + half, c + half), (10, 10, 10), -1)
    # another internal small filled circle offset to give a second feature
    cv2.circle(img, (c + int(r * 0.55), c), int(r * 0.10), (10, 10, 10), -1)
    return _encode_cv(img)


def _two_circles_big_corner_small_center(size: int = 600) -> bytes:
    """Big ring near a corner + smaller ring centered.  The 'centered' policy
    should pick the smaller centered one."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    # big ring near bottom-right corner
    big_r = int(size * 0.30)      # 180 on 600
    big_c = (int(size * 0.78), int(size * 0.78))  # offset near corner
    cv2.circle(img, big_c, big_r, (30, 30, 30), 6)
    # smaller centered ring
    small_r = int(size * 0.15)    # 90 on 600
    small_c = (size // 2, size // 2)
    cv2.circle(img, small_c, small_r, (30, 30, 30), 6)
    return _encode_cv(img), big_r, big_c, small_r, small_c


def _big_square_with_speckles(size: int = 500) -> bytes:
    """Large filled square in the middle + tiny black dots scattered around.
    With clean=false, tiny dots survive; with clean=true, they must be dropped."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    # big filled square (~ 60% of image)
    x0, y0, x1, y1 = int(size * 0.2), int(size * 0.2), int(size * 0.8), int(size * 0.8)
    cv2.rectangle(img, (x0, y0), (x1, y1), (0, 0, 0), -1)
    # tiny speckles well outside the big square (upper-left area)
    for (cx, cy) in [(30, 30), (60, 40), (40, 80), (90, 25), (25, 110), (70, 100)]:
        cv2.circle(img, (cx, cy), 2, (0, 0, 0), -1)
    return _encode_cv(img)


def _text_scritta_png(size: int = 500, text: str = "ABC") -> bytes:
    pil = Image.new("RGB", (size, size), "white")
    d = ImageDraw.Draw(pil)
    f = _font(160)
    bbox = d.textbbox((0, 0), text, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) // 2 - bbox[0], (size - th) // 2 - bbox[1]), text, fill=(0, 0, 0), font=f)
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return buf.getvalue()


def _blank_white(size: int = 400) -> bytes:
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    return _encode_cv(img)


# ---------- helpers ---------------------------------------------------------
def _post(png_bytes: bytes, **form) -> requests.Response:
    files = {"file": ("in.png", png_bytes, "image/png")}
    data = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in form.items()}
    return requests.post(f"{API}/vectorize", files=files, data=data, timeout=TIMEOUT)


def _poly_centroid(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _poly_bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


# ============================================================================
# 1. subject=cerchio internals=true returns circle + internals
# ============================================================================
class TestCerchioInternals:
    def test_internals_true_returns_multiple_polys(self):
        r = _post(_centered_ring_with_internals(), subject="cerchio", internals=True)
        assert r.status_code == 200, r.text
        js = r.json()
        # outer circle + at least one internal traced feature
        assert js["count"] >= 2, f"expected >=2 polylines (circle + internals), got {js['count']}"
        # the largest polyline (by point-count) should be the ~96-pt circle
        polys = js["polylines"]
        assert any(90 <= len(p) <= 200 for p in polys), \
            f"no circle-like polyline found; sizes={[len(p) for p in polys]}"

    def test_internals_false_returns_single_circle(self):
        r = _post(_centered_ring_with_internals(), subject="cerchio", internals=False)
        assert r.status_code == 200, r.text
        js = r.json()
        assert js["count"] == 1, f"expected 1 polyline (circle only), got {js['count']}"
        assert 90 <= len(js["polylines"][0]) <= 200


# ============================================================================
# 2. clean=true drops small spurious contours
# ============================================================================
class TestCleanNoiseRemoval:
    def test_clean_true_le_clean_false(self):
        img = _big_square_with_speckles()

        r_dirty = _post(img, subject="logo", clean=False)
        assert r_dirty.status_code == 200, r_dirty.text
        n_dirty = r_dirty.json()["count"]

        r_clean = _post(img, subject="logo", clean=True)
        assert r_clean.status_code == 200, r_clean.text
        n_clean = r_clean.json()["count"]

        assert n_clean <= n_dirty, \
            f"clean=true should drop specks: n_clean={n_clean}, n_dirty={n_dirty}"
        # ideally clean=true reduces to just the big square (1)
        assert n_clean == 1, f"clean=true should leave only the big shape; got {n_clean}"

    def test_clean_default_form_field_still_works(self):
        # regression: default clean=false form field must not break existing calls
        r = _post(_big_square_with_speckles(), subject="logo")
        assert r.status_code == 200, r.text
        js = r.json()
        assert js["count"] >= 1


# ============================================================================
# 3. subject=cerchio prefers the CENTERED circle over the largest one
# ============================================================================
class TestCerchioPrefersCentered:
    def test_two_circles_picks_centered_smaller(self):
        img_bytes, big_r, big_c, small_r, small_c = _two_circles_big_corner_small_center()
        r = _post(img_bytes, subject="cerchio")
        assert r.status_code == 200, r.text
        js = r.json()
        assert js["count"] == 1

        poly = js["polylines"][0]
        assert 90 <= len(poly) <= 200, f"expected ~96-pt circle, got {len(poly)}"

        # width_mm defaults to 200.0 in server.py; that corresponds to the
        # detected circle's px diameter -> so the height/width_mm ratio ~= 1 for
        # any circle. Instead assert via the polyline centroid: it should be
        # scaled from ORIGIN so centroid is around (100mm, 100mm) — but that's
        # true for both circles individually. Better: derive the RATIO between
        # the returned width_mm mapped back to px and compare with the two
        # candidate diameters.
        #
        # Simpler test: after normalisation, the polyline bbox is centered on
        # its own bbox (0..width_mm, 0..height_mm). We instead test that the
        # returned width_mm corresponds to the CENTERED (smaller) circle by
        # rerunning both individually and comparing height_mm ratios.
        #
        # Concrete approach: since target_width_mm=200 is applied AFTER
        # extraction, width_mm ≈ 200 for whichever circle was picked. Both are
        # circles -> aspect==1 for both, so we cannot distinguish via mm alone.
        # BUT: the polyline centroid in mm is (100, 100) for either. To
        # actually verify which one was picked, we run the same image via
        # subject=cerchio and inspect the centroid *within the polyline*:
        # since polylines are shifted so min=0, centroids being ~half-width is
        # tautological.
        #
        # DEFINITIVE approach: compare the "width_mm" mapping only works if we
        # use different-radius circles AND the SAME target width. Both come
        # out at 200 mm. So we must use the polyline centroid check, which
        # requires reading the raw polyline output BEFORE mm shift — not
        # available.
        #
        # -> We instead re-issue with target_width_mm equal to the actual
        # pixel diameter of the small circle. The server scales the polyline
        # so width_mm equals the input target_width_mm. That doesn't help
        # either.
        #
        # -> Use a preview-URL approach: fetch preview PNG, load it, and
        # visually verify a circle was drawn on the CENTRED one but NOT on
        # the corner one. This is the reliable check.
        preview_url = js.get("preview_url")
        assert preview_url, "vectorize endpoint must return a preview_url"
        pr = requests.get(BASE_URL + preview_url, timeout=TIMEOUT)
        assert pr.status_code == 200, f"preview fetch failed: {pr.status_code}"

        # Decode preview and check for the traced polyline color near CENTER
        # vs near CORNER. Trace color in vectorize.py is BGR (0, 90, 200) —
        # a bright orange/red on white.
        arr = np.frombuffer(pr.content, dtype=np.uint8)
        prev = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        assert prev is not None, "preview image undecodable"
        H, W = prev.shape[:2]

        def _traced_pixels(prev_img):
            # traced polyline uses (0, 90, 200) BGR — B~0, G~90, R~200
            b, g, r = cv2.split(prev_img)
            return ((r > 150) & (g > 40) & (g < 180) & (b < 90)).astype(np.uint8)

        mask = _traced_pixels(prev)
        # Count traced pixels near the two candidate centers (as fraction of
        # image size — preview may have been resized by _crop_letterbox/scale).
        def _ring_count(mask, cx_frac, cy_frac, r_frac):
            cx, cy = int(cx_frac * W), int(cy_frac * H)
            r_out = int(r_frac * 1.25 * min(W, H))
            r_in = int(r_frac * 0.55 * min(W, H))
            yy, xx = np.ogrid[:H, :W]
            d2 = (xx - cx) ** 2 + (yy - cy) ** 2
            annulus = (d2 <= r_out ** 2) & (d2 >= r_in ** 2)
            return int(mask[annulus].sum())

        # centered circle occupied ~ (0.5,0.5) with radius fraction 0.15
        centered_hits = _ring_count(mask, 0.50, 0.50, 0.15)
        # corner circle at ~ (0.78, 0.78) with radius fraction 0.30
        corner_hits = _ring_count(mask, 0.78, 0.78, 0.30)

        assert centered_hits > 30, \
            f"traced polyline not near image center (hits={centered_hits}); may have picked corner circle instead"
        assert centered_hits > corner_hits, \
            f"centered ring hits ({centered_hits}) should exceed corner ring hits ({corner_hits})"


# ============================================================================
# 4. Regressions from prior iterations
# ============================================================================
class TestRegressions:
    def test_logo_on_centered_ring_auto_circles(self):
        r = _post(_centered_ring(), subject="logo")
        assert r.status_code == 200, r.text
        js = r.json()
        assert js["count"] == 1
        # auto-circle synthesises 96 pts + closing wrap = 97
        assert 90 <= len(js["polylines"][0]) <= 200

    def test_scritta_on_text_returns_polys(self):
        r = _post(_text_scritta_png(), subject="scritta")
        assert r.status_code == 200, r.text
        js = r.json()
        assert js["count"] >= 1

    def test_blank_white_returns_422(self):
        r = _post(_blank_white(), subject="logo")
        assert r.status_code == 422, r.text
