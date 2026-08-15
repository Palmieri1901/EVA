"""Render an A4 overview PDF of a boat: all mat pieces auto-arranged (nested)
on the EVA sheet, each labeled with its name and size. Single panoramic page.
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


def render_assembly(nested: dict, meta: dict) -> bytes:
    fig = plt.figure(figsize=(PW / 25.4, PH / 25.4), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, PW)
    ax.set_ylim(PH, 0)  # y grows downward like the geometry
    ax.set_aspect("equal")
    ax.axis("off")

    # decorative border
    ax.add_patch(Rectangle((5, 5), PW - 10, PH - 10, fill=False, lw=1.0, ec="black", hatch="////"))
    ax.add_patch(Rectangle((9, 9), PW - 18, PH - 18, facecolor="white", ec="black", lw=1.2))

    # header
    ax.text(PW / 2, 20, meta.get("boat_name", "IMBARCAZIONE"), ha="center", va="center",
            fontsize=13, fontweight="bold")
    ax.text(PW / 2, 28, "LAYOUT PEZZI ASSEMBLATI — FOGLIO EVA", ha="center", va="center", fontsize=8)
    ax.text(14, 34, meta.get("date", ""), ha="left", va="center", fontsize=7)
    n = nested.get("count", 0)
    ax.text(PW - 14, 34, f"{n} pezzi · {meta.get('total_area_m2', 0):.2f} mq",
            ha="right", va="center", fontsize=7, fontweight="bold")

    sheet_w = nested.get("sheet_w", 1200.0)
    sheet_h = nested.get("sheet_h", 3000.0)

    # drawing region on page
    rx0, ry0, rw, rh = 14.0, 40.0, PW - 28.0, PH - 66.0
    s = min(rw / sheet_w, rh / sheet_h)
    ox = rx0 + (rw - sheet_w * s) / 2
    oy = ry0

    def tx(pt):
        return (ox + pt[0] * s, oy + pt[1] * s)

    # sheet outline (full 1200 x 3000)
    ax.add_patch(Rectangle((ox, oy), sheet_w * s, sheet_h * s, fill=False, lw=1.2, ec="#444444"))
    ax.text(ox + sheet_w * s / 2, oy - 2, f"Foglio EVA {int(sheet_w)} × {int(sheet_h)} mm",
            ha="center", va="bottom", fontsize=6, color="#444444")

    # overflow marker
    if nested.get("overflow"):
        ax.text(ox + sheet_w * s / 2, oy + sheet_h * s + 4,
                "⚠ I pezzi superano un singolo foglio", ha="center", va="top",
                fontsize=7, color="#B00000", fontweight="bold")

    for pc in nested.get("pieces", []):
        for poly in pc.get("engrave", []):
            xs = [tx(p)[0] for p in poly]
            ys = [tx(p)[1] for p in poly]
            ax.plot(xs, ys, color="#1f5fbf", lw=0.3, solid_capstyle="round")
        for poly in pc.get("cut", []):
            xs = [tx(p)[0] for p in poly]
            ys = [tx(p)[1] for p in poly]
            ax.plot(xs, ys, color="black", lw=1.0, solid_capstyle="round")
        # label at piece center
        cx = pc["x"] + pc["w"] / 2
        cy = pc["y"] + pc["h"] / 2
        px, py = tx([cx, cy])
        ax.text(px, py, pc.get("name", ""), ha="center", va="center", fontsize=7,
                fontweight="bold", color="#B84A00",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#B84A00", lw=0.6, alpha=0.85))
        # size under the piece
        px2, py2 = tx([cx, pc["y"] + pc["h"]])
        ax.text(px2, py2 + 3, f"{int(pc['w'])}×{int(pc['h'])}", ha="center", va="top",
                fontsize=5, color="#666666")

    buf = io.BytesIO()
    fig.savefig(buf, format="pdf")
    plt.close(fig)
    return buf.getvalue()
