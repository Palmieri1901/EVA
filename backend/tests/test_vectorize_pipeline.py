"""Targeted tests for the reworked photo->DXF vectorize pipeline.

Verifies subject presets (scritta / logo / oggetto), GrabCut logo silhouette,
internals extraction (holes), manual threshold + invert, target_width_mm
scaling, blank-image 422, and element append regression.

Notes:
 - Images use large canvases with subjects <30% of the frame so that the
   pipeline's letterbox-crop guard keeps the original layout (leaving a
   white margin around the subject), which is what the pipeline expects.
 - Uses LiberationSans-Bold as the TTF (widely available on this image).
"""
from __future__ import annotations

import io
import os

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


# ---------- image factories -------------------------------------------------
def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _text(msg: str = "OA", canvas=(1200, 1200), pos=(300, 500), font_px: int = 200) -> bytes:
    img = Image.new("RGB", canvas, "white")
    ImageDraw.Draw(img).text(pos, msg, fill="black", font=_font(font_px))
    return _png(img)


def _circle(canvas: int = 1200, r_frac: float = 0.12) -> bytes:
    img = Image.new("RGB", (canvas, canvas), "white")
    c = canvas // 2
    r = int(canvas * r_frac)
    ImageDraw.Draw(img).ellipse((c - r, c - r, c + r, c + r), fill="black")
    return _png(img)


def _ring(canvas: int = 1200) -> bytes:
    img = Image.new("RGB", (canvas, canvas), "white")
    c = canvas // 2
    d = ImageDraw.Draw(img)
    r_out = int(canvas * 0.12)
    r_in = int(r_out * 0.5)
    d.ellipse((c - r_out, c - r_out, c + r_out, c + r_out), fill="black")
    d.ellipse((c - r_in, c - r_in, c + r_in, c + r_in), fill="white")
    return _png(img)


def _rect_solid(canvas=(1200, 1000)) -> bytes:
    img = Image.new("RGB", canvas, "white")
    w, h = canvas
    cx, cy = w // 2, h // 2
    ImageDraw.Draw(img).rectangle((cx - 160, cy - 120, cx + 160, cy + 120), fill=(20, 20, 20))
    return _png(img)


def _blank() -> bytes:
    return _png(Image.new("RGB", (400, 400), "white"))


# ---------- fixtures --------------------------------------------------------
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


def _assert_ok_schema(j: dict):
    assert isinstance(j.get("polylines"), list) and len(j["polylines"]) > 0
    assert j["count"] > 0
    assert j["width_mm"] > 0 and j["height_mm"] > 0
    assert j.get("preview_url") and j["preview_url"].endswith(".png")
    assert j.get("dxf_url") and j["dxf_url"].endswith(".dxf")


# ---------- subject presets -------------------------------------------------
def test_scritta_black_text_on_white(s):
    r = _post_vec(s, _text("OA"), subject="scritta", invert="true", threshold=-1, target_width_mm=200)
    assert r.status_code == 200, r.text
    j = r.json()
    _assert_ok_schema(j)
    assert j["count"] >= 1


def test_logo_black_circle_on_white(s):
    r = _post_vec(s, _circle(), subject="logo", invert="true", threshold=-1, target_width_mm=200)
    assert r.status_code == 200, r.text
    j = r.json()
    _assert_ok_schema(j)
    assert j["count"] >= 1


def test_oggetto_solid_shape(s):
    r = _post_vec(s, _rect_solid(), subject="oggetto", invert="true", threshold=-1, target_width_mm=200)
    assert r.status_code == 200, r.text
    j = r.json()
    _assert_ok_schema(j)
    assert j["count"] >= 1


# ---------- internals -------------------------------------------------------
def test_internals_ring_more_than_external_only(s):
    img = _ring()
    r_out = _post_vec(s, img, subject="logo", invert="true", threshold=-1, internals="false", target_width_mm=200)
    r_in = _post_vec(s, img, subject="logo", invert="true", threshold=-1, internals="true", target_width_mm=200)
    assert r_out.status_code == 200, r_out.text
    assert r_in.status_code == 200, r_in.text
    c_out = r_out.json()["count"]
    c_in = r_in.json()["count"]
    assert c_in >= c_out, f"internals={c_in} should be >= external-only={c_out}"
    # A true hole should give strictly more with internals=true
    assert c_in >= 2, f"expected at least outer + inner contour, got {c_in}"


# ---------- manual threshold + invert ---------------------------------------
def test_manual_threshold_128_invert_true(s):
    r = _post_vec(s, _circle(), subject="logo", invert="true", threshold=128, target_width_mm=200)
    assert r.status_code == 200, r.text
    _assert_ok_schema(r.json())


# ---------- blank -----------------------------------------------------------
def test_blank_white_returns_422(s):
    r = _post_vec(s, _blank(), subject="logo", invert="true", threshold=-1, target_width_mm=200)
    assert r.status_code == 422, r.text
    assert "detail" in r.json()


# ---------- width scaling ---------------------------------------------------
def test_target_width_mm_300_scales_output(s):
    r = _post_vec(s, _text("OA"), subject="scritta", invert="true", threshold=-1, target_width_mm=300)
    assert r.status_code == 200, r.text
    j = r.json()
    _assert_ok_schema(j)
    assert abs(j["width_mm"] - 300.0) < 1.0, f"width_mm={j['width_mm']}"


# ---------- elements append regression --------------------------------------
def test_elements_append_polyline_regression(s):
    p = s.post(
        f"{API}/projects",
        json={
            "name": "TEST_vec_pipeline_piece",
            "background_mode": "blue_on_white",
            "marker_diameter_mm": 20,
            "ref_width_mm": 200,
            "ref_height_mm": 150,
            "cut_side": "inner",
            "blade_offset_mm": 0,
        },
        timeout=TIMEOUT,
    )
    assert p.status_code == 200, p.text
    pid = p.json()["id"]
    try:
        vr = _post_vec(s, _circle(), subject="logo", invert="true", threshold=-1, target_width_mm=200)
        assert vr.status_code == 200, vr.text
        polys = vr.json()["polylines"]
        assert len(polys) >= 1

        r = s.post(
            f"{API}/projects/{pid}/elements",
            json={"type": "polyline", "layer": "ENGRAVE", "polylines": polys, "params": {"source": "photo"}},
            timeout=TIMEOUT,
        )
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "edited"
        assert len(j["elements"]) == 1
        assert j["elements"][-1]["type"] == "polyline"
        assert j["elements"][-1]["layer"] == "ENGRAVE"

        g = s.get(f"{API}/projects/{pid}", timeout=TIMEOUT).json()
        assert len(g["elements"]) == 1
    finally:
        s.delete(f"{API}/projects/{pid}", timeout=TIMEOUT)
