"""Trace a logo / lettering / object outline from a photo into vector polylines.

Robust pipeline for real-world photos (uneven light, low contrast):
  - CLAHE contrast boost + bilateral edge-preserving denoise
  - subject-aware segmentation:
      * scritta / logo  -> Otsu (or manual) threshold on a high-contrast subject
      * oggetto         -> auto-Canny edges closed into regions (silhouette of a part)
  - automatic background orientation (borders must be background)
  - morphological cleanup scaled to image size
  - contour smoothing (Chaikin) so outlines are clean, not jagged
Coordinates keep image orientation (Y down), matching the editor canvas.
"""
from __future__ import annotations

import logging
from typing import List

import cv2
import numpy as np

log = logging.getLogger("vectorize")

Poly = List[List[float]]


def _odd(n: int) -> int:
    n = int(n)
    return n if n % 2 == 1 else n + 1


def _chaikin(pts: List[List[float]], iterations: int = 2) -> List[List[float]]:
    """Corner-cutting smoothing for a closed polygon."""
    if len(pts) < 4:
        return pts
    p = pts[:-1] if pts[0] == pts[-1] else pts[:]
    for _ in range(iterations):
        out = []
        n = len(p)
        for i in range(n):
            a = p[i]
            b = p[(i + 1) % n]
            out.append([a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25])
            out.append([a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75])
        p = out
    p.append(p[0])
    return p


