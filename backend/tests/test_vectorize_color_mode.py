"""Iteration 10 — vectorize COLOUR mode (vtracer) + regressions.

Verifies the new subject=colore engine (vtracer-based multi-colour region
tracer) and that the pre-existing subject modes still function.

Checks:
  * subject=colore on a synthetic multi-colour logo returns 200 with
    count>0, width_mm>0, height_mm>0, preview_url (rendered PNG) and dxf_url,
    both fetchable (HTTP 200 on GET).
  * REGRESSION subject=scritta on black-text-on-white PNG returns 200,count>0.
  * REGRESSION subject=logo   on dark-shape-on-light PNG returns 200,count>0.
  * REGRESSION subject=cerchio on a filled circle returns a circular polyline.
  * The preview PNG for subject=colore is a real RGB/RGBA PNG (magic bytes).
"""
import io
import os
import pytest
import cv2
import numpy as np
import requests


BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


# ---------------------------------------------------------------- factories --

def _png_bytes(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok, "failed to encode PNG"
    return buf.tobytes()


def _white_bg(w=600, h=400) -> np.ndarray:
    return np.full((h, w, 3), 255, np.uint8)


def _multicolour_logo() -> bytes:
    """Synthetic 'BMW-ish' colour emblem: blue quadrant, white quadrant, red
    ring, plus black bold text 'M'. Enough distinct colour regions so vtracer
    returns multiple traced regions."""
    img = _white_bg(700, 700)
    # outer black ring
    cv2.circle(img, (350, 350), 260, (30, 30, 30), thickness=22, lineType=cv2.LINE_AA)
    # inner blue quadrants (top-left / bottom-right in BGR: strong blue)
    cv2.ellipse(img, (350, 350), (230, 230), 0, 180, 270, (200, 60, 30), -1, cv2.LINE_AA)
    cv2.ellipse(img, (350, 350), (230, 230), 0, 0, 90, (200, 60, 30), -1, cv2.LINE_AA)
    # a bold red rectangle badge at the bottom
    cv2.rectangle(img, (200, 560), (500, 640), (40, 40, 220), thickness=-1)
    # black bold text 'M' in the centre
    cv2.putText(img, "M", (275, 430), cv2.FONT_HERSHEY_DUPLEX, 5.0, (0, 0, 0),
                thickness=14, lineType=cv2.LINE_AA)
    return _png_bytes(img)


def _black_text_on_white() -> bytes:
    img = _white_bg(720, 320)
    cv2.putText(img, "EVA", (60, 240), cv2.FONT_HERSHEY_DUPLEX, 6.5, (0, 0, 0),
                thickness=18, lineType=cv2.LINE_AA)
    return _png_bytes(img)


def _dark_shape_on_light() -> bytes:
    # dark rounded diamond shape on a slightly noisy light background so
    # _crop_letterbox (which strips uniform white bars) leaves the frame intact
    rng = np.random.default_rng(3)
    bg = rng.integers(225, 250, size=(500, 700, 3), dtype=np.uint8)
    pts = np.array([[350, 100], [600, 250], [350, 400], [100, 250]], np.int32)
    cv2.fillPoly(bg, [pts], (25, 25, 25))
    return _png_bytes(bg)


def _filled_circle() -> bytes:
    img = _white_bg(600, 600)
    cv2.circle(img, (300, 300), 200, (0, 0, 0), thickness=-1, lineType=cv2.LINE_AA)
    return _png_bytes(img)


# ---------------------------------------------------------------- helpers ---

def _post_vectorize(image_bytes: bytes, **form) -> requests.Response:
    files = {"file": ("test.png", image_bytes, "image/png")}
    data = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in form.items()}
    return requests.post(f"{API}/vectorize", files=files, data=data, timeout=60)


def _absolute(url: str) -> str:
    """server returns URLs starting with /api/files/... — prepend BASE_URL."""
    if url.startswith("http"):
        return url
    return f"{BASE_URL}{url}"


# ---------------------------------------------------------------- tests -----

class TestColoreMode:
    """New subject=colore engine (vtracer)."""

    def test_colore_full_pipeline(self):
        r = _post_vectorize(_multicolour_logo(), subject="colore")
        assert r.status_code == 200, r.text
        body = r.json()
        # required response fields
        for key in ("polylines", "count", "width_mm", "height_mm", "preview_url", "dxf_url"):
            assert key in body, f"missing field '{key}' in response: {body}"
        assert body["count"] > 0, f"expected count>0, got {body['count']}"
        assert body["width_mm"] > 0, f"expected width_mm>0, got {body['width_mm']}"
        assert body["height_mm"] > 0, f"expected height_mm>0, got {body['height_mm']}"
        assert body["preview_url"], "preview_url is empty/None"
        assert body["dxf_url"], "dxf_url is empty/None"
        # each polyline must be a list of at least 3 [x,y] points
        for poly in body["polylines"]:
            assert len(poly) >= 3, f"polyline too short: {len(poly)} pts"

    def test_colore_preview_and_dxf_fetchable(self):
        r = _post_vectorize(_multicolour_logo(), subject="colore")
        assert r.status_code == 200, r.text
        body = r.json()

        # GET preview PNG
        prev_r = requests.get(_absolute(body["preview_url"]), timeout=30)
        assert prev_r.status_code == 200, f"preview fetch failed: {prev_r.status_code}"
        assert prev_r.content[:8] == b"\x89PNG\r\n\x1a\n", (
            f"preview is not a PNG (magic: {prev_r.content[:8]!r})"
        )
        # sanity: decode with opencv
        arr = np.frombuffer(prev_r.content, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
        assert img is not None, "opencv could not decode the preview PNG"
        assert img.shape[0] > 0 and img.shape[1] > 0

        # GET DXF
        dxf_r = requests.get(_absolute(body["dxf_url"]), timeout=30)
        assert dxf_r.status_code == 200, f"dxf fetch failed: {dxf_r.status_code}"
        assert dxf_r.content[:2] == b"  " or b"SECTION" in dxf_r.content[:2048], (
            "DXF content missing expected 'SECTION' header"
        )


class TestScrittaRegression:
    def test_scritta_black_text(self):
        r = _post_vectorize(_black_text_on_white(), subject="scritta")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] > 0, f"expected count>0, got {body['count']}"
        assert body["polylines"], "no polylines returned"


class TestLogoRegression:
    def test_logo_dark_shape(self):
        r = _post_vectorize(_dark_shape_on_light(), subject="logo")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] > 0, f"expected count>0, got {body['count']}"


class TestCerchioRegression:
    def test_cerchio_circle_polyline(self):
        r = _post_vectorize(_filled_circle(), subject="cerchio")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] >= 1, f"expected >=1 circle polyline, got {body['count']}"
        # _circle_poly uses n=96 -> 97 points after closing
        pts = len(body["polylines"][0])
        assert 90 <= pts <= 100, f"expected ~96-pt circle polyline, got {pts}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
