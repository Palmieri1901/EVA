"""Computer-vision pipeline: marker detection, homography rectification,
tape-edge segmentation and vectorization.

Designed to be robust to marker polarity (dark-on-light and light-on-dark)
and to fall back gracefully so the editor always receives a usable contour.
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger("cv")

MAX_RECTIFIED_PX = 2000  # cap output resolution
MIN_MM_PER_PX = 0.25


def imdecode_exif(data: bytes) -> Optional[np.ndarray]:
    """Decode image bytes to a BGR ndarray, honouring the EXIF orientation tag.

    cv2.imdecode ignores EXIF, so phone photos (which store the sensor image plus
    an orientation flag) come out rotated/mirrored. We use Pillow to apply the
    correct orientation first, then hand a properly-rotated array to OpenCV.
    """
    if not data:
        return None
    try:
        from io import BytesIO

        from PIL import Image, ImageOps

        pil = Image.open(BytesIO(data))
        pil = ImageOps.exif_transpose(pil)  # bake orientation into pixels
        pil = pil.convert("RGB")
        rgb = np.asarray(pil)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception as e:  # noqa: BLE001
        logger.warning("imdecode_exif fell back to cv2.imdecode: %s", e)
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


# --------------------------------------------------------------------------
# Marker detection
# --------------------------------------------------------------------------
def _candidate_markers(gray: np.ndarray, invert: bool) -> List[dict]:
    """Return circular blob candidates using Otsu threshold with given polarity."""
    flag = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    _, th = cv2.threshold(gray, 0, 255, flag + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    img_area = gray.shape[0] * gray.shape[1]
    out: List[dict] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < img_area * 3e-5 or area > img_area * 0.03:
            continue
        peri = cv2.arcLength(c, True)
        if peri <= 0:
            continue
        circ = 4 * math.pi * area / (peri * peri)
        if circ < 0.72:
            continue
        if len(c) < 5:
            continue
        (cx, cy), (MA, ma), _ = cv2.fitEllipse(c)
        diameter = (MA + ma) / 2.0
        # reject very elongated ellipses
        if min(MA, ma) / max(MA, ma) < 0.6:
            continue
        out.append({"x": float(cx), "y": float(cy), "d": float(diameter), "circ": float(circ)})
    return out


def detect_markers(bgr: np.ndarray, background_mode: str) -> List[dict]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # Try both polarities, prefer the one with a consistent cluster of >=5 blobs.
    dark = _candidate_markers(gray, invert=True)    # dark blobs on light bg
    light = _candidate_markers(gray, invert=False)  # light blobs on dark bg

    def score(cands: List[dict]) -> float:
        if len(cands) < 4:
            return -1
        ds = np.array([c["d"] for c in cands])
        med = np.median(ds)
        # keep blobs whose diameter is within 40% of median
        keep = [c for c in cands if abs(c["d"] - med) <= 0.4 * med]
        return len(keep) + (np.mean([c["circ"] for c in keep]) if keep else 0)

    chosen = dark if score(dark) >= score(light) else light
    if len(chosen) < 4:
        chosen = dark if len(dark) >= len(light) else light

    # filter to consistent size cluster
    if chosen:
        ds = np.array([c["d"] for c in chosen])
        med = np.median(ds)
        chosen = [c for c in chosen if abs(c["d"] - med) <= 0.45 * med]
    # sort by circularity, cap to a reasonable number
    chosen.sort(key=lambda c: -c["circ"])
    return chosen[:12]


def order_markers(markers: List[dict]) -> Tuple[List[dict], Optional[dict]]:
    """Return (4 corners ordered TL,TR,BR,BL, center marker or None)."""
    if len(markers) < 4:
        return [], None
    pts = np.array([[m["x"], m["y"]] for m in markers])
    s = pts.sum(axis=1)
    d = pts[:, 0] - pts[:, 1]
    tl = int(np.argmin(s))
    br = int(np.argmax(s))
    tr = int(np.argmax(d))
    bl = int(np.argmin(d))
    corner_idx = [tl, tr, br, bl]
    if len(set(corner_idx)) < 4:
        # degenerate; fall back to convex hull extremes
        return [], None
    corners = [markers[i] for i in corner_idx]

    # center = marker closest to centroid of corners, excluding the corners
    cxcy = np.mean([[c["x"], c["y"]] for c in corners], axis=0)
    center = None
    best = 1e18
    for i, m in enumerate(markers):
        if i in corner_idx:
            continue
        dist = (m["x"] - cxcy[0]) ** 2 + (m["y"] - cxcy[1]) ** 2
        if dist < best:
            best = dist
            center = m
    for c, role in zip(corners, ["corner_tl", "corner_tr", "corner_br", "corner_bl"]):
        c["role"] = role
    if center is not None:
        center["role"] = "center"
    return corners, center


# --------------------------------------------------------------------------
# Homography & rectification
# --------------------------------------------------------------------------
def compute_rectification(corners: List[dict], ref_w_mm: float, ref_h_mm: float):
    """Return (H_mm, mm_per_px, out_w_px, out_h_px, M_px).

    H_mm maps image px -> real mm. M_px maps image px -> output px raster.
    """
    src = np.array([[c["x"], c["y"]] for c in corners], dtype=np.float32)
    dst_mm = np.array([[0, 0], [ref_w_mm, 0], [ref_w_mm, ref_h_mm], [0, ref_h_mm]], dtype=np.float32)
    H_mm = cv2.getPerspectiveTransform(src, dst_mm)

    long_edge = max(ref_w_mm, ref_h_mm)
    mm_per_px = max(long_edge / MAX_RECTIFIED_PX, MIN_MM_PER_PX)
    out_w = max(2, int(round(ref_w_mm / mm_per_px)))
    out_h = max(2, int(round(ref_h_mm / mm_per_px)))

    dst_px = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    M_px = cv2.getPerspectiveTransform(src, dst_px)
    return H_mm, mm_per_px, out_w, out_h, M_px


# --------------------------------------------------------------------------
# Tape edge segmentation
# --------------------------------------------------------------------------
def tape_mask(rectified_bgr: np.ndarray, background_mode: str) -> np.ndarray:
    hsv = cv2.cvtColor(rectified_bgr, cv2.COLOR_BGR2HSV)
    mode = (background_mode or "blue_on_white").lower()
    # accept both legacy background modes and explicit colour names
    if mode in ("blue_on_white", "blu", "azzurro", "blue"):
        mask = cv2.inRange(hsv, np.array([90, 60, 40]), np.array([135, 255, 255]))
    elif mode in ("giallo", "yellow"):
        mask = cv2.inRange(hsv, np.array([18, 60, 60]), np.array([38, 255, 255]))
    elif mode in ("verde", "green"):
        mask = cv2.inRange(hsv, np.array([38, 50, 40]), np.array([85, 255, 255]))
    elif mode in ("rosso", "red"):
        m1 = cv2.inRange(hsv, np.array([0, 70, 50]), np.array([10, 255, 255]))
        m2 = cv2.inRange(hsv, np.array([170, 70, 50]), np.array([180, 255, 255]))
        mask = m1 | m2
    else:  # white_on_dark / bianco -> bright/white tape
        mask = cv2.inRange(hsv, np.array([0, 0, 165]), np.array([180, 70, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return mask


# colours the auto-detector will try, in a sensible order
TAPE_COLORS = ["blu", "giallo", "verde", "rosso", "bianco"]


def _tape_score(bgr: np.ndarray, color: str) -> float:
    """Quality of a tape colour = area of the region it encloses (its inner hole),
    as a fraction of the frame. 0 when the colour does not form a closed band."""
    H, W = bgr.shape[:2]
    area = float(H * W)
    mask = tape_mask(bgr, color)
    frac = float(np.count_nonzero(mask)) / area
    if frac < 0.01 or frac > 0.6:
        return 0.0
    cnt = extract_contour(mask, "inner")
    if cnt is None or len(cnt) < 4:
        return 0.0
    a = cv2.contourArea(cnt.astype(np.float32)) / area
    if a < 0.05 or a > 0.97:
        return 0.0
    return a


def best_tape_color(bgr: np.ndarray) -> Optional[str]:
    """Return the tape colour that best encloses a region, or None."""
    best, best_s = None, 0.0
    for c in TAPE_COLORS:
        s = _tape_score(bgr, c)
        if s > best_s:
            best_s, best = s, c
    return best


def _order_quad(pts: np.ndarray) -> np.ndarray:
    pts = np.array(pts, dtype=np.float32).reshape(-1, 2)
    s = pts.sum(axis=1)
    d = pts[:, 0] - pts[:, 1]
    tl = pts[int(np.argmin(s))]
    br = pts[int(np.argmax(s))]
    tr = pts[int(np.argmax(d))]
    bl = pts[int(np.argmin(d))]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def detect_tape_corner_dots(bgr: np.ndarray, color: str) -> Optional[np.ndarray]:
    """Detect WHITE marker-pen dots drawn on the coloured tape (e.g. white marks
    on blue tape) and return the 4 corner dots (TL,TR,BR,BL px). These give a more
    precise reference quad than the raw tape corners. Returns None if 4 sensible
    corner dots cannot be found."""
    H, W = bgr.shape[:2]
    band = tape_mask(bgr, color)
    # close the band so the white marks (holes in the colour) become part of it
    k = max(9, int(round(min(H, W) * 0.03)) | 1)
    region = cv2.morphologyEx(band, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8), iterations=2)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    white = cv2.inRange(hsv, np.array([0, 0, 180]), np.array([180, 60, 255]))
    marks = cv2.bitwise_and(white, region)
    marks = cv2.morphologyEx(marks, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(marks, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area = float(H * W)
    pts = []
    for c in cnts:
        a = cv2.contourArea(c)
        if a < area * 2e-5 or a > area * 0.02:
            continue
        (cx, cy), r = cv2.minEnclosingCircle(c)
        if r <= 0 or a / (math.pi * r * r) < 0.5:
            continue
        pts.append((cx, cy))
    if len(pts) < 4:
        return None
    arr = np.array(pts, dtype=np.float32)
    s = arr[:, 0] + arr[:, 1]
    d = arr[:, 0] - arr[:, 1]
    corners = np.array([
        arr[int(np.argmin(s))],  # TL
        arr[int(np.argmax(d))],  # TR
        arr[int(np.argmax(s))],  # BR
        arr[int(np.argmin(d))],  # BL
    ], dtype=np.float32)
    # reject if two picked corners collapse to the same dot (degenerate)
    for i in range(4):
        for j in range(i + 1, 4):
            if np.hypot(*(corners[i] - corners[j])) < min(H, W) * 0.05:
                return None
    return _order_quad(corners)


def detect_tape_quad(bgr: np.ndarray, color: str) -> Optional[np.ndarray]:
    """Return the 4 outer corners (TL,TR,BR,BL px) of the tape band for `color`,
    or None if the tape outline cannot be reduced to a sensible quadrilateral."""
    mask = tape_mask(bgr, color)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    peri = cv2.arcLength(c, True)
    if peri <= 0:
        return None
    # progressively relax until we get a 4-point hull-like polygon
    for eps in (0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(c, eps * peri, True).reshape(-1, 2)
        if len(approx) == 4:
            return _order_quad(approx)
    # fall back to the min-area rectangle corners
    box = cv2.boxPoints(cv2.minAreaRect(c))
    return _order_quad(box)


def extract_contour(mask: np.ndarray, cut_side: str) -> Optional[np.ndarray]:
    """Return contour points (Nx2, px) for the mat outline.

    The tape forms a closed band; the mat is the region bounded by the tape.
    inner = the hole inside the band, outer = the outer boundary of the band.
    """
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    # largest external contour = outer edge of tape band
    outer_idx = max(range(len(contours)), key=lambda i: cv2.contourArea(contours[i]))
    if cut_side == "outer" or hierarchy is None:
        cnt = contours[outer_idx]
        return cnt.reshape(-1, 2).astype(np.float32)

    # inner: find the largest child hole of the outer contour
    hier = hierarchy[0]
    child = hier[outer_idx][2]
    best_child = None
    best_area = 0
    while child != -1:
        a = cv2.contourArea(contours[child])
        if a > best_area:
            best_area = a
            best_child = child
        child = hier[child][0]
    if best_child is None:
        cnt = contours[outer_idx]
    else:
        cnt = contours[best_child]
    return cnt.reshape(-1, 2).astype(np.float32)


def px_to_mm(points_px: np.ndarray, mm_per_px: float) -> List[List[float]]:
    return [[float(p[0] * mm_per_px), float(p[1] * mm_per_px)] for p in points_px]


def simplify_contour_mm(points_mm: List[List[float]], tolerance_mm: float = 0.6) -> List[List[float]]:
    """Simplify + lightly smooth the contour while preserving corners."""
    if len(points_mm) < 4:
        return points_mm
    pts = np.array(points_mm, dtype=np.float32).reshape(-1, 1, 2)
    peri = cv2.arcLength(pts, True)
    eps = max(tolerance_mm, 0.002 * peri)
    approx = cv2.approxPolyDP(pts, eps, True).reshape(-1, 2)
    return [[float(x), float(y)] for x, y in approx]


# --------------------------------------------------------------------------
# Quality metrics
# --------------------------------------------------------------------------
def sharpness(bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())
