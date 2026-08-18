"""DXF builder using ezdxf. Units in mm, layers CUT (red) and ENGRAVE (blue)."""
from __future__ import annotations

import io
from typing import List

import ezdxf
from ezdxf import units


def build_dxf(cut_polys: List[List[List[float]]], engrave_polys: List[List[List[float]]],
              bevel_polys: List[List[List[float]]] | None = None) -> bytes:
    doc = ezdxf.new("R2010")
    doc.units = units.MM
    doc.header["$INSUNITS"] = 4  # millimeters
    doc.header["$MEASUREMENT"] = 1  # metric

    if "CUT" not in doc.layers:
        doc.layers.add("CUT", color=1)  # red
    if "ENGRAVE" not in doc.layers:
        doc.layers.add("ENGRAVE", color=5)  # blue
    if "SVASO_EST" not in doc.layers:
        doc.layers.add("SVASO_EST", color=3)  # green — outer bevel (larger V-bit)

    msp = doc.modelspace()

    def add_poly(points, layer, close):
        if len(points) < 2:
            return
        pts = [(float(p[0]), float(p[1])) for p in points]
        msp.add_lwpolyline(pts, close=close, dxfattribs={"layer": layer})

    # outer perimeter bevel: separate layer (cut with a different, larger V-bit)
    for poly in (bevel_polys or []):
        add_poly(poly, "SVASO_EST", close=True)
    for poly in cut_polys:
        add_poly(poly, "CUT", close=True)
    for poly in engrave_polys:
        # engrave polylines may be open (text strokes) or closed shapes; keep as-is closed
        closed = len(poly) > 2 and _is_closed(poly)
        add_poly(poly, "ENGRAVE", close=closed)

    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def _is_closed(points, tol=0.01) -> bool:
    a, b = points[0], points[-1]
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol
