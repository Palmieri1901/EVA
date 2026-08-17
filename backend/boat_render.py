"""Compose a coloured EVA 'boat rendering' from all the mat pieces of a boat.

Each piece is placed by its saved layout position/rotation, filled with its EVA
base colour and overlaid with teak groove stripes in the chosen groove colour.
Returns a PNG (screen/share) or a PDF (client hand-out with legend + total area).
"""
from __future__ import annotations

import io
from typing import List

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon as MplPoly, Rectangle  # noqa: E402

EVA = {"marrone": "#6B4A2B", "grigio": "#8A8A8A", "nero": "#232323", "beige": "#C9B48F"}
GROOVE = {"bianco": "#FFFFFF", "nero": "#111111"}
EVA_LABEL = {"marrone": "Marrone", "grigio": "Grigio", "nero": "Nero", "beige": "Beige"}


def _transform(contour, x, y, rot):
    pts = np.array(contour, dtype=float)
    if len(pts) == 0:
        return pts
    c = pts.mean(axis=0)
    r = np.radians(rot)
    cos, sin = np.cos(r), np.sin(r)
    rel = pts - c
    rp = np.column_stack([rel[:, 0] * cos - rel[:, 1] * sin, rel[:, 0] * sin + rel[:, 1] * cos])
    return rp + c + np.array([x, y])


def _area_m2(contour) -> float:
    p = np.array(contour, dtype=float)
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    a = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    return a / 1_000_000.0  # mm^2 -> m^2


def render(pieces: List[dict], boat_name: str = "IMBARCAZIONE", fmt: str = "png") -> bytes:
    valid = [p for p in pieces if p.get("contour_mm") and len(p["contour_mm"]) >= 3]
    polys = []
    for p in valid:
        tp = _transform(p["contour_mm"], p.get("layout_x", 0) or 0,
                        p.get("layout_y", 0) or 0, p.get("layout_rot", 0) or 0)
        polys.append((p, tp))

    if polys:
        allpts = np.vstack([tp for _, tp in polys])
        minx, miny = allpts.min(axis=0)
        maxx, maxy = allpts.max(axis=0)
    else:
        minx, miny, maxx, maxy = 0, 0, 100, 100
    pad = max(50.0, 0.05 * max(maxx - minx, maxy - miny, 1))
    minx -= pad; miny -= pad; maxx += pad; maxy += pad
    W = maxx - minx
    H = maxy - miny

    fig_w = 11.0
    fig_h = max(4.0, fig_w * (H / W)) + 1.6
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=150)
    ax = fig.add_axes([0.02, 0.10, 0.96, 0.84])
    ax.set_xlim(minx, maxx)
    ax.set_ylim(maxy, miny)  # y down
    ax.set_aspect("equal")
    ax.axis("off")

    total_area = 0.0
    used_colors = set()
    stripe = 55.0  # mm between teak grooves
    for p, tp in polys:
        eva = EVA.get(p.get("eva_color", "marrone"), EVA["marrone"])
        grv = GROOVE.get(p.get("groove_color", "bianco"), GROOVE["bianco"])
        used_colors.add(p.get("eva_color", "marrone"))
        patch = MplPoly(tp, closed=True, facecolor=eva, edgecolor="black", lw=1.2, joinstyle="round")
        ax.add_patch(patch)
        # teak groove stripes, clipped to the piece, following its rotation
        rot = np.radians(p.get("layout_rot", 0) or 0)
        c = tp.mean(axis=0)
        diag = np.hypot(tp[:, 0].max() - tp[:, 0].min(), tp[:, 1].max() - tp[:, 1].min())
        d = np.array([np.cos(rot), np.sin(rot)])      # stripe direction
        n = np.array([-np.sin(rot), np.cos(rot)])     # normal (offset direction)
        # Symmetric around the piece centre: a central plank at k=0, the rest
        # mirrored outward toward the edges.
        m = int(diag / stripe) + 1
        for k in (i * stripe for i in range(-m, m + 1)):
            base = c + n * k
            a = base - d * diag
            b = base + d * diag
            ln, = ax.plot([a[0], b[0]], [a[1], b[1]], color=grv, lw=0.8, alpha=0.9)
            ln.set_clip_path(patch)
        area = _area_m2(p["contour_mm"])
        total_area += area
        cx, cy = tp.mean(axis=0)
        ax.text(cx, cy, p.get("piece_name") or p.get("name") or "", ha="center", va="center",
                fontsize=9, fontweight="bold", color="white",
                bbox=dict(boxstyle="round,pad=0.25", fc="#00000088", ec="none"))

    # header + legend
    fig.text(0.02, 0.965, boat_name.upper(), fontsize=15, fontweight="bold")
    fig.text(0.98, 0.965, f"{len(polys)} pezzi · {total_area:.2f} mq", fontsize=11,
             ha="right", fontweight="bold")
    lx = 0.02
    for col in ["marrone", "grigio", "nero", "beige"]:
        if col in used_colors:
            fig.patches.append(Rectangle((lx, 0.02), 0.03, 0.035, transform=fig.transFigure,
                                         facecolor=EVA[col], edgecolor="black", lw=0.8))
            fig.text(lx + 0.035, 0.037, EVA_LABEL[col], fontsize=9, va="center")
            lx += 0.16

    buf = io.BytesIO()
    fig.savefig(buf, format="pdf" if fmt == "pdf" else "png",
                facecolor="white", bbox_inches=None)
    plt.close(fig)
    return buf.getvalue()
