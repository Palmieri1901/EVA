"""Trace a logo / lettering from a photo into vector polylines (silhouette).

Assumes a dark subject on a light background (configurable). Uses OpenCV
thresholding + external contour tracing, simplifies the outlines and scales
them to a target real-world width in millimetres. Coordinates keep the image
orientation (Y grows downward), matching the app's editor canvas.
"""
from __future__ import annotations

import logging
from typing import List

import cv2
import numpy as np

log = logging.getLogger("vectorize")

Poly = List[List[float]]


def vectorize_image(
    image_bytes: bytes,
    threshold: int = -1,       # -1 => Otsu automatic
    invert: bool = True,       # True = dark subject on light bg
    target_width_mm: float = 200.0,
    simplify: float = 0.005,   # fraction of perimeter for approxPolyDP
    min_area_frac: float = 0.0008,
    subject: str = "logo",     # scritta | logo | oggetto
    internals: bool = False,   # keep inner contours (letter holes, inner lines)
) -> dict:
    # Tune tracing to what we are detecting.
    presets = {
        "scritta": {"min_area_frac": 0.0003, "simplify": 0.004, "largest_only": False},
        "logo":    {"min_area_frac": 0.0010, "simplify": 0.006, "largest_only": False},
        "oggetto": {"min_area_frac": 0.0040, "simplify": 0.010, "largest_only": True},
    }
    pr = presets.get((subject or "logo").lower(), presets["logo"])
    min_area_frac = pr["min_area_frac"]
    simplify = pr["simplify"]
    largest_only = pr["largest_only"] and not internals

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Immagine non valida")

    h0, w0 = img.shape[:2]
    scale_down = 1600.0 / max(h0, w0)
    if scale_down < 1.0:
        img = cv2.resize(img, (int(w0 * scale_down), int(h0 * scale_down)), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # foreground (subject) must become white (255)
    if threshold is None or threshold < 0:
        ttype = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
        _, binimg = cv2.threshold(gray, 0, 255, ttype + cv2.THRESH_OTSU)
    else:
        ttype = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
        _, binimg = cv2.threshold(gray, int(threshold), 255, ttype)

    kernel = np.ones((3, 3), np.uint8)
    binimg = cv2.morphologyEx(binimg, cv2.MORPH_CLOSE, kernel, iterations=2)
    binimg = cv2.morphologyEx(binimg, cv2.MORPH_OPEN, kernel, iterations=1)

    retr = cv2.RETR_CCOMP if internals else cv2.RETR_EXTERNAL
    contours, _ = cv2.findContours(binimg, retr, cv2.CHAIN_APPROX_SIMPLE)
    img_area = binimg.shape[0] * binimg.shape[1]
    polys_px: List[Poly] = []
    for c in contours:
        if cv2.contourArea(c) < img_area * min_area_frac:
            continue
        peri = cv2.arcLength(c, True)
        eps = max(simplify, 0.0005) * peri
        approx = cv2.approxPolyDP(c, eps, True)
        pts = [[float(p[0][0]), float(p[0][1])] for p in approx]
        if len(pts) >= 3:
            pts.append(pts[0])  # close
            polys_px.append(pts)

    if not polys_px:
        raise ValueError("Nessuna forma rilevata: regola la soglia o migliora la foto")

    if largest_only and len(polys_px) > 1:
        polys_px = [max(polys_px, key=lambda poly: cv2.contourArea(
            np.array(poly, dtype=np.float32).reshape(-1, 1, 2)))]

    # scale to target width (mm), keep aspect, origin at (0,0)
    xs = [p[0] for poly in polys_px for p in poly]
    ys = [p[1] for poly in polys_px for p in poly]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w_px = max(maxx - minx, 1.0)
    h_px = max(maxy - miny, 1.0)
    k = float(target_width_mm) / w_px

    polys_mm: List[Poly] = [
        [[(p[0] - minx) * k, (p[1] - miny) * k] for p in poly] for poly in polys_px
    ]
    width_mm = w_px * k
    height_mm = h_px * k

    # preview PNG (traced outline on white)
    prev = np.full((binimg.shape[0], binimg.shape[1], 3), 255, np.uint8)
    cv2.drawContours(prev, [np.array([[[int(x)], [int(y)]] for x, y in
                     [(p[0], p[1]) for p in poly]]).reshape(-1, 1, 2) for poly in polys_px],
                     -1, (0, 0, 0), 2)
    ok, buf = cv2.imencode(".png", prev)
    preview = buf.tobytes() if ok else None

    return {
        "polylines": polys_mm,
        "width_mm": round(width_mm, 1),
        "height_mm": round(height_mm, 1),
        "count": len(polys_mm),
        "preview": preview,
    }
