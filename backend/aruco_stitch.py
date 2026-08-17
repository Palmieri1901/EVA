"""ArUco-based multi-photo reconstruction for FLAT pieces.

The user prints a sheet of ArUco markers (known side length in mm) and places a
few of them on the flat surface, around the piece. Several overlapping photos are
taken from any angle; each photo must share at least one marker with another.

Pipeline (no OpenCV Stitcher -> crash-safe):
  1. Detect ArUco markers in every photo.
  2. Build a single metric world frame: anchor the most-seen marker to a square of
     known size, then propagate world coordinates to every other marker via the
     homographies of photos where markers co-appear (BFS).
  3. Warp every photo into one ortho-mosaic in real millimetres (blended).
  4. Segment the piece outline on the mosaic -> contour in mm.

This handles large / complex pieces that do not fit in a single frame.
"""
from __future__ import annotations

import io
import logging
from collections import Counter
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

import cv_pipeline as cv
import photogram

log = logging.getLogger("aruco")

MAX_DIM = 2400
_DICT = cv2.aruco.DICT_4X4_50
Detection = Dict[int, np.ndarray]  # marker id -> (4,2) pixel corners


def _detector() -> "cv2.aruco.ArucoDetector":
    params = cv2.aruco.DetectorParameters()
    return cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(_DICT), params)


def detect_all(images: List[np.ndarray]) -> List[Detection]:
    det = _detector()
    out: List[Detection] = []
    for img in images:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = det.detectMarkers(gray)
        d: Detection = {}
        if ids is not None:
            for c, i in zip(corners, ids.ravel()):
                d[int(i)] = c.reshape(4, 2).astype(np.float64)
        out.append(d)
    return out


def build_world(dets: List[Detection], marker_mm: float) -> Dict[int, np.ndarray]:
    """Return {marker_id: (4,2) world-mm corners}. Empty if nothing anchorable."""
    counts = Counter()
    for d in dets:
        counts.update(d.keys())
    if not counts:
        return {}
    anchor = counts.most_common(1)[0][0]
    S = marker_mm
    world: Dict[int, np.ndarray] = {
        anchor: np.array([[0, 0], [S, 0], [S, S], [0, S]], dtype=np.float64)
    }
    for _ in range(len(dets) + 2):
        changed = False
        for d in dets:
            known = [mid for mid in d if mid in world]
            if not known:
                continue
            src = np.vstack([d[m] for m in known])
            dst = np.vstack([world[m] for m in known])
            H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
            if H is None:
                continue
            for mid in d:
                if mid not in world:
                    w = cv2.perspectiveTransform(d[mid].reshape(-1, 1, 2), H).reshape(-1, 2)
                    world[mid] = w
                    changed = True
        if not changed:
            break
    return world


def _photo_homography(d: Detection, world: Dict[int, np.ndarray]) -> Optional[np.ndarray]:
    known = [m for m in d if m in world]
    if not known:
        return None
    src = np.vstack([d[m] for m in known])
    dst = np.vstack([world[m] for m in known])
    H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    return H


def build_mosaic(images: List[np.ndarray], dets: List[Detection],
                 world: Dict[int, np.ndarray], marker_mm: float
                 ) -> Tuple[np.ndarray, float]:
    allw = np.vstack(list(world.values()))
    minx, miny = allw.min(axis=0)
    maxx, maxy = allw.max(axis=0)
    margin = marker_mm * 4.0  # include the surface around the markers (the piece)
    minx -= margin; miny -= margin; maxx += margin; maxy += margin
    plane_w = float(maxx - minx)
    plane_h = float(maxy - miny)
    S = min(MAX_DIM / max(plane_w, plane_h), 3.0)  # px per mm
    mm_per_px = 1.0 / S
    out_w = max(2, int(plane_w * S))
    out_h = max(2, int(plane_h * S))
    T = np.array([[S, 0, -minx * S], [0, S, -miny * S], [0, 0, 1]], dtype=np.float64)

    acc = np.zeros((out_h, out_w, 3), np.float32)
    cnt = np.zeros((out_h, out_w), np.float32)
    used = 0
    for img, d in zip(images, dets):
        H = _photo_homography(d, world)
        if H is None:
            continue
        H_total = T @ H
        warped = cv2.warpPerspective(img, H_total, (out_w, out_h), flags=cv2.INTER_LINEAR)
        mask = cv2.warpPerspective(np.full(img.shape[:2], 255, np.uint8), H_total,
                                   (out_w, out_h), flags=cv2.INTER_NEAREST)
        m = mask > 0
        acc[m] += warped[m].astype(np.float32)
        cnt[m] += 1.0
        used += 1
    if used == 0:
        raise ValueError("Nessuna foto utilizzabile: marker non riconosciuti.")
    cnt_safe = np.maximum(cnt, 1.0)[:, :, None]
    mosaic = (acc / cnt_safe).astype(np.uint8)
    mosaic[cnt == 0] = 255  # fill gaps with white
    return mosaic, mm_per_px


