"""Pydantic models for EVA Boat Mat Digitizer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, List, Optional

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, Field, ConfigDict


def _validate_objectid(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, str):
        return v
    return str(v)


PyObjectId = Annotated[str, BeforeValidator(_validate_objectid)]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Point(BaseModel):
    x: float
    y: float


class MarkerInfo(BaseModel):
    x_px: float
    y_px: float
    diameter_px: float
    circularity: float
    role: str = "unknown"  # corner_tl/tr/br/bl, center


class Quality(BaseModel):
    markers_found: int = 0
    markers_required: int = 5
    sharpness: float = 0.0
    tape_detected: bool = False
    valid: bool = False
    messages: List[str] = Field(default_factory=list)


class Element(BaseModel):
    id: str
    type: str  # text | svg | rect | circle | line | track | polyline
    layer: str = "ENGRAVE"  # CUT | ENGRAVE
    polylines: List[List[List[float]]] = Field(default_factory=list)  # mm
    params: dict = Field(default_factory=dict)


class Project(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str = "Nuovo progetto"
    boat_id: Optional[str] = None       # parent boat/project id
    piece_name: str = "Pezzo 1"         # human name of this mat inside the boat
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    status: str = "draft"  # draft | captured | processed | edited | exported

    # setup params
    background_mode: str = "blue_on_white"  # blue_on_white | white_on_dark
    marker_diameter_mm: float = 20.0
    ref_width_mm: float = 500.0
    ref_height_mm: float = 500.0
    cut_side: str = "inner"  # inner | outer
    blade_offset_mm: float = 0.0
    fillet_radius_mm: float = 0.0
    capture_mode: str = "single"  # single | multi | photogram
    shots: List[dict] = Field(default_factory=list)
    photogram_shots: List[dict] = Field(default_factory=list)
    photogram_mosaic_path: Optional[str] = None
    photogram_mosaic_w: int = 0
    photogram_mosaic_h: int = 0

    # capture / processing
    photo_path: Optional[str] = None
    rectified_path: Optional[str] = None
    rectified_w_px: int = 0
    rectified_h_px: int = 0
    mm_per_px: float = 1.0
    markers: List[MarkerInfo] = Field(default_factory=list)
    quality: Quality = Field(default_factory=Quality)

    # geometry
    contour_mm: List[List[float]] = Field(default_factory=list)
    elements: List[Element] = Field(default_factory=list)

    # export
    dxf_path: Optional[str] = None
    deleted: bool = False


class ProjectCreate(BaseModel):
    name: str = "Nuovo progetto"
    boat_id: Optional[str] = None
    piece_name: str = "Pezzo 1"
    background_mode: str = "blue_on_white"
    marker_diameter_mm: float = 20.0
    ref_width_mm: float = 500.0
    ref_height_mm: float = 500.0
    cut_side: str = "inner"
    blade_offset_mm: float = 0.0
    fillet_radius_mm: float = 0.0
    capture_mode: str = "single"


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    piece_name: Optional[str] = None
    cut_side: Optional[str] = None
    blade_offset_mm: Optional[float] = None
    fillet_radius_mm: Optional[float] = None
    contour_mm: Optional[List[List[float]]] = None
    elements: Optional[List[Element]] = None
    status: Optional[str] = None


class Boat(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str = "Nuova imbarcazione"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    deleted: bool = False


class BoatCreate(BaseModel):
    name: str = "Nuova imbarcazione"


class BoatUpdate(BaseModel):
    name: Optional[str] = None


class TextRequest(BaseModel):
    text: str
    height_mm: float = 30.0
    x: float = 0.0
    y: float = 0.0
    layer: str = "ENGRAVE"


class SvgRequest(BaseModel):
    svg: str
    width_mm: float = 100.0
    x: float = 0.0
    y: float = 0.0
    layer: str = "CUT"


class TrackRequest(BaseModel):
    x: float = 0.0
    y: float = 0.0
    width_mm: float = 100.0
    height_mm: float = 100.0
    spacing_mm: float = 15.0
    angle_deg: float = 45.0
    layer: str = "ENGRAVE"


class FillRequest(BaseModel):
    contour: List[List[float]]
    spacing_mm: float = 15.0
    angle_deg: float = 45.0
    pattern: str = "diamond"  # diamond | cross | lines
    style: str = "semplice"   # semplice | bordato
    border_mm: float = 30.0
    groove_mm: float = 0.0    # caulking groove width (0 = single centerline)
    auto_angle: bool = False  # orient planks along the longest side
    board_length_mm: float = 0.0  # >0 = staggered (brick) plank butt-joints
    exclude: List[List[List[float]]] = Field(default_factory=list)  # text/logo polylines to keep clear
    exclude_margin_mm: float = 0.0  # clear halo around excluded elements
    layer: str = "ENGRAVE"
