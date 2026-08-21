"""CNC tool definitions, colors and auto-classification of engraving/cut types.

Four tools, each mapped to a DXF layer with a distinct color and machine
settings that the user can tweak in-app:
  FUGA     - caulking grooves between teak planks (incisione fuga)   -> blue
  CONTORNO - outlines of text / logos / shapes (incisione contorno)  -> magenta
  TAGLIO   - inner cut lines / junctions                             -> red
  SVASO    - outer perimeter bevel (larger V-bit)                    -> green
"""
from __future__ import annotations

from typing import List

TOOL_IDS = ["FUGA", "BORDO", "CONTORNO", "TAGLIO", "SVASO"]

DEFAULT_TOOLS: List[dict] = [
    {"id": "FUGA", "name": "Fresa incisione fuga", "color_aci": 5, "color_hex": "#2563EB",
     "depth_mm": 2.0, "feed_mm_min": 2500.0, "spindle_rpm": 18000.0, "tool_no": "T1",
     "bit_diameter_mm": 3.0, "passes": 1},
    {"id": "BORDO", "name": "Fresa incisione bordatura", "color_aci": 4, "color_hex": "#06B6D4",
     "depth_mm": 2.0, "feed_mm_min": 2200.0, "spindle_rpm": 18000.0, "tool_no": "T5",
     "bit_diameter_mm": 4.0, "passes": 1},
    {"id": "CONTORNO", "name": "Fresa incisione contorno", "color_aci": 6, "color_hex": "#DB2777",
     "depth_mm": 1.5, "feed_mm_min": 2000.0, "spindle_rpm": 18000.0, "tool_no": "T2",
     "bit_diameter_mm": 2.0, "passes": 1},
    {"id": "TAGLIO", "name": "Fresa taglio", "color_aci": 1, "color_hex": "#DC2626",
     "depth_mm": 6.0, "feed_mm_min": 1500.0, "spindle_rpm": 16000.0, "tool_no": "T3",
     "bit_diameter_mm": 6.0, "passes": 2},
    {"id": "SVASO", "name": "Fresa svaso esterno", "color_aci": 3, "color_hex": "#16A34A",
     "depth_mm": 6.0, "feed_mm_min": 1200.0, "spindle_rpm": 16000.0, "tool_no": "T4",
     "bit_diameter_mm": 8.0, "passes": 2},
]


def default_tools() -> List[dict]:
    return [dict(t) for t in DEFAULT_TOOLS]


def classify_element(el: dict) -> str:
    """Auto tool for an element when it has no explicit `tool`."""
    tool = el.get("tool")
    if tool in TOOL_IDS:
        return tool
    etype = el.get("type", "")
    layer = el.get("layer", "ENGRAVE")
    if layer == "CUT" or etype == "junction":
        return "TAGLIO"
    if etype in ("fill", "track"):
        return "FUGA"
    if etype in ("text", "svg", "dxf", "circle", "line", "rect"):
        return "CONTORNO"
    return "CONTORNO"
