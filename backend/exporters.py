"""Multi-format exporters for cut/engrave polylines (mm).

Formats: SVG (vector), PDF (clean drawing), PNG (raster preview), G-code (CNC).
DXF is handled by dxf_builder. All geometry in millimetres, Y grows downward
(same convention as the rest of the app).
"""
from __future__ import annotations

import io
import math
from typing import List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

Poly = List[List[float]]


def _bbox(polys: List[Poly]):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _is_closed(poly: Poly, tol: float = 0.05) -> bool:
    if len(poly) < 3:
        return False
    a, b = poly[0], poly[-1]
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------
def to_svg(cut: List[Poly], engrave: List[Poly]) -> bytes:
    allp = (cut or []) + (engrave or [])
    if not allp:
        raise ValueError("Nessuna geometria da esportare")
    minx, miny, maxx, maxy = _bbox(allp)
    pad = max(maxx - minx, maxy - miny) * 0.02 + 2
    minx -= pad; miny -= pad; maxx += pad; maxy += pad
    w = maxx - minx
    h = maxy - miny

    def path(poly: Poly) -> str:
        d = "M " + " L ".join(f"{p[0]:.3f} {p[1]:.3f}" for p in poly)
        if _is_closed(poly):
            d += " Z"
        return d

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}mm" height="{h:.2f}mm" '
        f'viewBox="{minx:.3f} {miny:.3f} {w:.3f} {h:.3f}">',
        f'<g fill="none" stroke-linejoin="round" stroke-linecap="round">',
    ]
    sw = max(w, h) * 0.0015 + 0.2
    for poly in engrave or []:
        if len(poly) >= 2:
            parts.append(f'<path d="{path(poly)}" stroke="#1f5fbf" stroke-width="{sw:.3f}"/>')
    for poly in cut or []:
        if len(poly) >= 2:
            parts.append(f'<path d="{path(poly)}" stroke="#d00000" stroke-width="{sw*2:.3f}"/>')
    parts.append("</g></svg>")
    return "\n".join(parts).encode("utf-8")


# --------------------------------------------------------------------------
# PNG / PDF drawing (matplotlib)
# --------------------------------------------------------------------------
def _draw(cut: List[Poly], engrave: List[Poly], fmt: str) -> bytes:
    allp = (cut or []) + (engrave or [])
    if not allp:
        raise ValueError("Nessuna geometria da esportare")
    minx, miny, maxx, maxy = _bbox(allp)
    w = max(maxx - minx, 1.0)
    h = max(maxy - miny, 1.0)
    pad = max(w, h) * 0.06 + 5

    # size in inches (cap so PNG stays reasonable)
    scale = 1.0 / 25.4
    fig_w = min((w + 2 * pad) * scale, 40)
    fig_h = min((h + 2 * pad) * scale, 40)
    dpi = 150 if fmt == "png" else 200
    fig = plt.figure(figsize=(max(fig_w, 2), max(fig_h, 2)), dpi=dpi)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(maxy + pad, miny - pad)  # invert Y
    ax.set_aspect("equal")
    ax.axis("off")

    for poly in engrave or []:
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        ax.plot(xs, ys, color="#1f5fbf", lw=0.5, solid_capstyle="round")
    for poly in cut or []:
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        ax.plot(xs, ys, color="#d00000", lw=1.4, solid_capstyle="round")

    # bounding dimensions label
    ax.text((minx + maxx) / 2, miny - pad * 0.5, f"{w:.0f} mm",
            ha="center", va="center", fontsize=8, color="#333")
    ax.text(minx - pad * 0.5, (miny + maxy) / 2, f"{h:.0f} mm",
            ha="center", va="center", fontsize=8, color="#333", rotation=90)

    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, bbox_inches="tight",
                facecolor="white" if fmt == "png" else "none")
    plt.close(fig)
    return buf.getvalue()


def to_png(cut: List[Poly], engrave: List[Poly]) -> bytes:
    return _draw(cut, engrave, "png")


