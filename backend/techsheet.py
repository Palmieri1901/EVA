"""Render a printable technical sheet (scheda tecnica) as PDF, matching a
classic marine EVA/teak production sheet: decorative border, title block,
the dima drawing (cut + engrave) and an acceptance-signature box.
"""
from __future__ import annotations

import io
from typing import List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

# A4 portrait in mm
PW, PH = 210.0, 297.0


def _bbox(polys: List[List[List[float]]]):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def render_sheet(cut, engrave, meta: dict) -> bytes:
    fig = plt.figure(figsize=(PW / 25.4, PH / 25.4), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, PW)
    ax.set_ylim(PH, 0)  # invert Y (page coords, y grows downward like the geometry)
    ax.set_aspect("equal")
    ax.axis("off")

    # decorative hatched border ring
    ax.add_patch(Rectangle((5, 5), PW - 10, PH - 10, fill=False, lw=1.0, ec="black",
                           hatch="////"))
    ax.add_patch(Rectangle((11, 11), PW - 22, PH - 22, facecolor="white", ec="black", lw=1.2))

    # --- Title block (top-right) ---
    tbx, tbw = 120.0, 78.0
    tby, tbh = 14.0, 46.0
    rows = tby
    ax.add_patch(Rectangle((tbx, tby), tbw, tbh, fill=False, lw=1.0, ec="black"))
    line_h = tbh / 6.0
    for i in range(1, 6):
        ax.plot([tbx, tbx + tbw], [tby + i * line_h, tby + i * line_h], color="black", lw=0.6)

    def row_text(i, label, value=None, bold=False):
        y = tby + (i + 0.5) * line_h
        if value is None:
            ax.text(tbx + tbw / 2, y, label, ha="center", va="center", fontsize=8,
                    fontweight="bold" if bold else "normal")
        else:
            ax.text(tbx + 2, y, label, ha="left", va="center", fontsize=7)
            ax.text(tbx + tbw - 2, y, value, ha="right", va="center", fontsize=8, fontweight="bold")

    row_text(0, meta.get("company", "FOAM TEAK"), bold=True)
    row_text(1, meta.get("date", ""), bold=False)
    row_text(2, meta.get("client", ""))
    row_text(3, meta.get("model", ""))
    row_text(4, meta.get("tipo", ""))
    # last row split: colore + metratura handled below with two mini rows
    ax.text(tbx + 2, tby + 5.5 * line_h, "Colore:", ha="left", va="center", fontsize=7)
    ax.text(tbx + tbw - 2, tby + 5.5 * line_h, meta.get("color", ""), ha="right", va="center", fontsize=8)

    # metratura strip just below title block
    ax.add_patch(Rectangle((tbx, tby + tbh), tbw, 8, fill=False, lw=1.0, ec="black"))
    ax.text(tbx + 2, tby + tbh + 4, "Metratura:", ha="left", va="center", fontsize=7)
    ax.text(tbx + tbw - 2, tby + tbh + 4, f"{meta.get('area_m2', 0):.2f} mq",
            ha="right", va="center", fontsize=8, fontweight="bold")

    # --- Logo box (top-left) ---
    ax.add_patch(Rectangle((14, 14), 62, 42, fill=False, lw=1.0, ec="black"))
    ax.text(45, 50, "FOAM TEAK", ha="center", va="center", fontsize=9, fontweight="bold")

    # --- Drawing region ---
    all_polys = (cut or []) + (engrave or [])
    if all_polys:
        gminx, gminy, gmaxx, gmaxy = _bbox(all_polys)
        gw = max(gmaxx - gminx, 1.0)
        gh = max(gmaxy - gminy, 1.0)
        rx0, ry0, rw, rh = 16.0, 76.0, PW - 32.0, 178.0
        s = min(rw / gw, rh / gh)
        ox = rx0 + (rw - gw * s) / 2 - gminx * s
        oy = ry0 + (rh - gh * s) / 2 - gminy * s

        def tx(pt):
            return (pt[0] * s + ox, pt[1] * s + oy)

        for poly in engrave or []:
            xs = [tx(p)[0] for p in poly]
            ys = [tx(p)[1] for p in poly]
            ax.plot(xs, ys, color="black", lw=0.35, solid_capstyle="round")
        for poly in cut or []:
            xs = [tx(p)[0] for p in poly]
            ys = [tx(p)[1] for p in poly]
            ax.plot(xs, ys, color="black", lw=1.1, solid_capstyle="round")

    # --- Signature box (bottom-right) ---
    sx, sy, sw2, sh2 = 120.0, 264.0, 78.0, 20.0
    ax.add_patch(Rectangle((sx, sy), sw2, sh2, fill=False, lw=1.0, ec="black"))
    ax.text(sx + 2, sy + 4, "Firma per accettazione:", ha="left", va="center", fontsize=7)
    ax.plot([sx + 6, sx + sw2 - 6], [sy + sh2 - 5, sy + sh2 - 5], color="black", lw=0.6)

    buf = io.BytesIO()
    fig.savefig(buf, format="pdf")
    plt.close(fig)
    return buf.getvalue()
