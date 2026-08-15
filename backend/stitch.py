"""Multi-shot stitching for large areas (up to ~2x3 m).

Each shot detects markers. The first shot anchors the global mm frame using its
4 corner markers + the known inter-axis rectangle. Subsequent shots are anchored
by matching their markers to already-globalized markers (shared markers between
overlapping shots), via a RANSAC similarity hypothesis upgraded to a homography.
All shots' tape masks are then warped into one global raster and merged, and the
full contour is vectorized in millimeters.
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

import cv2
import numpy as np

import cv_pipeline as cv

logger = logging.getLogger("stitch")

MATCH_TOL_MM = 18.0     # marker match tolerance in the global plane
MAX_GLOBAL_PX = 3000    # cap merged raster dimension


def _apply_h(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Apply 3x3 homography to Nx2 points -> Nx2."""
    n = pts.shape[0]
    hom = np.hstack([pts, np.ones((n, 1))])
    out = (H @ hom.T).T
    out = out[:, :2] / out[:, 2:3]
    return out


def _similarity_from_two(p0, p1, q0, q1) -> np.ndarray:
    """3x3 similarity mapping image pair (p) -> global pair (q)."""
    dp = complex(p1[0] - p0[0], p1[1] - p0[1])
    dq = complex(q1[0] - q0[0], q1[1] - q0[1])
    if abs(dp) < 1e-6:
        return np.eye(3)
    z = dq / dp
    a, b = z.real, z.imag
    tx = q0[0] - (a * p0[0] - b * p0[1])
    ty = q0[1] - (b * p0[0] + a * p0[1])
    return np.array([[a, -b, tx], [b, a, ty], [0, 0, 1]], dtype=np.float64)


def _match_shot(img_pts: np.ndarray, global_pts: np.ndarray):
    """Find correspondences (img->global) via RANSAC similarity hypotheses.

    Returns (best_pairs, best_H) or (None, None). best_pairs: list of (i_img, j_global).
    """
    ni, ng = len(img_pts), len(global_pts)
    if ni < 2 or ng < 2:
        return None, None
    best_pairs: List = []
    for a in range(ni):
        for b in range(ni):
            if a == b:
                continue
            for i in range(ng):
                for j in range(ng):
                    if i == j:
                        continue
                    H = _similarity_from_two(img_pts[a], img_pts[b], global_pts[i], global_pts[j])
                    tp = _apply_h(H, img_pts)
                    pairs = []
                    used = set()
                    for k in range(ni):
                        d = np.linalg.norm(global_pts - tp[k], axis=1)
                        jm = int(np.argmin(d))
                        if d[jm] < MATCH_TOL_MM and jm not in used:
                            pairs.append((k, jm))
                            used.add(jm)
                    if len(pairs) > len(best_pairs):
                        best_pairs = pairs
    if len(best_pairs) < 2:
        return None, None

    src = np.array([img_pts[k] for k, _ in best_pairs], dtype=np.float64)
    dst = np.array([global_pts[j] for _, j in best_pairs], dtype=np.float64)
    if len(best_pairs) >= 4:
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        if H is None:
            H = _refine_similarity(src, dst)
    else:
        H = _refine_similarity(src, dst)
    return best_pairs, H


def _refine_similarity(src, dst) -> np.ndarray:
    M, _ = cv2.estimateAffinePartial2D(src.astype(np.float32), dst.astype(np.float32), method=cv2.LMEDS)
    if M is None:
        return _similarity_from_two(src[0], src[1], dst[0], dst[1])
    return np.vstack([M, [0, 0, 1]])


def stitch(project: dict, shots: List[dict]) -> dict:
    """shots: [{id, order, bgr(np.ndarray)}]. Returns merged result dict."""
    bg = project["background_mode"]
    ref_w, ref_h = project["ref_width_mm"], project["ref_height_mm"]

    # --- Anchor first shot ---
    shots = sorted(shots, key=lambda s: s.get("order", 0))
    first = shots[0]
    m0 = cv.detect_markers(first["bgr"], bg)
    corners, _ = cv.order_markers(m0)
    if len(corners) < 4:
        return {"error": "Il primo scatto deve contenere i 4 bollini d'angolo del riquadro di riferimento."}

    src = np.array([[c["x"], c["y"]] for c in corners], dtype=np.float32)
    dst_mm = np.array([[0, 0], [ref_w, 0], [ref_w, ref_h], [0, ref_h]], dtype=np.float32)
    H0 = cv2.getPerspectiveTransform(src, dst_mm).astype(np.float64)

    all_img0 = np.array([[m["x"], m["y"]] for m in m0], dtype=np.float64)
    first["H"] = H0
    first["anchored"] = True
    global_pts = list(_apply_h(H0, all_img0))  # list of np arrays (mm)

    for s in shots[1:]:
        s["anchored"] = False
        s["_markers"] = cv.detect_markers(s["bgr"], bg)

    # --- Iteratively anchor remaining shots ---
    progress = True
    while progress:
        progress = False
        for s in shots[1:]:
            if s["anchored"]:
                continue
            markers = s["_markers"]
            if len(markers) < 2:
                continue
            img_pts = np.array([[m["x"], m["y"]] for m in markers], dtype=np.float64)
            gp = np.array(global_pts, dtype=np.float64)
            pairs, H = _match_shot(img_pts, gp)
            if pairs is None or H is None:
                continue
            s["H"] = H
            s["anchored"] = True
            # add newly seen markers to the global set
            tp = _apply_h(H, img_pts)
            matched_idx = {k for k, _ in pairs}
            for k in range(len(img_pts)):
                if k in matched_idx:
                    continue
                d = np.linalg.norm(gp - tp[k], axis=1) if len(gp) else np.array([1e9])
                if len(gp) == 0 or d.min() > MATCH_TOL_MM:
                    global_pts.append(tp[k])
            progress = True

    anchored = [s for s in shots if s.get("anchored")]
    unanchored = [s for s in shots if not s.get("anchored")]

    # --- Global raster extent from all global markers, translated to origin ---
    gp = np.array(global_pts, dtype=np.float64)
    margin = max(ref_w, ref_h) * 0.06 + 20
    min_xy = gp.min(axis=0) - margin
    max_xy = gp.max(axis=0) + margin
    plane_w = float(max_xy[0] - min_xy[0])
    plane_h = float(max_xy[1] - min_xy[1])

    mm_per_px = max(max(plane_w, plane_h) / MAX_GLOBAL_PX, cv.MIN_MM_PER_PX)
    out_w = max(2, int(round(plane_w / mm_per_px)))
    out_h = max(2, int(round(plane_h / mm_per_px)))

    # translation+scale: global_mm -> raster px, with origin at min_xy
    K = np.array([
        [1.0 / mm_per_px, 0, -min_xy[0] / mm_per_px],
        [0, 1.0 / mm_per_px, -min_xy[1] / mm_per_px],
        [0, 0, 1],
    ], dtype=np.float64)

    merged_mask = np.zeros((out_h, out_w), np.uint8)
    preview = np.full((out_h, out_w, 3), 255, np.uint8)

    for s in anchored:
        M = K @ s["H"]  # image px -> raster px
        mask = cv.tape_mask(s["bgr"], bg)
        wmask = cv2.warpPerspective(mask, M, (out_w, out_h))
        merged_mask = cv2.bitwise_or(merged_mask, wmask)
        wcolor = cv2.warpPerspective(s["bgr"], M, (out_w, out_h), borderValue=(255, 255, 255))
        content = wcolor.sum(axis=2) < (255 * 3)
        preview[content] = wcolor[content]

    merged_mask = cv2.morphologyEx(merged_mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
    merged_mask = cv2.morphologyEx(merged_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    contour_px = cv.extract_contour(merged_mask, project["cut_side"])
    if contour_px is not None and len(contour_px) >= 4:
        contour_mm = cv.px_to_mm(contour_px, mm_per_px)
        contour_mm = cv.simplify_contour_mm(contour_mm, tolerance_mm=max(0.6, mm_per_px))
        tape_ok = True
    else:
        m = min(plane_w, plane_h) * 0.1
        contour_mm = [[m, m], [plane_w - m, m], [plane_w - m, plane_h - m], [m, plane_h - m]]
        tape_ok = False

    ok, buf = cv2.imencode(".jpg", preview, [cv2.IMWRITE_JPEG_QUALITY, 85])
    preview_bytes = buf.tobytes() if ok else None

    return {
        "contour_mm": contour_mm,
        "mm_per_px": mm_per_px,
        "w_px": out_w,
        "h_px": out_h,
        "plane_w_mm": plane_w,
        "plane_h_mm": plane_h,
        "preview_bytes": preview_bytes,
        "anchored_ids": [s["id"] for s in anchored],
        "unanchored_ids": [s["id"] for s in unanchored],
        "tape_detected": tape_ok,
        "n_global_markers": len(global_pts),
    }
