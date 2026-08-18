"""Render an overview PDF of a boat: all mat pieces auto-arranged (nested) on
EVA sheets, each labeled with its name and size. One page per EVA sheet when the
pieces span multiple sheets.
"""
from __future__ import annotations

import io
from typing import List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

# A4 portrait in mm
PW, PH = 210.0, 297.0


def _draw_sheet(pdf: PdfPages, sheet: dict, meta: dict, page_idx: int, page_total: int) -> None:
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
    ax.text(PW / 2, 28, f"LAYOUT PEZZI ASSEMBLATI — FOGLIO {page_idx + 1}/{page_total}",
            ha="center", va="center", fontsize=8)
    ax.text(14, 34, meta.get("date", ""), ha="left", va="center", fontsize=7)

    n = len(sheet.get("pieces", []))
    util = sheet.get("utilization", 0.0) * 100.0
    uh = sheet.get("used_h", 0.0)
    ax.text(PW - 14, 34, f"{n} pezzi · resa {util:.0f}% · lungh. usata {int(uh)} mm",
            ha="right", va="center", fontsize=7, fontweight="bold")

    sheet_w = sheet.get("sheet_w", 900.0)
    sheet_h = sheet.get("sheet_h", 2400.0)

    rx0, ry0, rw, rh = 14.0, 40.0, PW - 28.0, PH - 66.0
    s = min(rw / sheet_w, rh / sheet_h)
    ox = rx0 + (rw - sheet_w * s) / 2
    oy = ry0

    def tx(pt):
        return (ox + pt[0] * s, oy + pt[1] * s)

    ax.add_patch(Rectangle((ox, oy), sheet_w * s, sheet_h * s, fill=False, lw=1.2, ec="#444444"))
    ax.text(ox + sheet_w * s / 2, oy - 2, f"Foglio EVA {int(sheet_w)} × {int(sheet_h)} mm",
            ha="center", va="bottom", fontsize=6, color="#444444")

    for pc in sheet.get("pieces", []):
        for poly in pc.get("engrave", []):
            xs = [tx(p)[0] for p in poly]
            ys = [tx(p)[1] for p in poly]
            ax.plot(xs, ys, color="#1f5fbf", lw=0.3, solid_capstyle="round")
        for poly in pc.get("cut", []):
            xs = [tx(p)[0] for p in poly]
            ys = [tx(p)[1] for p in poly]
            ax.plot(xs, ys, color="black", lw=1.0, solid_capstyle="round")
        cx = pc["x"] + pc["w"] / 2
        cy = pc["y"] + pc["h"] / 2
        px, py = tx([cx, cy])
        label = pc.get("name", "")
        if pc.get("rotated"):
            label += " ⟳"
        ax.text(px, py, label, ha="center", va="center", fontsize=7,
                fontweight="bold", color="#B84A00",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#B84A00", lw=0.6, alpha=0.85))
        px2, py2 = tx([cx, pc["y"] + pc["h"]])
        ax.text(px2, py2 + 3, f"{int(pc['w'])}×{int(pc['h'])}", ha="center", va="top",
                fontsize=5, color="#666666")
        if pc.get("oversize"):
            ax.text(px, py + 6, "⚠ supera il foglio", ha="center", va="top",
                    fontsize=5, color="#B00000", fontweight="bold")

    pdf.savefig(fig)
    plt.close(fig)


def render_assembly(nested: dict, meta: dict) -> bytes:
    sheets = nested.get("sheets")
    if not sheets:
        # fallback: wrap the flat structure as a single sheet
        sheets = [{
            "pieces": nested.get("pieces", []),
            "used_h": nested.get("used_h", 0.0),
            "utilization": nested.get("utilization", 0.0),
            "sheet_w": nested.get("sheet_w", 900.0),
            "sheet_h": nested.get("sheet_h", 2400.0),
        }]
    total = len(sheets)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for i, sh in enumerate(sheets):
            _draw_sheet(pdf, sh, meta, i, total)
    return buf.getvalue()