def to_pdf_drawing(cut: List[Poly], engrave: List[Poly]) -> bytes:
    return _draw(cut, engrave, "pdf")


# --------------------------------------------------------------------------
# G-code (GRBL / Mach3 flavours)
# --------------------------------------------------------------------------
GCODE_DEFAULTS = {
    "flavor": "grbl",        # grbl | mach3
    "tool_diameter_mm": 3.0,
    "cut_depth_mm": 3.0,
    "step_down_mm": 1.5,
    "feed_xy": 1000.0,
    "feed_z": 300.0,
    "safe_z_mm": 5.0,
    "spindle_speed": 12000,
    "include_engrave": True,
    "engrave_depth_mm": 1.0,
}


def to_gcode(cut: List[Poly], engrave: List[Poly], params: dict = None) -> bytes:
    p = dict(GCODE_DEFAULTS)
    if params:
        p.update({k: v for k, v in params.items() if v is not None})
    safe_z = float(p["safe_z_mm"])
    feed_xy = float(p["feed_xy"])
    feed_z = float(p["feed_z"])
    spindle = int(p["spindle_speed"])
    flavor = str(p["flavor"]).lower()

    lines: List[str] = []
    lines.append("; EVA Boat Mat Digitizer — G-code")
    lines.append(f"; flavor={flavor} tool={p['tool_diameter_mm']}mm cut_depth={p['cut_depth_mm']}mm")
    lines.append("G21")   # mm
    lines.append("G90")   # absolute
    lines.append("G17")   # XY plane
    lines.append(f"M3 S{spindle}")  # spindle on
    lines.append(f"G0 Z{safe_z:.3f}")

    def pockets(polys: List[Poly], total_depth: float, step: float):
        if total_depth <= 0:
            return
        step = max(step, 0.1)
        n_pass = max(1, math.ceil(total_depth / step))
        for poly in polys:
            pts = poly if len(poly) >= 2 else None
            if not pts:
                continue
            x0, y0 = pts[0][0], pts[0][1]
            lines.append(f"G0 Z{safe_z:.3f}")
            lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
            for k in range(1, n_pass + 1):
                z = -min(step * k, total_depth)
                lines.append(f"G1 Z{z:.3f} F{feed_z:.0f}")
                for pt in pts[1:]:
                    lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{feed_xy:.0f}")
                if _is_closed(poly):
                    lines.append(f"G1 X{x0:.3f} Y{y0:.3f} F{feed_xy:.0f}")
            lines.append(f"G0 Z{safe_z:.3f}")

    if p.get("include_engrave") and engrave:
        lines.append("; --- ENGRAVE ---")
        pockets(engrave, float(p["engrave_depth_mm"]), float(p["step_down_mm"]))
    lines.append("; --- CUT ---")
    pockets(cut, float(p["cut_depth_mm"]), float(p["step_down_mm"]))

    lines.append(f"G0 Z{safe_z:.3f}")
    lines.append("M5")            # spindle off
    lines.append("M30" if flavor == "mach3" else "M2")
    return ("\n".join(lines) + "\n").encode("utf-8")


# --------------------------------------------------------------------------
# Tool-aware G-code: one section per CNC tool, with tool changes between them
# --------------------------------------------------------------------------
def _tool_num(tool_no: str) -> int:
    digits = "".join(ch for ch in str(tool_no) if ch.isdigit())
    return int(digits) if digits else 1


