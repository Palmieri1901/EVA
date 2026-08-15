"""Simple bounding-box shelf nesting of multiple mat pieces onto an EVA sheet.

Raw EVA sheet default = 1200 x 3000 mm. Pieces are packed by their bounding box
using a first-fit decreasing shelf algorithm with a gap between parts. This is an
MVP nester (bbox-based, no rotation), good enough for an assembled overview and a
combined DXF. Returns translations to move each piece into its slot.
"""
from __future__ import annotations

from typing import List, Tuple

Poly = List[List[float]]

SHEET_W_MM = 900.0
SHEET_H_MM = 2400.0
GAP_MM = 20.0


def _bbox(polys: List[Poly]):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def nest_pieces(pieces: List[dict], sheet_w: float = SHEET_W_MM,
                gap: float = GAP_MM) -> dict:
    """pieces: list of {id, name, cut, engrave}. Returns placements with (dx, dy)
    translations plus overall used size and per-piece placed geometry."""
    placed = []
    # measure
    items = []
    for p in pieces:
        allp = (p.get("cut") or []) + (p.get("engrave") or [])
        if not allp:
            continue
        minx, miny, maxx, maxy = _bbox(allp)
        items.append({
            "id": p.get("id"),
            "name": p.get("name", ""),
            "cut": p.get("cut") or [],
            "engrave": p.get("engrave") or [],
            "minx": minx, "miny": miny,
            "w": max(maxx - minx, 1.0), "h": max(maxy - miny, 1.0),
        })
    # first-fit decreasing by height
    items.sort(key=lambda it: it["h"], reverse=True)

    cursor_x = gap
    cursor_y = gap
    row_h = 0.0
    used_w = 0.0
    for it in items:
        if cursor_x + it["w"] + gap > sheet_w and cursor_x > gap:
            # new shelf
            cursor_y += row_h + gap
            cursor_x = gap
            row_h = 0.0
        dx = cursor_x - it["minx"]
        dy = cursor_y - it["miny"]
        it["dx"], it["dy"] = dx, dy
        placed.append(it)
        cursor_x += it["w"] + gap
        row_h = max(row_h, it["h"])
        used_w = max(used_w, cursor_x)
    used_h = cursor_y + row_h + gap

    def translate(polys: List[Poly], dx: float, dy: float) -> List[Poly]:
        return [[[pt[0] + dx, pt[1] + dy] for pt in poly] for poly in polys]

    out_pieces = []
    all_cut: List[Poly] = []
    all_engrave: List[Poly] = []
    for it in placed:
        c = translate(it["cut"], it["dx"], it["dy"])
        e = translate(it["engrave"], it["dx"], it["dy"])
        all_cut += c
        all_engrave += e
        out_pieces.append({
            "id": it["id"], "name": it["name"],
            "cut": c, "engrave": e,
            "x": it["minx"] + it["dx"], "y": it["miny"] + it["dy"],
            "w": it["w"], "h": it["h"],
        })

    return {
        "pieces": out_pieces,
        "cut": all_cut,
        "engrave": all_engrave,
        "used_w": used_w,
        "used_h": used_h,
        "sheet_w": sheet_w,
        "sheet_h": SHEET_H_MM,
        "overflow": used_h > SHEET_H_MM,
        "count": len(out_pieces),
    }
