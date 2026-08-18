"""2D irregular-part nesting of mat pieces onto an EVA sheet (900 x 2400 mm).

Uses a MaxRects packer (Best-Short-Side-Fit heuristic, tuned to minimise the
total used height in a fixed-width sheet) with optional 90-degree rotation of
each part. Parts are packed by their bounding box (fast + robust); rotation and
bottom-left placement noticeably reduce wasted rubber versus the old shelf
packer. Returns per-piece translated/rotated geometry + waste stats.
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


def _rotate90(polys: List[Poly]) -> List[Poly]:
    """Rotate 90 deg CCW about the origin: (x, y) -> (-y, x)."""
    return [[[-pt[1], pt[0]] for pt in poly] for poly in polys]


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
    """MaxRects split: replace every free rect overlapping `used` with the
    sub-rects that remain free, then prune contained rects."""
    out: List[_Rect] = []
    for fr in free:
        if (used.x >= fr.x + fr.w or used.x + used.w <= fr.x or
                used.y >= fr.y + fr.h or used.y + used.h <= fr.y):
            out.append(fr)  # no overlap
            continue
        # left slab
        if used.x > fr.x:
            out.append(_Rect(fr.x, fr.y, used.x - fr.x, fr.h))
        # right slab
        if used.x + used.w < fr.x + fr.w:
            out.append(_Rect(used.x + used.w, fr.y, fr.x + fr.w - (used.x + used.w), fr.h))
        # bottom slab
        if used.y > fr.y:
            out.append(_Rect(fr.x, fr.y, fr.w, used.y - fr.y))
        # top slab
        if used.y + used.h < fr.y + fr.h:
            out.append(_Rect(fr.x, used.y + used.h, fr.w, fr.y + fr.h - (used.y + used.h)))
    # prune rects fully contained in another
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
                    not (a.w == b.w and a.h == b.h and a.x == b.x and a.y == b.y and j > i)):
                contained = True
                break
        if not contained:
            pruned.append(a)
    return pruned


def nest_pieces(pieces: List[dict], sheet_w: float = SHEET_W_MM,
                gap: float = GAP_MM, allow_rotate: bool = True) -> dict:
    """pieces: list of {id, name, cut, engrave}. Returns placements with placed
    geometry (already translated/rotated) plus used size and waste stats."""
    items = []
    for p in pieces:
        allp = (p.get("cut") or []) + (p.get("engrave") or [])
        if not allp:
            continue
        minx, miny, maxx, maxy = _bbox(allp)
        w = max(maxx - minx, 1.0)
        h = max(maxy - miny, 1.0)
        # normalise so the part sits at the origin (min corner at 0,0)
        cut0 = [[[pt[0] - minx, pt[1] - miny] for pt in poly] for poly in (p.get("cut") or [])]
        eng0 = [[[pt[0] - minx, pt[1] - miny] for pt in poly] for poly in (p.get("engrave") or [])]
        area = sum(_poly_area(poly) for poly in cut0) or (w * h)
        items.append({
            "id": p.get("id"), "name": p.get("name", ""),
            "cut": cut0, "engrave": eng0, "w": w, "h": h, "area": area,
        })
    # pack larger parts first
    items.sort(key=lambda it: max(it["w"], it["h"]) * (it["w"] * it["h"]), reverse=True)

    BIG_H = SHEET_H_MM * 20.0  # virtually unbounded so every part is placed
    free: List[_Rect] = [_Rect(0.0, 0.0, sheet_w, BIG_H)]
    placed = []

    for it in items:
        best = None  # (top_edge, short_leftover, long_leftover, x, y, rotated)
        for rotated in ((False, True) if allow_rotate else (False,)):
            pw = (it["h"] if rotated else it["w"]) + gap
            ph = (it["w"] if rotated else it["h"]) + gap
            for fr in free:
                if pw <= fr.w + 1e-6 and ph <= fr.h + 1e-6:
                    lo_w = fr.w - pw
                    lo_h = fr.h - ph
                    short = min(lo_w, lo_h)
                    long = max(lo_w, lo_h)
                    top_edge = fr.y + ph  # minimise sheet height used
                    score = (round(top_edge, 3), round(short, 3), round(long, 3), round(fr.x, 3))
                    if best is None or score < best[0]:
                        best = (score, fr.x, fr.y, rotated, pw, ph)
        if best is None:
            continue
        _, x, y, rotated, pw, ph = best
        free[:] = _split_free(free, _Rect(x, y, pw, ph))
        it["place"] = (x, y, rotated)
        placed.append(it)

    def translate(polys: List[Poly], dx: float, dy: float) -> List[Poly]:
        return [[[pt[0] + dx, pt[1] + dy] for pt in poly] for poly in polys]

    out_pieces = []
    all_cut: List[Poly] = []
    all_engrave: List[Poly] = []
    used_w = 0.0
    used_h = 0.0
    for it in placed:
        x, y, rotated = it["place"]
        cut = it["cut"]
        eng = it["engrave"]
        w, h = it["w"], it["h"]
        if rotated:
            # rotate 90 CCW then shift back into positive quadrant (width<-h)
            cut = [[[h - pt[1], pt[0]] for pt in poly] for poly in cut]
            eng = [[[h - pt[1], pt[0]] for pt in poly] for poly in eng]
            w, h = h, w
        c = translate(cut, x, y)
        e = translate(eng, x, y)
        all_cut += c
        all_engrave += e
        used_w = max(used_w, x + w)
        used_h = max(used_h, y + h)
        out_pieces.append({
            "id": it["id"], "name": it["name"], "cut": c, "engrave": e,
            "x": x, "y": y, "w": w, "h": h, "rotated": rotated,
        })

    part_area = sum(it["area"] for it in placed)
    sheet_used_area = sheet_w * max(used_h, 1.0)
    utilization = (part_area / sheet_used_area) if sheet_used_area > 0 else 0.0

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
        "utilization": utilization,
        "part_area_mm2": part_area,
    }