def gcode_tools(buckets: dict, tools: List[dict], params: dict = None) -> bytes:
    """Emit G-code grouped by tool. Each tool prints its own header (tool change,
    spindle speed, feed and depth from its machine settings) so the operator can
    run every operation with the right bit in sequence."""
    import cnctools
    p = dict(GCODE_DEFAULTS)
    if params:
        p.update({k: v for k, v in params.items() if v is not None})
    safe_z = float(p["safe_z_mm"])
    feed_z = float(p["feed_z"])
    flavor = str(p["flavor"]).lower()
    tool_by_id = {t["id"]: t for t in (tools or cnctools.default_tools())}
    order = cnctools.TOOL_IDS

    if not any(buckets.get(tid) for tid in order):
        raise ValueError("Nessuna geometria da esportare")

    lines: List[str] = []
    lines.append("; EVA Boat Mat Digitizer — G-code (per utensile)")
    lines.append("G21")   # mm
    lines.append("G90")   # absolute
    lines.append("G17")   # XY plane
    lines.append(f"G0 Z{safe_z:.3f}")

    def pockets(polys: List[Poly], total_depth: float, step: float, feed_xy: float):
        step = max(step, 0.1)
        total_depth = max(total_depth, 0.1)
        n_pass = max(1, math.ceil(total_depth / step))
        for poly in polys:
            if len(poly) < 2:
                continue
            x0, y0 = poly[0][0], poly[0][1]
            lines.append(f"G0 Z{safe_z:.3f}")
            lines.append(f"G0 X{x0:.3f} Y{y0:.3f}")
            for k in range(1, n_pass + 1):
                z = -min(step * k, total_depth)
                lines.append(f"G1 Z{z:.3f} F{feed_z:.0f}")
                for pt in poly[1:]:
                    lines.append(f"G1 X{pt[0]:.3f} Y{pt[1]:.3f} F{feed_xy:.0f}")
                if _is_closed(poly):
                    lines.append(f"G1 X{x0:.3f} Y{y0:.3f} F{feed_xy:.0f}")
            lines.append(f"G0 Z{safe_z:.3f}")

    first = True
    for tid in order:
        polys = buckets.get(tid) or []
        if not polys:
            continue
        t = tool_by_id.get(tid, {})
        depth = float(t.get("depth_mm", p["cut_depth_mm"]))
        feed_xy = float(t.get("feed_mm_min", p["feed_xy"]))
        spindle = int(float(t.get("spindle_rpm", p["spindle_speed"])))
        tno = _tool_num(t.get("tool_no", "T1"))
        passes = int(t.get("passes", 1) or 1)
        step = depth / max(passes, 1)
        lines.append("")
        lines.append(f"; ===== {tid} — {t.get('name', tid)} =====")
        lines.append(f"; utensile {t.get('tool_no', 'T?')} Ø{t.get('bit_diameter_mm', '?')}mm "
                     f"prof {depth}mm feed {feed_xy}mm/min {spindle}rpm {passes} passate")
        if not first:
            lines.append("M5")                 # stop spindle before tool change
        lines.append(f"G0 Z{safe_z:.3f}")
        lines.append(f"M6 T{tno}")             # tool change
        lines.append(f"M3 S{spindle}")         # spindle on at this tool's speed
        pockets(polys, depth, step, feed_xy)
        first = False

    lines.append("")
    lines.append(f"G0 Z{safe_z:.3f}")
    lines.append("M5")
    lines.append("M30" if flavor == "mach3" else "M2")
    return ("\n".join(lines) + "\n").encode("utf-8")


# --------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------
FORMAT_INFO = {
    "dxf":   ("application/dxf", "dxf"),
    "svg":   ("image/svg+xml", "svg"),
    "pdf":   ("application/pdf", "pdf"),
    "png":   ("image/png", "png"),
    "gcode": ("text/plain", "nc"),
}


def render(fmt: str, cut: List[Poly], engrave: List[Poly], gparams: dict = None) -> Tuple[bytes, str, str]:
    fmt = fmt.lower()
    if fmt not in FORMAT_INFO:
        raise ValueError(f"Formato non supportato: {fmt}")
    if fmt == "svg":
        data = to_svg(cut, engrave)
    elif fmt == "png":
        data = to_png(cut, engrave)
    elif fmt == "pdf":
        data = to_pdf_drawing(cut, engrave)
    elif fmt == "gcode":
        data = to_gcode(cut, engrave, gparams)
    else:
        from dxf_builder import build_dxf
        data = build_dxf({"FUGA": [], "CONTORNO": engrave, "TAGLIO": cut, "SVASO": []})
    mime, ext = FORMAT_INFO[fmt]
    return data, mime, ext