def process(images: List[np.ndarray], marker_mm: float) -> dict:
    if marker_mm <= 0:
        raise ValueError("Indica il lato reale del marker (mm)")
    imgs = [photogram._fit(im, MAX_DIM) for im in images if im is not None]
    if not imgs:
        raise ValueError("Nessuna foto valida.")
    dets = detect_all(imgs)
    total_markers = len({m for d in dets for m in d})
    if total_markers == 0:
        raise ValueError(
            "Nessun marker ArUco rilevato. Stampa il foglio marker, appoggia alcuni "
            "marker sul piano attorno al pezzo e assicurati che siano ben visibili e a fuoco."
        )
    world = build_world(dets, marker_mm)
    if len(world) == 0:
        raise ValueError("Marker rilevati ma non collegabili tra le foto.")
    mosaic, mm_per_px = build_mosaic(imgs, dets, world, marker_mm)

    h, w = mosaic.shape[:2]
    contour_px = photogram._segment_piece(mosaic)
    if contour_px is not None and len(contour_px) >= 4:
        contour_mm = cv.px_to_mm(contour_px, mm_per_px)
        contour_mm = cv.simplify_contour_mm(contour_mm, tolerance_mm=1.0)
        detected = True
    else:
        contour_mm = photogram._provisional_rect(w * mm_per_px, h * mm_per_px)
        detected = False

    ok, buf = cv2.imencode(".jpg", mosaic, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return {
        "rectified_bytes": buf.tobytes() if ok else None,
        "w_px": w, "h_px": h, "mm_per_px": mm_per_px,
        "contour_mm": contour_mm, "detected": detected,
        "photos_used": len([d for d in dets if _photo_homography(d, world) is not None]),
        "markers_found": total_markers,
    }


# --------------------------------------------------------------------------
# Printable marker sheet (matplotlib -> PDF)
# --------------------------------------------------------------------------
def make_sheet_pdf(marker_mm: float = 40.0, count: int = 8) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    dic = cv2.aruco.getPredefinedDictionary(_DICT)
    A4_W, A4_H = 8.27, 11.69  # inches
    mm_in = marker_mm / 25.4
    gap_in = 15 / 25.4
    cols = 2
    rows = int(np.ceil(count / cols))

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        fig = plt.figure(figsize=(A4_W, A4_H))
        fig.text(0.5, 0.97, "FOGLIO MARKER ArUco (DICT_4X4_50)", ha="center",
                 fontsize=13, weight="bold")
        fig.text(0.5, 0.94,
                 f"Stampa a grandezza reale (100%, senza adattamento). Lato marker = {marker_mm:.0f} mm.",
                 ha="center", fontsize=9)
        fig.text(0.5, 0.925,
                 "Ritaglia e appoggia alcuni marker sul piano, attorno al pezzo.",
                 ha="center", fontsize=9)

        block_w = mm_in + gap_in
        block_h = mm_in + gap_in + 0.25
        grid_w = cols * block_w
        grid_h = rows * block_h
        x0 = (A4_W - grid_w) / 2.0
        y_top = A4_H * 0.90
        for k in range(count):
            r = k // cols
            c = k % cols
            left = (x0 + c * block_w) / A4_W
            bottom = (y_top - r * block_h - mm_in) / A4_H
            ax = fig.add_axes([left, bottom, mm_in / A4_W, mm_in / A4_H])
            img = cv2.aruco.generateImageMarker(dic, k, 300)
            ax.imshow(img, cmap="gray", interpolation="nearest", extent=[0, 1, 0, 1])
            ax.set_xticks([]); ax.set_yticks([])
            for s in ax.spines.values():
                s.set_visible(False)
            fig.text(left + (mm_in / A4_W) / 2, bottom - 0.012, f"ID {k}",
                     ha="center", fontsize=8)
        # a reference ruler so the user can verify the print scale
        fig.text(0.5, 0.05, f"Verifica scala: il lato di ogni marker deve misurare {marker_mm:.0f} mm.",
                 ha="center", fontsize=8)
        pdf.savefig(fig)
        plt.close(fig)
    return buf.getvalue()