def _crop_letterbox(img: np.ndarray) -> np.ndarray:
    """Remove near-uniform (black/white) bars at the image extremes, e.g. from
    phone screenshots, so segmentation focuses on the actual photo region."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = g.shape[:2]
    row_mean = g.mean(axis=1)
    row_std = g.std(axis=1)
    col_mean = g.mean(axis=0)
    col_std = g.std(axis=0)

    def uniform(m, s):
        return s < 18 and (m < 45 or m > 225)

    top = 0
    while top < h - 1 and uniform(row_mean[top], row_std[top]):
        top += 1
    bot = h - 1
    while bot > top and uniform(row_mean[bot], row_std[bot]):
        bot -= 1
    left = 0
    while left < w - 1 and uniform(col_mean[left], col_std[left]):
        left += 1
    right = w - 1
    while right > left and uniform(col_mean[right], col_std[right]):
        right -= 1
    if bot - top < h * 0.3 or right - left < w * 0.3:
        return img  # crop too aggressive, keep original
    return img[top:bot + 1, left:right + 1]


def _circle_poly(cx: float, cy: float, r: float, n: int = 96) -> Poly:
    poly = [[float(cx + r * np.cos(t)), float(cy + r * np.sin(t))]
            for t in np.linspace(0, 2 * np.pi, n, endpoint=False)]
    poly.append(poly[0])
    return poly


def _hough(gray: np.ndarray, w: int, h: int, p2: int = 45):
    g = cv2.medianBlur(gray, 5)
    return cv2.HoughCircles(
        g, cv2.HOUGH_GRADIENT, dp=1.2, minDist=int(min(w, h) * 0.5),
        param1=110, param2=p2, minRadius=int(min(w, h) * 0.12), maxRadius=int(min(w, h) * 0.60),
    )


def _dominant_circle(gray: np.ndarray, w: int, h: int):
    """Return (cx,cy,r) only if a clearly dominant, roughly-centred circle exists.
    Used to auto-clean round logos even in LOGO/OGGETTO modes."""
    circles = _hough(gray, w, h, p2=55)
    if circles is None:
        return None
    circles = np.round(circles[0, :]).astype(int)
    cx, cy, r = max(circles, key=lambda c: c[2])
    if r < 0.28 * min(w, h):
        return None
    if abs(cx - w / 2) > w * 0.3 or abs(cy - h / 2) > h * 0.35:
        return None
    return (cx, cy, r)


def _detect_circles(gray: np.ndarray, w: int, h: int) -> List[Poly]:
    """Detect circular logos/emblems and return perfect circle polylines (px)."""
    circles = _hough(gray, w, h, p2=45)
    if circles is None:
        # fallback: fit a circle to the largest foreground blob (filled discs)
        _, b = cv2.threshold(cv2.medianBlur(gray, 5), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        border = np.concatenate([b[0, :], b[-1, :], b[:, 0], b[:, -1]])
        if border.mean() > 140:
            b = cv2.bitwise_not(b)
        cnts, _ = cv2.findContours(b, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnts = [c for c in cnts if cv2.contourArea(c) > (w * h) * 0.01]
        if not cnts:
            return []
        (cx, cy), r = cv2.minEnclosingCircle(max(cnts, key=cv2.contourArea))
    else:
        circles = np.round(circles[0, :]).astype(int)
        cx, cy, r = max(circles, key=lambda c: c[2])
    return [_circle_poly(cx, cy, r)]


def _grabcut_mask(img: np.ndarray) -> np.ndarray:
    """Foreground silhouette via GrabCut, seeded with an inset rectangle.
    Best after the user has cropped tightly to the subject."""
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    rect = (int(w * 0.06), int(h * 0.06), int(w * 0.88), int(h * 0.88))
    try:
        cv2.grabCut(img, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except Exception:  # noqa: BLE001
        return None
    return np.where((mask == 2) | (mask == 0), 0, 255).astype("uint8")


def _binarize(img: np.ndarray, gray: np.ndarray, threshold: int, invert: bool,
              subject: str, internals: bool) -> np.ndarray:
    # Detailed/silhouette logos on cluttered backgrounds: GrabCut removes the
    # background far better than a global threshold. Text and manual-threshold
    # or internal-detail requests use intensity thresholding instead.
    use_grabcut = subject in ("logo", "oggetto") and not internals and (threshold is None or threshold < 0)
    if use_grabcut:
        m = _grabcut_mask(img)
        if m is not None and 0.02 < (m.mean() / 255.0) < 0.95:
            return m
    ttype = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    if threshold is None or threshold < 0:
        _, binimg = cv2.threshold(gray, 0, 255, ttype + cv2.THRESH_OTSU)
    else:
        _, binimg = cv2.threshold(gray, int(threshold), 255, ttype)
    return binimg


def vectorize_image(
    image_bytes: bytes,
    threshold: int = -1,
    invert: bool = True,
    target_width_mm: float = 200.0,
    simplify: float = 0.005,
    min_area_frac: float = 0.0008,
    subject: str = "logo",
    internals: bool = False,
    smooth: bool = True,
    roi: dict = None,          # {x,y,w,h} as fractions 0-1 of the image
) -> dict:
    presets = {
        "scritta": {"min_area_frac": 0.0004, "simplify": 0.0025, "largest_only": False, "smooth_it": 1, "close_mul": 0.006, "close_it": 1},
        "logo":    {"min_area_frac": 0.0008, "simplify": 0.0030, "largest_only": False, "smooth_it": 2, "close_mul": 0.008, "close_it": 2},
        "oggetto": {"min_area_frac": 0.0060, "simplify": 0.0035, "largest_only": False, "smooth_it": 2, "close_mul": 0.020, "close_it": 3},
    }
    pr = presets.get((subject or "logo").lower(), presets["logo"])
    subj = (subject or "logo").lower()
    min_area_frac = pr["min_area_frac"]
    simplify = pr["simplify"]
    largest_only = pr["largest_only"] and not internals
    smooth_it = pr["smooth_it"] if smooth else 0

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Immagine non valida")

    if roi:
        H, W = img.shape[:2]
        rx = max(0.0, min(1.0, float(roi.get("x", 0))))
        ry = max(0.0, min(1.0, float(roi.get("y", 0))))
        rw = max(0.02, min(1.0 - rx, float(roi.get("w", 1))))
        rh = max(0.02, min(1.0 - ry, float(roi.get("h", 1))))
        x0, y0 = int(rx * W), int(ry * H)
        x1, y1 = int((rx + rw) * W), int((ry + rh) * H)
        crop = img[y0:y1, x0:x1]
        if crop.size and crop.shape[0] > 10 and crop.shape[1] > 10:
            img = crop  # manual ROI overrides auto letterbox crop
    else:
        img = _crop_letterbox(img)
    h0, w0 = img.shape[:2]
    scale_down = 1400.0 / max(h0, w0)
    if scale_down < 1.0:
        img = cv2.resize(img, (int(w0 * scale_down), int(h0 * scale_down)), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 75, 75)
    gray = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(gray)

    if subj == "cerchio":
        polys_px = _detect_circles(gray, w, h)
        if not polys_px:
            raise ValueError("Nessun cerchio rilevato: ritaglia meglio attorno al logo")
    elif (subj in ("logo", "oggetto") and not internals and (threshold is None or threshold < 0)
          and (_auto_c := _dominant_circle(gray, w, h)) is not None):
        # round logo/emblem detected -> clean circular outline (avoids messy blobs)
        polys_px = [_circle_poly(*_auto_c)]
    else:
        binimg = _binarize(img, gray, threshold, invert, subj, internals)

        # ensure background (image borders) is black; else flip
        border = np.concatenate([binimg[0, :], binimg[-1, :], binimg[:, 0], binimg[:, -1]])
        if border.mean() > 140:
            binimg = cv2.bitwise_not(binimg)

        # cleanup — close scaled to subject (fills plank grooves for 'oggetto')
        k = _odd(max(3, int(min(h, w) * pr["close_mul"])))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        binimg = cv2.morphologyEx(binimg, cv2.MORPH_CLOSE, kernel, iterations=pr["close_it"])
        ok = _odd(max(3, int(min(h, w) * 0.005)))
        binimg = cv2.morphologyEx(binimg, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ok, ok)), iterations=1)

        retr = cv2.RETR_CCOMP if internals else cv2.RETR_EXTERNAL
        contours, _ = cv2.findContours(binimg, retr, cv2.CHAIN_APPROX_SIMPLE)
        img_area = h * w
        polys_px = []
        fallback: List[Poly] = []  # kept if the frame-hugging filter removes everything
        for c in contours:
            area = cv2.contourArea(c)
            if area < img_area * min_area_frac:
                continue
            peri = cv2.arcLength(c, True)
            eps = max(simplify, 0.0008) * peri
            approx = cv2.approxPolyDP(c, eps, True)
            pts = [[float(p[0][0]), float(p[0][1])] for p in approx]
            if len(pts) < 3:
                continue
            pts.append(pts[0])
            if smooth_it:
                pts = _chaikin(pts, smooth_it)
            fallback.append(pts)

            # background heuristics: whole-frame rectangle or blob touching 3+ borders
            x, y, cw, ch = cv2.boundingRect(c)
            full_frame = cw > w * 0.985 and ch > h * 0.985
            touch = (x <= 2) + (y <= 2) + (x + cw >= w - 2) + (y + ch >= h - 2)
            if full_frame or (touch >= 3 and area > img_area * 0.35):
                continue
            polys_px.append(pts)

        # never drop everything: on a very tight crop the subject fills the frame
        if not polys_px:
            polys_px = fallback
        if not polys_px:
            raise ValueError("Nessuna forma rilevata: regola la soglia o migliora la foto")

        if largest_only and len(polys_px) > 1:
            polys_px = [max(polys_px, key=lambda poly: cv2.contourArea(
                np.array(poly, dtype=np.float32).reshape(-1, 1, 2)))]

    xs = [p[0] for poly in polys_px for p in poly]
    ys = [p[1] for poly in polys_px for p in poly]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w_px = max(maxx - minx, 1.0)
    h_px = max(maxy - miny, 1.0)
    k_scale = float(target_width_mm) / w_px

    polys_mm: List[Poly] = [
        [[(p[0] - minx) * k_scale, (p[1] - miny) * k_scale] for p in poly] for poly in polys_px
    ]
    width_mm = w_px * k_scale
    height_mm = h_px * k_scale

    # preview PNG (traced outline on the original, dimmed)
    prev = cv2.addWeighted(img, 0.45, np.full_like(img, 255), 0.55, 0)
    for poly in polys_px:
        cnt = np.array(poly, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(prev, [cnt], True, (0, 90, 200), max(2, int(min(h, w) * 0.004)))
    ok, buf = cv2.imencode(".png", prev)
    preview = buf.tobytes() if ok else None

    return {
        "polylines": polys_mm,
        "width_mm": round(width_mm, 1),
        "height_mm": round(height_mm, 1),
        "count": len(polys_mm),
        "preview": preview,
    }
