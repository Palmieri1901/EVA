"""DXF builder using ezdxf. Units in mm.

Geometry is grouped by CNC tool, one DXF layer per tool, each with a distinct
color (AutoCAD Color Index) so the CAM operator can identify the operation:
  FUGA (blue) · CONTORNO (magenta) · TAGLIO (red) · SVASO (green)
Machine settings for each tool are written into the layer description.
"""
from __future__ import annotations

import io
from typing import Dict, List

import ezdxf
from ezdxf import units

import cnctools

Poly = List[List[float]]
TOOL_ORDER = ["FUGA", "CONTORNO", "TAGLIO", "SVASO"]


def _settings_desc(t: dict) -> str:
    return (f"prof {t.get('depth_mm')}mm | feed {t.get('feed_mm_min')}mm/min | "
            f"{t.get('spindle_rpm')}rpm | {t.get('tool_no')} O{t.get('bit_diameter_mm')}mm | "
            f"{t.get('passes')}x")


def build_dxf(buckets: Dict[str, List[Poly]], tools: List[dict] | None = None) -> bytes:
    """buckets: {"FUGA":[...], "CONTORNO":[...], "TAGLIO":[...], "SVASO":[...]}"""
    tools = tools or cnctools.default_tools()
    tool_by_id = {t["id"]: t for t in tools}

    doc = ezdxf.new("R2010")
    doc.units = units.MM
    doc.header["$INSUNITS"] = 4
    doc.header["$MEASUREMENT"] = 1

    for tid in TOOL_ORDER:
        t = tool_by_id.get(tid) or {"color_aci": 7}
        if tid not in doc.layers:
            layer = doc.layers.add(tid, color=int(t.get("color_aci", 7)))
            try:
                layer.description = _settings_desc(t)
            except Exception:  # noqa: BLE001
                pass

    msp = doc.modelspace()

    def add_poly(points, layer, close):
        if len(points) < 2:
            return
        pts = [(float(p[0]), float(p[1])) for p in points]
        msp.add_lwpolyline(pts, close=close, dxfattribs={"layer": layer})

    for tid in TOOL_ORDER:
        polys = buckets.get(tid) or []
        cut_like = tid in ("TAGLIO", "SVASO")
        for poly in polys:
            close = True if cut_like else (len(poly) > 2 and _is_closed(poly))
            add_poly(poly, tid, close)

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def _is_closed(points, tol=0.01) -> bool:
    a, b = points[0], points[-1]
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol
