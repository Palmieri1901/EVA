"""Geometry helpers: offset, fillet, text->paths, svg->paths, patterns."""
from __future__ import annotations

import logging
import re
from typing import List

import matplotlib

matplotlib.use("Agg")
import math  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.textpath import TextPath  # noqa: E402
from shapely.geometry import LineString, Point, Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from svgpathtools import parse_path  # noqa: E402

logger = logging.getLogger("geometry")

Poly = List[List[float]]  # a single polyline: list of [x,y]


def _ring(points: Poly) -> Polygon:
    if len(points) < 3:
        return Polygon()
    return Polygon(points)


def apply_fillet(points: Poly, radius_mm: float, seg: int = 10) -> Poly:
    """Round each corner of the polygon with a circular arc of the given radius,
    keeping the straight edges in place (true CAD fillet). The radius is clamped
    per-corner so arcs never overrun the adjacent edges."""
    if radius_mm <= 0 or len(points) < 3:
        return points
    pts = [[float(p[0]), float(p[1])] for p in points]
    # drop a duplicated closing point if present
    if len(pts) >= 2 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
        pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return points
    out: Poly = []
    for i in range(n):
        prev = pts[(i - 1) % n]
        cur = pts[i]
        nxt = pts[(i + 1) % n]
        v1x, v1y = prev[0] - cur[0], prev[1] - cur[1]
        v2x, v2y = nxt[0] - cur[0], nxt[1] - cur[1]
        l1 = math.hypot(v1x, v1y)
        l2 = math.hypot(v2x, v2y)
        if l1 < 1e-6 or l2 < 1e-6:
            out.append([cur[0], cur[1]])
            continue
        u1 = (v1x / l1, v1y / l1)
        u2 = (v2x / l2, v2y / l2)
        dot = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
        theta = math.acos(dot)  # interior angle at the vertex
        if theta < 1e-3 or theta > math.pi - 1e-3:
            out.append([cur[0], cur[1]])
            continue
        half = theta / 2.0
        t = radius_mm / math.tan(half)
        tmax = min(l1, l2) * 0.5
        t = min(t, tmax)
        rr = t * math.tan(half)
        p1 = (cur[0] + u1[0] * t, cur[1] + u1[1] * t)
        p2 = (cur[0] + u2[0] * t, cur[1] + u2[1] * t)
        bx, by = u1[0] + u2[0], u1[1] + u2[1]
        bl = math.hypot(bx, by)
        if bl < 1e-6:
            out.append([cur[0], cur[1]])
            continue
        bx, by = bx / bl, by / bl
        center = (cur[0] + bx * (rr / math.sin(half)), cur[1] + by * (rr / math.sin(half)))
        a1 = math.atan2(p1[1] - center[1], p1[0] - center[0])
        a2 = math.atan2(p2[1] - center[1], p2[0] - center[0])
        da = a2 - a1
        while da <= -math.pi:
            da += 2 * math.pi
        while da > math.pi:
            da -= 2 * math.pi
        for k in range(seg + 1):
            a = a1 + da * (k / seg)
            out.append([center[0] + rr * math.cos(a), center[1] + rr * math.sin(a)])
    out.append([out[0][0], out[0][1]])
    return out


def apply_offset(points: Poly, offset_mm: float) -> Poly:
    """Positive offset grows outward (blade compensation)."""
    if offset_mm == 0 or len(points) < 3:
        return points
    poly = _ring(points)
    if not poly.is_valid or poly.is_empty:
        poly = poly.buffer(0)
    try:
        result = poly.buffer(offset_mm, join_style=2)
        if result.is_empty:
            return points
        if result.geom_type == "MultiPolygon":
            result = max(result.geoms, key=lambda g: g.area)
        return [[float(x), float(y)] for x, y in result.exterior.coords]
    except Exception as e:  # noqa: BLE001
        logger.warning("offset failed: %s", e)
        return points


def perimeter_mm(points: Poly) -> float:
    if len(points) < 2:
        return 0.0
    total = 0.0
    n = len(points)
    for i in range(n):
        a = points[i]
        b = points[(i + 1) % n]
        total += ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
    return total


def area_m2(points: Poly) -> float:
    poly = _ring(points)
    if poly.is_empty:
        return 0.0
    if not poly.is_valid:
        poly = poly.buffer(0)
    return float(poly.area) / 1_000_000.0


def bbox_mm(points: Poly):
    if not points:
        return {"w": 0.0, "h": 0.0, "min_x": 0.0, "min_y": 0.0}
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {
        "w": max(xs) - min(xs),
        "h": max(ys) - min(ys),
        "min_x": min(xs),
        "min_y": min(ys),
    }


# --------------------------------------------------------------------------
# Text -> vector paths (filled glyph outlines, ideal for engraving pockets)
# --------------------------------------------------------------------------
def text_to_polylines(text: str, height_mm: float, x: float, y: float) -> List[Poly]:
    if not text.strip():
        return []
    prop = FontProperties(family="DejaVu Sans")
    tp = TextPath((0, 0), text, size=1.0, prop=prop)
    polys = tp.to_polygons(closed_only=False)
    if not polys:
        return []
    # normalize to requested cap height; flip Y (matplotlib is y-up, our plane is y-down)
    all_y = [pt[1] for poly in polys for pt in poly]
    all_x = [pt[0] for poly in polys for pt in poly]
    raw_h = (max(all_y) - min(all_y)) or 1.0
    scale = height_mm / raw_h
    min_x = min(all_x)
    max_y = max(all_y)
    out: List[Poly] = []
    for poly in polys:
        line = [[float((px - min_x) * scale + x), float((max_y - py) * scale + y)] for px, py in poly]
        if len(line) >= 2:
            out.append(line)
    return out


# --------------------------------------------------------------------------
# SVG -> vector paths
# --------------------------------------------------------------------------
def svg_to_polylines(svg: str, width_mm: float, x: float, y: float, samples: int = 60) -> List[Poly]:
    d_attrs = re.findall(r'\sd\s*=\s*"([^"]+)"', svg)
    if not d_attrs:
        d_attrs = re.findall(r"\sd\s*=\s*'([^']+)'", svg)
    raw: List[Poly] = []
    for d in d_attrs:
        try:
            path = parse_path(d)
        except Exception:  # noqa: BLE001
            continue
        if len(path) == 0:
            continue
        pts: Poly = []
        length = path.length() or 1.0
        n = max(20, min(400, int(length / 2)))
        for i in range(n + 1):
            t = i / n
            pt = path.point(t)
            pts.append([pt.real, pt.imag])
        if len(pts) >= 2:
            raw.append(pts)
    if not raw:
        return []
    all_x = [p[0] for poly in raw for p in poly]
    all_y = [p[1] for poly in raw for p in poly]
    raw_w = (max(all_x) - min(all_x)) or 1.0
    scale = width_mm / raw_w
    min_x = min(all_x)
    min_y = min(all_y)
    out: List[Poly] = []
    for poly in raw:
        # SVG y grows downward; flip so it reads naturally in mm plane
        out.append([[float((px - min_x) * scale + x), float((py - min_y) * scale + y)] for px, py in poly])
    return out


# --------------------------------------------------------------------------
# Track pattern (parallel grooves)
# --------------------------------------------------------------------------
def track_pattern(x: float, y: float, width_mm: float, height_mm: float,
                  spacing_mm: float, angle_deg: float) -> List[Poly]:
    spacing_mm = max(spacing_mm, 2.0)
    ang = math.radians(angle_deg)
    dx, dy = math.cos(ang), math.sin(ang)
    nx, ny = -dy, dx  # normal
    diag = (width_mm ** 2 + height_mm ** 2) ** 0.5
    cx, cy = x + width_mm / 2, y + height_mm / 2
    lines: List[Poly] = []
    n = int(diag / spacing_mm) + 1
    clip = Polygon([[x, y], [x + width_mm, y], [x + width_mm, y + height_mm], [x, y + height_mm]])
    for i in range(-n, n + 1):
        off = i * spacing_mm
        px = cx + nx * off
        py = cy + ny * off
        p1 = (px - dx * diag, py - dy * diag)
        p2 = (px + dx * diag, py + dy * diag)
        seg = LineString([p1, p2]).intersection(clip)
        if seg.is_empty or seg.geom_type != "LineString":
            continue
        coords = list(seg.coords)
        if len(coords) >= 2:
            lines.append([[float(a), float(b)] for a, b in coords])
    return lines


# --------------------------------------------------------------------------
# Fill area with texture, clipped to an arbitrary contour polygon.
# pattern: "diamond" (teak lattice), "cross" (orthogonal), "lines" (planks)
# style:   "semplice" (fill to edge) | "bordato" (inset border frame + field)
# --------------------------------------------------------------------------
def _hatch(field: Polygon, spacing: float, angle_deg: float) -> List[Poly]:
    minx, miny, maxx, maxy = field.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    diag = math.hypot(maxx - minx, maxy - miny) + spacing
    ang = math.radians(angle_deg)
    dx, dy = math.cos(ang), math.sin(ang)
    nx, ny = -dy, dx
    out: List[Poly] = []
    n = int(diag / spacing) + 2
    for i in range(-n, n + 1):
        off = i * spacing
        px, py = cx + nx * off, cy + ny * off
        seg = LineString([(px - dx * diag, py - dy * diag), (px + dx * diag, py + dy * diag)])
        inter = seg.intersection(field)
        if inter.is_empty:
            continue
        geoms = list(inter.geoms) if inter.geom_type.startswith("Multi") else [inter]
        for g in geoms:
            if g.geom_type == "LineString" and len(g.coords) >= 2:
                out.append([[float(a), float(b)] for a, b in g.coords])
    return out


def _poly_exteriors(geom) -> List[Poly]:
    rings: List[Poly] = []
    if geom.is_empty:
        return rings
    parts = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    for p in parts:
        rings.append([[float(x), float(y)] for x, y in p.exterior.coords])
    return rings


def _all_rings(geom) -> List[Poly]:
    """Every ring (exteriors + holes) of a Polygon/MultiPolygon as closed polylines."""
    rings: List[Poly] = []
    if geom.is_empty:
        return rings
    parts = list(geom.geoms) if geom.geom_type.startswith("Multi") else [geom]
    for p in parts:
        if p.geom_type != "Polygon":
            continue
        rings.append([[float(x), float(y)] for x, y in p.exterior.coords])
        for interior in p.interiors:
            rings.append([[float(x), float(y)] for x, y in interior.coords])
    return rings


def _longest_edge_angle(poly: Polygon) -> float:
    """Angle (deg) of the longest side of the polygon's min-area rectangle."""
    try:
        mrr = poly.minimum_rotated_rectangle
        coords = list(mrr.exterior.coords)
    except Exception:  # noqa: BLE001
        return 0.0
    best_len, best_ang = 0.0, 0.0
    for i in range(len(coords) - 1):
        ax, ay = coords[i]
        bx, by = coords[i + 1]
        length = math.hypot(bx - ax, by - ay)
        if length > best_len:
            best_len = length
            best_ang = math.degrees(math.atan2(by - ay, bx - ax))
    return best_ang


def _staggered_planks(field: Polygon, plank_w: float, angle_deg: float,
                      board_len: float, stagger_frac: float = 0.5) -> List[Poly]:
    """Brick-laid planks: long grooves between rows + staggered butt joints."""
    minx, miny, maxx, maxy = field.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    ang = math.radians(angle_deg)
    dx, dy = math.cos(ang), math.sin(ang)
    nx, ny = -dy, dx
    corners = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
    us = [(px - cx) * dx + (py - cy) * dy for px, py in corners]
    vs = [(px - cx) * nx + (py - cy) * ny for px, py in corners]
    umin, umax = min(us) - plank_w, max(us) + plank_w
    vmin, vmax = min(vs) - plank_w, max(vs) + plank_w

    def to_xy(u, v):
        return (cx + dx * u + nx * v, cy + dy * u + ny * v)

    segs: List[LineString] = []
    k0 = int(math.floor(vmin / plank_w))
    k1 = int(math.ceil(vmax / plank_w))
    row = 0
    for k in range(k0, k1 + 1):
        v = k * plank_w
        segs.append(LineString([to_xy(umin, v), to_xy(umax, v)]))  # long groove
        if board_len > 0:
            v0, v1 = k * plank_w, (k + 1) * plank_w
            offset = ((row * stagger_frac) % 1.0) * board_len
            m0 = int(math.floor((umin - offset) / board_len))
            m1 = int(math.ceil((umax - offset) / board_len))
            for m in range(m0, m1 + 1):
                u = offset + m * board_len
                segs.append(LineString([to_xy(u, v0), to_xy(u, v1)]))  # butt joint
        row += 1

    out: List[Poly] = []
    for s in segs:
        inter = s.intersection(field)
        if inter.is_empty:
            continue
        geoms = list(inter.geoms) if inter.geom_type.startswith("Multi") else [inter]
        for g in geoms:
            if g.geom_type == "LineString" and len(g.coords) >= 2:
                out.append([[float(a), float(b)] for a, b in g.coords])
    return out


def _build_keepout(exclude: List[Poly], margin: float):
    """Clear-zone geometry: closed shapes (logos/glyphs) are filled and buffered,
    open strokes are buffered as bands. Union → one keep-out region."""
    if not exclude:
        return None
    shapes = []
    m = max(margin, 0.1)
    for line in exclude:
        if not line or len(line) < 2:
            continue
        try:
            if len(line) >= 3:
                p = Polygon(line)
                if not p.is_valid:
                    p = p.buffer(0)
                if not p.is_empty and p.area > 1e-6:
                    shapes.append(p.buffer(m, join_style=1))
                    continue
            shapes.append(LineString(line).buffer(m, cap_style=1, join_style=1))
        except Exception:  # noqa: BLE001
            try:
                shapes.append(LineString(line).buffer(m, cap_style=1, join_style=1))
            except Exception:  # noqa: BLE001
                continue
    if not shapes:
        return None
    zone = unary_union(shapes)
    if zone.is_empty:
        return None
    return zone


def _corner_grooves(contour_poly, inset_poly, border_mm: float,
                    min_turn_deg: float = 22.0) -> List[Poly]:
    """Miter grooves at each corner of the border frame: a short groove from the
    contour corner across the border band to the inner border, like real teak
    mats. Rounded corners are detected via simplification of the contour."""
    grooves: List[Poly] = []
    try:
        simp = contour_poly.simplify(max(border_mm * 0.6, 8.0), preserve_topology=True)
        ext = list(simp.exterior.coords)[:-1]
    except Exception:
        return grooves
    n = len(ext)
    if n < 3:
        return grooves
    iring = inset_poly.exterior
    for i in range(n):
        a, b, c = ext[(i - 1) % n], ext[i], ext[(i + 1) % n]
        d1x, d1y = b[0] - a[0], b[1] - a[1]
        d2x, d2y = c[0] - b[0], c[1] - b[1]
        l1 = math.hypot(d1x, d1y); l2 = math.hypot(d2x, d2y)
        if l1 < 1e-6 or l2 < 1e-6:
            continue
        cross = (d1x * d2y - d1y * d2x) / (l1 * l2)
        dot = (d1x * d2x + d1y * d2y) / (l1 * l2)
        turn = abs(math.degrees(math.atan2(cross, dot)))
        if turn < min_turn_deg:
            continue
        pt = Point(b)
        proj = iring.interpolate(iring.project(pt))
        if pt.distance(proj) > 3.0:
            grooves.append([[b[0], b[1]], [proj.x, proj.y]])
    return grooves



def fill_pattern(contour: Poly, spacing_mm: float, angle_deg: float,
                 pattern: str = "diamond", style: str = "semplice",
                 border_mm: float = 30.0, groove_mm: float = 0.0,
                 auto_angle: bool = False, board_length_mm: float = 0.0,
                 exclude: List[Poly] = None, exclude_margin_mm: float = 0.0,
                 diamond_height_mm: float = 0.0, corner_radius_mm: float = 0.0,
                 plank_ease_mm: float = 0.0) -> dict:
    poly = _ring(contour)
    if not poly.is_valid or poly.is_empty:
        poly = poly.buffer(0)
    if poly.is_empty:
        return {"pattern": [], "border": [], "angle_used": angle_deg}

    orig_poly = poly  # full contour, used to clip grooves / keep-out outline

    if auto_angle:
        angle_deg = _longest_edge_angle(poly)

    spacing = max(spacing_mm, 3.0)
    border_lines: List[Poly] = []
    field = poly
    border_only = style == "bordo"  # only the frame, no interior planks/diamonds

    if style in ("bordato", "bordo") and border_mm > 0:
        # inset border that follows the contour; round its corners (morphological
        # opening) so corners/curves look like real teak mat borders in the photos.
        inset = poly.buffer(-border_mm, join_style=1, resolution=24)
        if not inset.is_empty:
            R = corner_radius_mm if (corner_radius_mm and corner_radius_mm > 0) else min(border_mm * 1.5, 70.0)
            if R > 1:
                opened = inset.buffer(-R, join_style=1, resolution=24).buffer(R, join_style=1, resolution=24)
                if not opened.is_empty and opened.area > inset.area * 0.4:
                    inset = opened
            if inset.geom_type == "MultiPolygon":
                inset = max(inset.geoms, key=lambda g: g.area)
            border_lines = _poly_exteriors(inset)
            # miter grooves at every corner of the frame (like real teak mats)
            border_lines += _corner_grooves(orig_poly, inset, border_mm)
            field = inset

    # Clear zone around text/logo: subtract keep-out from the hatch field,
    # and keep its outline as a groove that delimits the empty area.
    keep_rings: List[Poly] = []
    keepout = _build_keepout(exclude or [], exclude_margin_mm)
    if keepout is not None:
        try:
            keep_rings = _all_rings(keepout.intersection(orig_poly))
            field = field.difference(keepout)
            poly = poly.difference(keepout)
        except Exception:  # noqa: BLE001
            pass
        if field.is_empty:
            return {"pattern": [], "border": border_lines + keep_rings, "angle_used": angle_deg}

    lines: List[Poly] = []
    # "Doghe svasate": plank ends eased back from the border with a rounded set-back
    # so they don't hard-butt the frame, like real teak. Applies to planks/lines only.
    plank_field = field
    if plank_ease_mm and plank_ease_mm > 0 and pattern not in ("diamond", "cross"):
        try:
            pf = field.buffer(-plank_ease_mm, join_style=1, resolution=16)
            if not pf.is_empty and pf.area > field.area * 0.3:
                plank_field = pf
        except Exception:  # noqa: BLE001
            pass
    if border_only:
        # Only the frame (+ corner grooves + keep-out rings): no interior pattern.
        pass
    elif pattern == "diamond":
        # Diamond (rhombus) grid of width W and height H. The two edge families run
        # at +/- theta from the orientation angle, where theta = atan2(H, W); their
        # perpendicular spacing (W*H)/hypot(W,H) makes the diamonds tile exactly.
        # Using +/-theta (never 0) fixes the old bug where angle 0 collapsed the two
        # families into plain parallel lines.
        w_cell = spacing
        h_cell = diamond_height_mm if diamond_height_mm and diamond_height_mm > 0 else spacing
        theta = math.degrees(math.atan2(h_cell, w_cell))
        perp = (w_cell * h_cell) / math.hypot(w_cell, h_cell)
        perp = max(perp, 2.0)
        lines += _hatch(field, perp, angle_deg + theta)
        lines += _hatch(field, perp, angle_deg - theta)
    elif pattern == "cross":
        lines += _hatch(field, spacing, angle_deg)
        lines += _hatch(field, spacing, angle_deg + 90)
    else:  # lines / planks
        if board_length_mm and board_length_mm > 0:
            lines += _staggered_planks(plank_field, spacing, angle_deg, board_length_mm, 0.5)
        else:
            lines += _hatch(plank_field, spacing, angle_deg)

    # Caulking groove: turn centerlines (and border + keep-out outline) into thin channel pockets.
    if groove_mm and groove_mm > 0:
        segs = [LineString(l) for l in lines if len(l) >= 2]
        for b in border_lines:
            if len(b) >= 2:
                segs.append(LineString(b))
        for kr in keep_rings:
            if len(kr) >= 2:
                segs.append(LineString(kr))
        if not segs:
            return {"pattern": [], "border": [], "angle_used": angle_deg}
        buffered = unary_union([s.buffer(groove_mm / 2.0, cap_style=2, join_style=2) for s in segs])
        clipped = buffered.intersection(orig_poly)
        return {"pattern": _all_rings(clipped), "border": [], "angle_used": angle_deg}

    return {"pattern": lines, "border": border_lines + keep_rings, "angle_used": angle_deg}
