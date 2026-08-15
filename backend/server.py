"""EVA Boat Mat Digitizer — FastAPI backend.

Pipeline: photo -> marker detection -> homography rectification ->
tape-edge segmentation -> vectorized contour (mm) -> editor -> DXF export.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

import cv_pipeline as cv
import geometry_ops as geo
import storage_client as store
from dxf_builder import build_dxf
from models import (
    Element,
    MarkerInfo,
    Project,
    ProjectCreate,
    ProjectUpdate,
    Quality,
    SvgRequest,
    TextRequest,
    TrackRequest,
    now_iso,
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("server")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="EVA Boat Mat Digitizer")
api_router = APIRouter(prefix="/api")

BACKEND_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def serialize(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def file_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return f"/api/files/{path}"


async def get_project_doc(project_id: str) -> dict:
    try:
        oid = ObjectId(project_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID progetto non valido")
    doc = await db.projects.find_one({"_id": oid, "deleted": {"$ne": True}})
    if not doc:
        raise HTTPException(status_code=404, detail="Progetto non trovato")
    return doc


# --------------------------------------------------------------------------
# Health & patterns
# --------------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"message": "EVA Boat Mat Digitizer API", "status": "ok"}


PATTERN_LIBRARY = [
    {"id": "track_45", "name": "Track 45°", "type": "track", "params": {"spacing_mm": 15, "angle_deg": 45}},
    {"id": "track_90", "name": "Track lineare", "type": "track", "params": {"spacing_mm": 12, "angle_deg": 0}},
    {"id": "diamond", "name": "Diamante", "type": "track", "params": {"spacing_mm": 20, "angle_deg": 45}},
    {"id": "cross_hatch", "name": "Incrociato", "type": "track", "params": {"spacing_mm": 18, "angle_deg": 90}},
]


@api_router.get("/patterns")
async def get_patterns():
    return PATTERN_LIBRARY


# --------------------------------------------------------------------------
# Projects CRUD
# --------------------------------------------------------------------------
@api_router.post("/projects")
async def create_project(payload: ProjectCreate):
    proj = Project(**payload.model_dump())
    doc = proj.model_dump(by_alias=True, exclude={"id"})
    res = await db.projects.insert_one(doc)
    saved = await db.projects.find_one({"_id": res.inserted_id})
    return serialize(saved)


@api_router.get("/projects")
async def list_projects():
    docs = await db.projects.find({"deleted": {"$ne": True}}).sort("updated_at", -1).to_list(500)
    out = []
    for d in docs:
        s = serialize(d)
        s["photo_url"] = file_url(d.get("photo_path"))
        s["rectified_url"] = file_url(d.get("rectified_path"))
        out.append(s)
    return out


@api_router.get("/projects/{project_id}")
async def get_project(project_id: str):
    doc = await get_project_doc(project_id)
    s = serialize(doc)
    s["photo_url"] = file_url(doc.get("photo_path"))
    s["rectified_url"] = file_url(doc.get("rectified_path"))
    s["dxf_url"] = file_url(doc.get("dxf_path"))
    return s


@api_router.patch("/projects/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdate):
    doc = await get_project_doc(project_id)
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    updates["updated_at"] = now_iso()
    await db.projects.update_one({"_id": doc["_id"]}, {"$set": updates})
    saved = await db.projects.find_one({"_id": doc["_id"]})
    return serialize(saved)


@api_router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    doc = await get_project_doc(project_id)
    await db.projects.update_one({"_id": doc["_id"]}, {"$set": {"deleted": True, "updated_at": now_iso()}})
    return {"ok": True}


# --------------------------------------------------------------------------
# Photo upload
# --------------------------------------------------------------------------
@api_router.post("/projects/{project_id}/photo")
async def upload_photo(project_id: str, file: UploadFile = File(...)):
    doc = await get_project_doc(project_id)
    data = await file.read()
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    path = f"{store.APP_NAME}/uploads/{project_id}/{uuid.uuid4()}.{ext}"
    ctype = file.content_type or "image/jpeg"
    await run_in_threadpool(store.put_object, path, data, ctype)
    await db.projects.update_one(
        {"_id": doc["_id"]},
        {"$set": {"photo_path": path, "status": "captured", "updated_at": now_iso()}},
    )
    return {"photo_path": path, "photo_url": file_url(path)}


# --------------------------------------------------------------------------
# CV processing
# --------------------------------------------------------------------------
def _run_pipeline(img_bytes: bytes, project: dict) -> dict:
    arr = np.frombuffer(img_bytes, np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Immagine non decodificabile")

    bg = project["background_mode"]
    raw_markers = cv.detect_markers(bgr, bg)
    corners, center = cv.order_markers(raw_markers)

    messages: List[str] = []
    markers_out: List[dict] = []
    sharp = cv.sharpness(bgr)

    if len(corners) < 4:
        messages.append("Meno di 4 bollini rilevati: usa la correzione manuale.")
        # fallback: rectangle from ref size, no rectified image
        w, h = project["ref_width_mm"], project["ref_height_mm"]
        contour = [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]]
        contour = geo.simplify_contour_mm(contour)
        quality = Quality(
            markers_found=len(raw_markers), sharpness=sharp, tape_detected=False, valid=False,
            messages=messages,
        )
        return {
            "markers": [MarkerInfo(x_px=m["x"], y_px=m["y"], diameter_px=m["d"],
                                   circularity=m["circ"]).model_dump() for m in raw_markers],
            "quality": quality.model_dump(),
            "contour_mm": contour,
            "rectified": None,
        }

    for c in corners:
        markers_out.append(MarkerInfo(x_px=c["x"], y_px=c["y"], diameter_px=c["d"],
                                      circularity=c["circ"], role=c.get("role", "corner")).model_dump())
    if center:
        markers_out.append(MarkerInfo(x_px=center["x"], y_px=center["y"], diameter_px=center["d"],
                                      circularity=center["circ"], role="center").model_dump())

    H_mm, mm_per_px, out_w, out_h, M_px = cv.compute_rectification(
        corners, project["ref_width_mm"], project["ref_height_mm"]
    )
    rectified = cv2.warpPerspective(bgr, M_px, (out_w, out_h))

    mask = cv.tape_mask(rectified, bg)
    tape_area = float(np.count_nonzero(mask)) / (out_w * out_h)
    tape_detected = tape_area > 0.005
    contour_px = cv.extract_contour(mask, project["cut_side"]) if tape_detected else None

    if contour_px is not None and len(contour_px) >= 4:
        contour_mm = cv.px_to_mm(contour_px, mm_per_px)
        contour_mm = cv.simplify_contour_mm(contour_mm, tolerance_mm=0.6)
        messages.append("Bordo nastro rilevato.")
    else:
        tape_detected = False
        w, h = project["ref_width_mm"], project["ref_height_mm"]
        margin = min(w, h) * 0.1
        contour_mm = [[margin, margin], [w - margin, margin], [w - margin, h - margin], [margin, h - margin]]
        messages.append("Nastro non rilevato: contorno provvisorio, correggilo nell'editor.")

    ok, buf = cv2.imencode(".jpg", rectified, [cv2.IMWRITE_JPEG_QUALITY, 88])
    rect_bytes = buf.tobytes() if ok else None

    valid = len(corners) >= 4 and (center is not None) and sharp > 40 and tape_detected
    if sharp <= 40:
        messages.append("Immagine poco nitida.")
    quality = Quality(
        markers_found=len(markers_out), sharpness=sharp, tape_detected=tape_detected,
        valid=valid, messages=messages,
    )
    return {
        "markers": markers_out,
        "quality": quality.model_dump(),
        "contour_mm": contour_mm,
        "rectified": {"bytes": rect_bytes, "w": out_w, "h": out_h, "mm_per_px": mm_per_px},
    }


@api_router.post("/projects/{project_id}/process")
async def process_project(project_id: str):
    doc = await get_project_doc(project_id)
    if not doc.get("photo_path"):
        raise HTTPException(status_code=400, detail="Nessuna foto caricata per questo progetto")

    img_bytes, _ = await run_in_threadpool(store.get_object, doc["photo_path"])
    try:
        result = await run_in_threadpool(_run_pipeline, img_bytes, doc)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    updates = {
        "markers": result["markers"],
        "quality": result["quality"],
        "contour_mm": result["contour_mm"],
        "status": "processed",
        "updated_at": now_iso(),
    }
    rect = result.get("rectified")
    if rect and rect.get("bytes"):
        rpath = f"{store.APP_NAME}/rectified/{project_id}/{uuid.uuid4()}.jpg"
        await run_in_threadpool(store.put_object, rpath, rect["bytes"], "image/jpeg")
        updates.update({
            "rectified_path": rpath,
            "rectified_w_px": rect["w"],
            "rectified_h_px": rect["h"],
            "mm_per_px": rect["mm_per_px"],
        })
    await db.projects.update_one({"_id": doc["_id"]}, {"$set": updates})
    saved = await db.projects.find_one({"_id": doc["_id"]})
    s = serialize(saved)
    s["rectified_url"] = file_url(saved.get("rectified_path"))
    return s


# --------------------------------------------------------------------------
# Geometry generation for elements
# --------------------------------------------------------------------------
@api_router.post("/geometry/text")
async def geometry_text(req: TextRequest):
    polys = await run_in_threadpool(geo.text_to_polylines, req.text, req.height_mm, req.x, req.y)
    return {"polylines": polys}


@api_router.post("/geometry/svg")
async def geometry_svg(req: SvgRequest):
    polys = await run_in_threadpool(geo.svg_to_polylines, req.svg, req.width_mm, req.x, req.y)
    if not polys:
        raise HTTPException(status_code=422, detail="Nessun tracciato <path> trovato nell'SVG")
    return {"polylines": polys}


@api_router.post("/geometry/track")
async def geometry_track(req: TrackRequest):
    polys = await run_in_threadpool(
        geo.track_pattern, req.x, req.y, req.width_mm, req.height_mm, req.spacing_mm, req.angle_deg
    )
    return {"polylines": polys}


# --------------------------------------------------------------------------
# Final geometry preview + DXF export
# --------------------------------------------------------------------------
def _compute_final(doc: dict):
    base = doc.get("contour_mm") or []
    if doc.get("fillet_radius_mm", 0):
        base = geo.apply_fillet(base, doc["fillet_radius_mm"])
    if doc.get("blade_offset_mm", 0):
        base = geo.apply_offset(base, doc["blade_offset_mm"])

    cut_polys: List[List[List[float]]] = []
    engrave_polys: List[List[List[float]]] = []
    if base:
        cut_polys.append(base)

    for el in doc.get("elements", []):
        layer = el.get("layer", "ENGRAVE")
        target = cut_polys if layer == "CUT" else engrave_polys
        for poly in el.get("polylines", []):
            if len(poly) >= 2:
                target.append(poly)

    return base, cut_polys, engrave_polys


@api_router.get("/projects/{project_id}/preview")
async def preview_project(project_id: str):
    doc = await get_project_doc(project_id)
    base, cut_polys, engrave_polys = _compute_final(doc)
    bb = geo.bbox_mm(base)
    return {
        "cut": cut_polys,
        "engrave": engrave_polys,
        "bbox": bb,
        "perimeter_mm": geo.perimeter_mm(base),
        "cut_count": len(cut_polys),
        "engrave_count": len(engrave_polys),
    }


@api_router.post("/projects/{project_id}/export")
async def export_project(project_id: str):
    doc = await get_project_doc(project_id)
    _, cut_polys, engrave_polys = _compute_final(doc)
    if not cut_polys and not engrave_polys:
        raise HTTPException(status_code=422, detail="Nessuna geometria da esportare")
    dxf_bytes = await run_in_threadpool(build_dxf, cut_polys, engrave_polys)
    dpath = f"{store.APP_NAME}/dxf/{project_id}/{uuid.uuid4()}.dxf"
    await run_in_threadpool(store.put_object, dpath, dxf_bytes, "application/dxf")
    await db.projects.update_one(
        {"_id": doc["_id"]},
        {"$set": {"dxf_path": dpath, "status": "exported", "updated_at": now_iso()}},
    )
    return {"dxf_path": dpath, "dxf_url": file_url(dpath), "size": len(dxf_bytes)}


# --------------------------------------------------------------------------
# File streaming (no auth in MVP -> works on web + native)
# --------------------------------------------------------------------------
@api_router.get("/files/{file_path:path}")
async def get_file(file_path: str):
    try:
        content, ctype = await run_in_threadpool(store.get_object, file_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("file fetch failed %s: %s", file_path, e)
        raise HTTPException(status_code=404, detail="File non trovato")
    headers = {}
    if file_path.endswith(".dxf"):
        headers["Content-Disposition"] = f'attachment; filename="{file_path.split("/")[-1]}"'
    return Response(content=content, media_type=ctype, headers=headers)


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    try:
        await run_in_threadpool(store.init_storage)
    except Exception as e:  # noqa: BLE001
        logger.error("Storage init failed at startup: %s", e)


@app.on_event("shutdown")
async def shutdown():
    client.close()
