"""Markerless photogrammetry-style capture for FLAT pieces.

Combine several photos of a flat piece (shot from various angles at ~1 m) into a
single mosaic (OpenCV Stitcher), then rectify/scale using a user-provided
reference and extract the piece outline in millimetres.

Two reference types are supported:
  * "rect"  -> a rectangle of known width x height (4 tapped corners).
               Enables full perspective rectification (accurate, CNC-ready).
  * "line"  -> a segment of known length (2 tapped points).
               Sets scale only (no perspective correction).

The result mirrors the marker pipeline output so the editor works unchanged:
rectified image + contour_mm + mm_per_px.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import cv2
import numpy as np

import cv_pipeline as cv

log = logging.getLogger("photogram")

MAX_DIM = 2200  # cap image dimension for speed/memory


def _fit(img: np.ndarray, cap: int = MAX_DIM) -> np.ndarray:
    h, w = img.shape[:2]
    s = cap / float(max(h, w))
    if s < 1.0:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


# --------------------------------------------------------------------------
# 1) Mosaic: combine all photos into one image
# --------------------------------------------------------------------------
def stitch_photos(images: List[np.ndarray]) -> Tuple[Optional[np.ndarray], Optional[str]]:
    """Return (mosaic, warning). mosaic is None only on fatal error (2nd item = reason)."""
    imgs = [_fit(im) for im in images if im is not None]
    if not imgs:
        return None, "Nessuna foto valida da unire."
    if len(imgs) == 1:
        return imgs[0], None
    for mode in (cv2.Stitcher_SCANS, cv2.Stitcher_PANORAMA):
        try:
            st = cv2.Stitcher_create(mode)
            status, pano = st.stitch(imgs)
            if status == cv2.Stitcher_OK and pano is not None and pano.size:
                return _fit(pano), None
        except Exception as e:  # noqa: BLE001
            log.warning("stitch mode %s failed: %s", mode, e)
            continue
    # Non-fatal: fall back to the first photo so the user can still proceed.
    return imgs[0], ("Non sono riuscito a unire le foto (poca sovrapposizione o "
                     "inquadrature troppo diverse): uso solo la prima foto. "
                     "Riprova scattando con più sovrapposizione tra le foto.")


# --------------------------------------------------------------------------
# 2) Piece segmentation (flat mat vs background)
# --------------------------------------------------------------------------
def _segment_piece(bgr: np.ndarray) -> Optional[np.ndarray]:
    """Segment the flat piece from the background. GrabCut runs on a downscaled
    copy for speed, then the contour is scaled back to full resolution."""
    H0, W0 = bgr.shape[:2]
    seg_cap = 600
    sc = seg_cap / float(max(H0, W0))
    if sc < 1.0:
        small = cv2.resize(bgr, (max(1, int(W0 * sc)), max(1, int(H0 * sc))), interpolation=cv2.INTER_AREA)
    else:
        small = bgr
    h, w = small.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    rect = (int(w * 0.05), int(h * 0.05), int(w * 0.90), int(h * 0.90))
    try:
        bgd = np.zeros((1, 65), np.float64)
        fgd = np.zeros((1, 65), np.float64)
        cv2.grabCut(small, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
        m = np.where((mask == 2) | (mask == 0), 0, 255).astype("uint8")
    except Exception:  # noqa: BLE001
        return None
    frac = float(m.mean()) / 255.0
    if frac < 0.02 or frac > 0.98:
        return None
    k = max(3, int(min(h, w) * 0.02) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)), iterations=2)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < (h * w) * 0.02:
        return None
    peri = cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, 0.004 * peri, True).reshape(-1, 2).astype(np.float32)
    # scale contour back to full-resolution pixel coordinates
    approx[:, 0] *= (W0 / float(w))
    approx[:, 1] *= (H0 / float(h))
    return approx


def _order_quad(pts) -> np.ndarray:
    pts = np.array(pts, dtype=np.float32).reshape(-1, 2)
    s = pts.sum(axis=1)
    d = (pts[:, 0] - pts[:, 1])
    tl = pts[int(np.argmin(s))]
    br = pts[int(np.argmax(s))]
    tr = pts[int(np.argmax(d))]
    bl = pts[int(np.argmin(d))]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def _provisional_rect(w_mm: float, h_mm: float) -> List[List[float]]:
    m = min(w_mm, h_mm) * 0.12
    return [[m, m], [w_mm - m, m], [w_mm - m, h_mm - m], [m, h_mm - m]]


# --------------------------------------------------------------------------
# 3) Rectify + extract contour in mm
# --------------------------------------------------------------------------
def _clean_points(pts, n: int) -> list:
    """Validate exactly n [x,y] numeric finite points, else raise ValueError."""
    if not isinstance(pts, list) or len(pts) != n:
        raise ValueError(f"Servono {n} punti sul riferimento")
    out = []
    for p in pts:
        if (not isinstance(p, (list, tuple)) or len(p) != 2
                or not all(isinstance(v, (int, float)) and np.isfinite(v) for v in p)):
            raise ValueError("Punti del riferimento non validi: tocca di nuovo l'immagine")
        out.append([float(p[0]), float(p[1])])
    return out


def rectify_and_extract(mosaic: np.ndarray, reference: dict) -> dict:
    rtype = (reference or {}).get("type", "rect")

    if rtype == "rect":
        pts = _clean_points((reference or {}).get("points") or [], 4)
        w_mm = float(reference.get("width_mm") or 0)
        h_mm = float(reference.get("height_mm") or 0)
        if w_mm <= 0 or h_mm <= 0:
            raise ValueError("Inserisci larghezza e altezza reali del riferimento (mm)")
        src = _order_quad(pts)
        dst_mm = np.array([[0, 0], [w_mm, 0], [w_mm, h_mm], [0, h_mm]], dtype=np.float32)
        H_mm = cv2.getPerspectiveTransform(src, dst_mm)
        # where do the mosaic corners land, in mm?
        H, W = mosaic.shape[:2]
        corners = np.array([[0, 0], [W, 0], [W, H], [0, H]], dtype=np.float32).reshape(-1, 1, 2)
        mapped = cv2.perspectiveTransform(corners, H_mm).reshape(-1, 2)
        minx, miny = mapped.min(axis=0)
        maxx, maxy = mapped.max(axis=0)
        plane_w = float(maxx - minx)
        plane_h = float(maxy - miny)
        if plane_w <= 1 or plane_h <= 1:
            raise ValueError("Riferimento non valido: ricontrolla i 4 angoli")
        S = min(MAX_DIM / max(plane_w, plane_h), 3.0)  # px per mm
        mm_per_px = 1.0 / S
        T = np.array([[S, 0, -minx * S], [0, S, -miny * S], [0, 0, 1]], dtype=np.float64)
        H_total = T @ H_mm
        out_w = max(2, int(plane_w * S))
        out_h = max(2, int(plane_h * S))
        rectified = cv2.warpPerspective(mosaic, H_total, (out_w, out_h),
                                        flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    elif rtype == "line":
        pts = _clean_points((reference or {}).get("points") or [], 2)
        length_mm = float(reference.get("length_mm") or 0)
        if length_mm <= 0:
            raise ValueError("Inserisci la lunghezza reale della linea (mm)")
        (x0, y0), (x1, y1) = pts
        dist_px = float(np.hypot(x1 - x0, y1 - y0))
        if dist_px < 2:
            raise ValueError("I due punti sono troppo vicini")
        rectified = _fit(mosaic)
        # account for any resize applied by _fit vs original mosaic
        scale = rectified.shape[1] / float(mosaic.shape[1])
        mm_per_px = length_mm / (dist_px * scale)
    else:
        raise ValueError("Tipo di riferimento sconosciuto")

    h_r, w_r = rectified.shape[:2]
    contour_px = _segment_piece(rectified)
    if contour_px is not None and len(contour_px) >= 4:
        contour_mm = cv.px_to_mm(contour_px, mm_per_px)
        contour_mm = cv.simplify_contour_mm(contour_mm, tolerance_mm=1.0)
        detected = True
    else:
        contour_mm = _provisional_rect(w_r * mm_per_px, h_r * mm_per_px)
        detected = False

    ok, buf = cv2.imencode(".jpg", rectified, [cv2.IMWRITE_JPEG_QUALITY, 88])
    rect_bytes = buf.tobytes() if ok else None

    return {
        "rectified_bytes": rect_bytes,
        "w_px": w_r,
        "h_px": h_r,
        "mm_per_px": mm_per_px,
        "contour_mm": contour_mm,
        "detected": detected,
    }
