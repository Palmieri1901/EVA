"""2D irregular-part nesting of mat pieces onto EVA sheets (900 x 2400 mm each).

MaxRects packer (Best-Short-Side-Fit, height-minimising) with optional 90-degree
rotation. Parts that don't fit the remaining space overflow onto additional,
automatically numbered sheets. Returns per-sheet placements plus a combined
geometry (sheets laid side-by-side) for a single nested DXF, and waste stats.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

Poly = List[List[float]]

SHEET_W_MM = 900.0
SHEET_H_MM = 2400.0
GAP_MM = 20.0
SHEET_GAP_MM = 120.0  # horizontal spacing between sheets in the combined DXF


def _bbox(polys: List[Poly]):
    xs = [p[0] for poly in polys for p in poly]
    ys = [p[1] for poly in polys for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _poly_area(poly: Poly) -> float:
    a = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


class _Rect:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


def _split_free(free: List[_Rect], used: _Rect) -> List[_Rect]:
    out: List[_Rect] = []
    for fr in free:
        if (used.x >= fr.x + fr.w or used.x + used.w <= fr.x or
                used.y >= fr.y + fr.h or used.y + used.h <= fr.y):
            out.append(fr)
            continue
        if used.x > fr.x:
            out.append(_Rect(fr.x, fr.y, used.x - fr.x, fr.h))
        if used.x + used.w < fr.x + fr.w:
            out.append(_Rect(used.x + used.w, fr.y, fr.x + fr.w - (used.x + used.w), fr.h))
        if used.y > fr.y:
            out.append(_Rect(fr.x, fr.y, fr.w, used.y - fr.y))
        if used.y + used.h < fr.y + fr.h:
            out.append(_Rect(fr.x, used.y + used.h, fr.w, fr.y + fr.h - (used.y + used.h)))
    pruned: List[_Rect] = []
    for i, a in enumerate(out):
        if a.w <= 1e-6 or a.h <= 1e-6:
            continue
        contained = False
        for j, b in enumerate(out):
            if i == j:
                continue
            if (a.x >= b.x - 1e-6 and a.y >= b.y - 1e-6 and
                    a.x + a.w <= b.x + b.w + 1e-6 and a.y + a.h <= b.y + b.h + 1e-6 and
                    not (a.x == b.x and a.y == b.y and a.w == b.w and a.h == b.h and j > i)):
                contained = True
                break
        if not contained:
            pruned.append(a)
    return pruned


def _best_placement(free: List[_Rect], it: dict, sheet_h: float, gap: float,
                    allow_rotate: bool) -> Optional[tuple]:
    """Return (x, y, rotated, pw, ph) or None if the part can't fit any free
    rect within the sheet height."""
    best = None
    for rotated in ((False, True) if allow_rotate else (False,)):
        pw = (it["h"] if rotated else it["w"]) + gap
        ph = (it["w"] if rotated else it["h"]) + gap
        for fr in free:
            if pw <= fr.w + 1e-6 and ph <= fr.h + 1e-6 and fr.y + ph <= sheet_h + 1e-6:
                lo_w = fr.w - pw
                lo_h = fr.h - ph
                score = (round(fr.y + ph, 3), round(min(lo_w, lo_h), 3),
                         round(max(lo_w, lo_h), 3), round(fr.x, 3))
                if best is None or score < best[0]:
                    best = (score, fr.x, fr.y, rotated, pw, ph)
    if best is None:
        return None
    _, x, y, rotated, pw, ph = best
    return (x, y, rotated, pw, ph)


def nest_pieces(pieces: List[dict], sheet_w: float = SHEET_W_MM,
                sheet_h: float = SHEET_H_MM, gap: float = GAP_MM,
                allow_rotate: bool = True) -> dict:
    items = []
    for p in pieces:
        allp = (p.get("cut") or []) + (p.get("engrave") or [])
        if not allp:
            continue
        minx, miny, maxx, maxy = _bbox(allp)
        w = max(maxx - minx, 1.0)
        h = max(maxy - miny, 1.0)
        cut0 = [[[pt[0] - minx, pt[1] - miny] for pt in poly] for poly in (p.get("cut") or [])]
        eng0 = [[[pt[0] - minx, pt[1] - miny] for pt in poly] for poly in (p.get("engrave") or [])]
        area = sum(_poly_area(poly) for poly in cut0) or (w * h)
        items.append({"id": p.get("id"), "name": p.get("name", ""),
                      "cut": cut0, "engrave": eng0, "w": w, "h": h, "area": area})
    items.sort(key=lambda it: max(it["w"], it["h"]) * (it["w"] * it["h"]), reverse=True)

    # multi-bin packing: open a new sheet whenever a part doesn't fit the open ones
    sheets: List[dict] = []

    def new_sheet():
        s = {"free": [_Rect(0.0, 0.0, sheet_w, sheet_h)], "placed": []}
        sheets.append(s)
        return s

    for it in items:
        done = False
        for sh in sheets:
            pos = _best_placement(sh["free"], it, sheet_h, gap, allow_rotate)
            if pos:
                x, y, rotated, pw, ph = pos
                sh["free"][:] = _split_free(sh["free"], _Rect(x, y, pw, ph))
                sh["placed"].append({**it, "x": x, "y": y, "rotated": rotated, "oversize": False})
                done = True
                break
        if done:
            continue
        # doesn't fit any existing sheet -> new sheet
        sh = new_sheet()
        pos = _best_placement(sh["free"], it, sheet_h, gap, allow_rotate)
        if pos:
            x, y, rotated, pw, ph = pos
            sh["free"][:] = _split_free(sh["free"], _Rect(x, y, pw, ph))
            sh["placed"].append({**it, "x": x, "y": y, "rotated": rotated, "oversize": False})
        else:
            # part is bigger than a whole sheet even rotated: place at origin, flag it
            rotated = allow_rotate and it["h"] > it["w"] and it["w"] <= sheet_w and it["h"] > sheet_w
            sh["placed"].append({**it, "x": 0.0, "y": 0.0, "rotated": rotated, "oversize": True})

    def translate(polys: List[Poly], dx: float, dy: float) -> List[Poly]:
        return [[[pt[0] + dx, pt[1] + dy] for pt in poly] for poly in polys]

    def rot90(polys: List[Poly], h: float) -> List[Poly]:
        # 90 CCW then shift into +quadrant: (x,y)->(h-y, x)
        return [[[h - pt[1], pt[0]] for pt in poly] for poly in polys]

    out_sheets = []
    all_cut: List[Poly] = []
    all_engrave: List[Poly] = []
    max_used_h = 0.0
    total_part_area = 0.0
    any_oversize = False

    for si, sh in enumerate(sheets):
        x_off = si * (sheet_w + SHEET_GAP_MM)  # side-by-side in the combined DXF
        s_pieces = []
        s_cut: List[Poly] = []
        s_eng: List[Poly] = []
        s_used_h = 0.0
        s_area = 0.0
        for it in sh["placed"]:
            x, y, rotated = it["x"], it["y"], it["rotated"]
            cut, eng, w, h = it["cut"], it["engrave"], it["w"], it["h"]
            if rotated:
                cut = rot90(cut, h)
                eng = rot90(eng, h)
                w, h = h, w
            # local (per-sheet) geometry
            c_local = translate(cut, x, y)
            e_local = translate(eng, x, y)
            s_cut += c_local
            s_eng += e_local
            # combined geometry (sheet offset applied)
            all_cut += translate(cut, x + x_off, y)
            all_engrave += translate(eng, x + x_off, y)
            s_used_h = max(s_used_h, y + h)
            s_area += it["area"]
            if it.get("oversize"):
                any_oversize = True
            s_pieces.append({"id": it["id"], "name": it["name"], "cut": c_local,
                             "engrave": e_local, "x": x, "y": y, "w": w, "h": h,
                             "rotated": rotated, "oversize": it.get("oversize", False),
                             "sheet": si})
        util = (s_area / (sheet_w * max(s_used_h, 1.0))) if s_used_h > 0 else 0.0
        out_sheets.append({"index": si, "pieces": s_pieces, "cut": s_cut, "engrave": s_eng,
                           "used_h": s_used_h, "utilization": util,
                           "sheet_w": sheet_w, "sheet_h": sheet_h})
        max_used_h = max(max_used_h, s_used_h)
        total_part_area += s_area

    sheet_count = len(out_sheets)
    all_pieces = [p for s in out_sheets for p in s["pieces"]]
    overall_util = (total_part_area / (sheet_count * sheet_w * sheet_h)) if sheet_count else 0.0

    return {
        "sheets": out_sheets,
        "sheet_count": sheet_count,
        "pieces": all_pieces,          # backward-compat: all pieces (local per-sheet coords)
        "cut": all_cut,                # combined, sheets side-by-side (for nested DXF)
        "engrave": all_engrave,
        "used_w": sheet_w,
        "used_h": max_used_h,
        "sheet_w": sheet_w,
        "sheet_h": sheet_h,
        "overflow": sheet_count > 1 or any_oversize,
        "oversize": any_oversize,
        "count": len(all_pieces),
        "utilization": overall_util,
        "part_area_mm2": total_part_area,
    }
