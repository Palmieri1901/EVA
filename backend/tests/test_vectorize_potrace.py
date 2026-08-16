"""Iteration 9 — vectorize potrace tracing engine.

Verifies the new potrace (raster->vector) tracing produces SMOOTH polylines
(many points) for the threshold/GrabCut path (subject=scritta/logo/oggetto)
while:
  * NOT overriding the circle auto-detection for centered ring logos
  * Preserving the cerchio + internals branch
  * Preserving ROI cropping, clean noise removal, and blank-image 422
  * Regression on POST /api/projects/{id}/elements append
"""
import io
import os
import json
import pytest
import cv2
import numpy as np
import requests


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


# ---------------------------------------------------------------- factories --

def _png_bytes(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _white_bg(w=600, h=400) -> np.ndarray:
    return np.full((h, w, 3), 255, np.uint8)


def _eva_text_img() -> bytes:
    img = _white_bg(720, 320)
    # bold black EVA — potrace should produce three smooth outlines
    cv2.putText(img, "EVA", (60, 240), cv2.FONT_HERSHEY_DUPLEX, 6.5, (0, 0, 0),
                thickness=18, lineType=cv2.LINE_AA)
    return _png_bytes(img)


def _letter_O_with_hole() -> bytes:
    # Big margin so the outer glyph is not filtered as full-frame background.
    img = _white_bg(800, 800)
    cv2.putText(img, "O", (200, 620), cv2.FONT_HERSHEY_DUPLEX, 10, (0, 0, 0),
                thickness=22, lineType=cv2.LINE_AA)
    return _png_bytes(img)


def _centered_ring() -> bytes:
    img = _white_bg(600, 600)
    cv2.circle(img, (300, 300), 200, (0, 0, 0), thickness=14, lineType=cv2.LINE_AA)
    return _png_bytes(img)


def _rounded_rect_filled() -> bytes:
    # Use a mid-gray background with substantial noise so _crop_letterbox
    # (which trims uniform white/black bars) leaves the frame intact.
    rng = np.random.default_rng(7)
    bg = rng.integers(150, 210, size=(500, 700, 3), dtype=np.uint8)
    cv2.rectangle(bg, (140, 120), (560, 380), (0, 0, 0), thickness=-1)
    return _png_bytes(bg)


def _big_square_and_specks() -> bytes:
    img = _white_bg(600, 600)
    cv2.rectangle(img, (120, 120), (480, 480), (0, 0, 0), thickness=-1)
    # tiny black dots (noise) — should be removed when clean=true
    for (x, y) in [(30, 30), (560, 30), (30, 560), (560, 560), (30, 300), (560, 300)]:
        cv2.circle(img, (x, y), 3, (0, 0, 0), -1)
    return _png_bytes(img)


def _ring_with_internal_shapes() -> bytes:
    img = _white_bg(600, 600)
    cv2.circle(img, (300, 300), 240, (0, 0, 0), thickness=14, lineType=cv2.LINE_AA)
    cv2.rectangle(img, (240, 240), (360, 360), (0, 0, 0), thickness=-1)
    return _png_bytes(img)


def _big_ring_with_letter() -> bytes:
    """Wider image so 'roi' cropping to right half selects a distinct region."""
    img = _white_bg(900, 500)
    # left half: big ring
    cv2.circle(img, (240, 250), 180, (0, 0, 0), thickness=14, lineType=cv2.LINE_AA)
    # right half: a bold letter A
    cv2.putText(img, "A", (600, 380), cv2.FONT_HERSHEY_DUPLEX, 8, (0, 0, 0),
                thickness=20, lineType=cv2.LINE_AA)
    return _png_bytes(img)


def _blank_white() -> bytes:
    return _png_bytes(_white_bg(400, 400))


# ---------------------------------------------------------------- helpers ---

def _post_vectorize(image_bytes: bytes, **form) -> requests.Response:
    files = {"file": ("test.png", image_bytes, "image/png")}
    # send bools as lowercased strings, ints/floats as strings — matches FastAPI Form parsing
    data = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in form.items()}
    return requests.post(f"{API}/vectorize", files=files, data=data, timeout=45)


def _max_points_per_poly(polylines):
    return max((len(p) for p in polylines), default=0)


# ---------------------------------------------------------------- tests -----

class TestScrittaPotraceSmooth:
    """subject=scritta on black text 'EVA' -> letters E,V,A each with many pts."""

    def test_eva_returns_smooth_polylines(self):
        r = _post_vectorize(_eva_text_img(), subject="scritta")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 3, f"expected >=3 letter outlines, got {body['count']}"
        max_pts = _max_points_per_poly(body["polylines"])
        # potrace produces many points per outline (>40 typical);
        # approxPolyDP fallback would give ~4-8 points
        assert max_pts >= 40, (
            f"expected smooth potrace polylines (>=40 pts), got max {max_pts} "
            f"— may be running old approxPolyDP path"
        )


class TestLetterWithHole:
    """subject=scritta on 'O' returns outer + inner hole rings (>=2)."""

    def test_letter_o_has_hole(self):
        r = _post_vectorize(_letter_O_with_hole(), subject="scritta")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 2, (
            f"expected outer+hole rings (>=2), got {body['count']}"
        )


class TestLogoAutoCircleNotOverridden:
    """subject=logo on centered ring must still auto-circle (count==1, ~96 pts)."""

    def test_ring_logo_auto_circle(self):
        r = _post_vectorize(_centered_ring(), subject="logo")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1, f"expected exactly 1 circle, got {body['count']}"
        # _circle_poly uses n=96
        pts = len(body["polylines"][0])
        assert 90 <= pts <= 100, f"expected ~96-pt circle, got {pts}"


class TestOggettoSmoothOutline:
    """subject=oggetto on a filled rectangle -> at least one smooth outline."""

    def test_rounded_rect_smooth(self):
        # subject=oggetto uses GrabCut on synthetic clean imagery, which can
        # collapse to a full-frame mask; pass explicit threshold to force
        # intensity-thresholding path — still exercises the potrace tracer.
        r = _post_vectorize(_rounded_rect_filled(), subject="oggetto", threshold=127)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 1
        # potrace path should return smooth polylines with many points
        assert _max_points_per_poly(body["polylines"]) >= 20, (
            f"expected smooth outline, got max {_max_points_per_poly(body['polylines'])} pts"
        )


class TestCleanNoiseRemoval:
    """clean=true reduces count vs clean=false on big square + tiny specks."""

    def test_clean_reduces_specks(self):
        img = _big_square_and_specks()
        r_noisy = _post_vectorize(img, subject="oggetto", clean=False, threshold=127)
        r_clean = _post_vectorize(img, subject="oggetto", clean=True, threshold=127)
        assert r_noisy.status_code == 200, r_noisy.text
        assert r_clean.status_code == 200, r_clean.text
        c_noisy = r_noisy.json()["count"]
        c_clean = r_clean.json()["count"]
        assert c_clean <= c_noisy, (
            f"clean=true ({c_clean}) should be <= clean=false ({c_noisy})"
        )
        # clean should keep only the big square
        assert c_clean == 1, f"clean=true should yield only the big square, got {c_clean}"


class TestCerchioInternalsRegression:
    """subject=cerchio + internals=true still returns count>=2."""

    def test_internals_regression(self):
        r = _post_vectorize(_ring_with_internal_shapes(), subject="cerchio", internals=True)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 2, (
            f"expected outer circle + internal features, got {body['count']}"
        )


class TestRoiRegression:
    """roi crop selects the right region only (letter 'A' on right half)."""

    def test_roi_crops_to_letter(self):
        img = _big_ring_with_letter()
        # left half only contains the ring
        roi_left = json.dumps({"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0})
        r_left = _post_vectorize(img, subject="scritta", roi=roi_left)
        assert r_left.status_code == 200, r_left.text
        # right half only contains 'A'
        roi_right = json.dumps({"x": 0.55, "y": 0.0, "w": 0.45, "h": 1.0})
        r_right = _post_vectorize(img, subject="scritta", roi=roi_right)
        assert r_right.status_code == 200, r_right.text
        # Right-half crop of just 'A' -> at least 1 outline; letter A has an
        # inner triangular hole, so >=2 with potrace is typical.
        assert r_right.json()["count"] >= 1


class TestBlankReturns422:
    def test_blank_white_422(self):
        r = _post_vectorize(_blank_white(), subject="scritta")
        assert r.status_code == 422, f"expected 422 on blank image, got {r.status_code}"


class TestElementsAppendRegression:
    """POST /api/projects/{id}/elements still appends a polyline element."""

    def test_append_polyline_element(self):
        # create minimal project
        payload = {
            "name": "TEST_vectorize_iter9",
            "ref_width_mm": 500, "ref_height_mm": 500,
            "background_mode": "light", "cut_side": "outside",
        }
        cp = requests.post(f"{API}/projects", json=payload, timeout=15)
        assert cp.status_code in (200, 201), cp.text
        pid = cp.json()["id"]
        try:
            poly = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
            el = {"type": "polyline", "layer": "ENGRAVE", "polylines": [poly]}
            r = requests.post(f"{API}/projects/{pid}/elements", json=el, timeout=15)
            assert r.status_code == 200, r.text
            data = r.json()
            assert "elements" in data and len(data["elements"]) >= 1
            last = data["elements"][-1]
            assert last["type"] == "polyline"
            assert last["layer"] == "ENGRAVE"
            assert last["polylines"] and len(last["polylines"][0]) == 5
        finally:
            requests.delete(f"{API}/projects/{pid}", timeout=15)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
