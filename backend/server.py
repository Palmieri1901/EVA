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
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

import cv_pipeline as cv
import geometry_ops as geo
import stitch as stitcher
import storage_client as store
import techsheet
import assembly
import nesting
import exporters
import photogram
import aruco_stitch
import boat_render
import vectorize as vec
from dxf_builder import build_dxf
from models import (
    Boat,
    BoatCreate,
    BoatUpdate,
    Element,
    MarkerInfo,
    Project,
    ProjectCreate,
    ProjectUpdate,
    Quality,
    SvgRequest,
    TextRequest,
    TrackRequest,
    FillRequest,
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
# Boats (a boat/project groups one or more mat pieces)
# --------------------------------------------------------------------------
async def get_boat_doc(boat_id: str) -> dict:
    try:
        oid = ObjectId(boat_id)
    except Exception:
        raise HTTPException(status_code=400, detail="ID imbarcazione non valido")
    doc = await db.boats.find_one({"_id": oid, "deleted": {"$ne": True}})
    if not doc:
        raise HTTPException(status_code=404, detail="Imbarcazione non trovata")
    return doc


async def _boat_pieces(boat_id: str) -> List[dict]:
    return await db.projects.find(
        {"boat_id": boat_id, "deleted": {"$ne": True}}
    ).sort("created_at", 1).to_list(500)


@api_router.post("/boats")
async def create_boat(payload: BoatCreate):
    boat = Boat(**payload.model_dump())
    doc = boat.model_dump(by_alias=True, exclude={"id"})
    res = await db.boats.insert_one(doc)
    saved = await db.boats.find_one({"_id": res.inserted_id})
    s = serialize(saved)
    s["piece_count"] = 0
    s["thumb_url"] = None
    return s


@api_router.get("/boats")
async def list_boats():
    docs = await db.boats.find({"deleted": {"$ne": True}}).sort("updated_at", -1).to_list(500)
    out = []
    for d in docs:
        s = serialize(d)
        pieces = await _boat_pieces(s["id"])
        s["piece_count"] = len(pieces)
        thumb = None
        for p in pieces:
            thumb = p.get("rectified_path") or p.get("photo_path")
            if thumb:
                break
        s["thumb_url"] = file_url(thumb)
        out.append(s)
    return out


@api_router.get("/boats/{boat_id}")
async def get_boat(boat_id: str):
    doc = await get_boat_doc(boat_id)
    s = serialize(doc)
    pieces = await _boat_pieces(boat_id)
    out_pieces = []
    for p in pieces:
        ps = serialize(p)
        ps["photo_url"] = file_url(p.get("photo_path"))
        ps["rectified_url"] = file_url(p.get("rectified_path"))
        out_pieces.append(ps)
    s["pieces"] = out_pieces
    return s


@api_router.get("/boats/{boat_id}/render.{fmt}")
async def boat_render_endpoint(boat_id: str, fmt: str):
    if fmt not in ("png", "pdf"):
        raise HTTPException(status_code=400, detail="Formato non supportato")
    boat = await get_boat_doc(boat_id)
    pieces = await _boat_pieces(boat_id)
    pieces = [serialize(p) for p in pieces if p.get("contour_mm")]
    if not pieces:
        raise HTTPException(status_code=422, detail="Nessun pezzo con contorno da comporre")
    data = await run_in_threadpool(boat_render.render, pieces, boat.get("name", "IMBARCAZIONE"), fmt)
    mime = "application/pdf" if fmt == "pdf" else "image/png"
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": f'inline; filename="rendering_barca.{fmt}"'})


@api_router.patch("/boats/{boat_id}")
async def update_boat(boat_id: str, payload: BoatUpdate):
    doc = await get_boat_doc(boat_id)
    updates = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    updates["updated_at"] = now_iso()
    await db.boats.update_one({"_id": doc["_id"]}, {"$set": updates})
    saved = await db.boats.find_one({"_id": doc["_id"]})
    return serialize(saved)


@api_router.delete("/boats/{boat_id}")
async def delete_boat(boat_id: str):
    doc = await get_boat_doc(boat_id)
    await db.boats.update_one({"_id": doc["_id"]}, {"$set": {"deleted": True, "updated_at": now_iso()}})
    await db.projects.update_many({"boat_id": boat_id}, {"$set": {"deleted": True, "updated_at": now_iso()}})
    return {"ok": True}


def _boat_nested(pieces: List[dict]) -> dict:
    items = []
    total_area = 0.0
    for p in pieces:
        base, cut_polys, engrave_polys = _compute_final(p)
        if not cut_polys:
            continue
        total_area += geo.area_m2(base)
        items.append({
            "id": str(p["_id"]),
            "name": p.get("piece_name") or p.get("name") or "Pezzo",
            "cut": cut_polys,
            "engrave": engrave_polys,
        })
    nested = nesting.nest_pieces(items)
    nested["total_area_m2"] = total_area
    return nested


@api_router.get("/boats/{boat_id}/assembly")
async def boat_assembly(boat_id: str):
    doc = await get_boat_doc(boat_id)
    pieces = await _boat_pieces(boat_id)
    nested = await run_in_threadpool(_boat_nested, pieces)
    if nested.get("count", 0) == 0:
        raise HTTPException(status_code=422, detail="Nessun pezzo pronto: elabora e definisci i contorni dei pezzi")
    from datetime import datetime, timezone
    meta = {
        "boat_name": doc.get("name", "IMBARCAZIONE"),
        "date": datetime.now(timezone.utc).strftime("%d/%m/%y"),
        "total_area_m2": nested.get("total_area_m2", 0.0),
    }
    pdf = await run_in_threadpool(assembly.render_assembly, nested, meta)
    spath = f"{store.APP_NAME}/assembly/{boat_id}/{uuid.uuid4()}.pdf"
    await run_in_threadpool(store.put_object, spath, pdf, "application/pdf")
    return {
        "sheet_url": file_url(spath), "size": len(pdf), "count": nested["count"],
        "overflow": nested.get("overflow", False), "total_area_m2": nested.get("total_area_m2", 0.0),
    }


@api_router.post("/boats/{boat_id}/nested-dxf")
async def boat_nested_dxf(boat_id: str):
    await get_boat_doc(boat_id)
    pieces = await _boat_pieces(boat_id)
    nested = await run_in_threadpool(_boat_nested, pieces)
    if nested.get("count", 0) == 0:
        raise HTTPException(status_code=422, detail="Nessun pezzo pronto da annidare")
    dxf_bytes = await run_in_threadpool(build_dxf, nested["cut"], nested["engrave"])
    dpath = f"{store.APP_NAME}/dxf/{boat_id}/nested_{uuid.uuid4()}.dxf"
    await run_in_threadpool(store.put_object, dpath, dxf_bytes, "application/dxf")
    return {
        "dxf_url": file_url(dpath), "size": len(dxf_bytes), "count": nested["count"],
        "overflow": nested.get("overflow", False),
    }


# --------------------------------------------------------------------------
# Projects CRUD
# --------------------------------------------------------------------------
@api_router.post("/projects")
async def create_project(payload: ProjectCreate):
    proj = Project(**payload.model_dump())
    doc = proj.model_dump(by_alias=True, exclude={"id"})
    res = await db.projects.insert_one(doc)
    if proj.boat_id:
        try:
            await db.boats.update_one({"_id": ObjectId(proj.boat_id)}, {"$set": {"updated_at": now_iso()}})
        except Exception:  # noqa: BLE001
            pass
    saved = await db.projects.find_one({"_id": res.inserted_id})
    return serialize(saved)


@api_router.get("/projects")
async def list_projects(boat_id: Optional[str] = None):
    query: dict = {"deleted": {"$ne": True}}
    if boat_id:
        query["boat_id"] = boat_id
    docs = await db.projects.find(query).sort("created_at", 1).to_list(500)
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
    bgr = cv.imdecode_exif(img_bytes)
    if bgr is None:
        raise ValueError("Immagine non decodificabile")

    bg = project["background_mode"]
    raw_markers = cv.detect_markers(bgr, bg)
    corners, center = cv.order_markers(raw_markers)

    messages: List[str] = []
    markers_out: List[dict] = []
    sharp = cv.sharpness(bgr)

    if len(corners) < 4:
        # No corner dots/markers found -> AUTO tape mode: detect the coloured tape,
        # take its 4 outer corners as the reference rectangle (known interasse) and
        # extract the mat outline it delimits. Always keep the photo visible.
        w, h = project["ref_width_mm"], project["ref_height_mm"]
        tape_pref = (project.get("tape_color") or project.get("background_mode") or "auto")
        color = tape_pref if tape_pref not in ("auto", "", None) and cv._tape_score(bgr, tape_pref) > 0 else cv.best_tape_color(bgr)
        quad = None
        used_dots = False
        if color:
            quad = cv.detect_tape_corner_dots(bgr, color)  # white pen marks on the tape
            if quad is not None:
                used_dots = True
            else:
                quad = cv.detect_tape_quad(bgr, color)     # fall back to tape corners
        if quad is not None:
            ref = {"type": "rect", "points": quad.tolist(), "width_mm": w, "height_mm": h}
            try:
                res = photogram.rectify_and_extract(bgr, ref, color, project["cut_side"])
            except Exception as e:  # noqa: BLE001
                res = None
                logger.warning("auto-tape rectify failed: %s", e)
            if res is not None:
                ref_src = "punti bianchi agli angoli" if used_dots else "angoli del nastro"
                messages.append(
                    f"Nastro '{color}' rilevato automaticamente ({ref_src}): contorno sul nastro. "
                    "Per la massima precisione usa FOTO + RIFERIMENTO toccando i 4 angoli."
                )
                quality = Quality(
                    markers_found=0, sharpness=sharp, tape_detected=res.get("detected", False),
                    valid=bool(res.get("detected")), messages=messages,
                )
                return {
                    "markers": [],
                    "quality": quality.model_dump(),
                    "contour_mm": res["contour_mm"],
                    "rectified": {"bytes": res.get("rectified_bytes"), "w": res["w_px"],
                                  "h": res["h_px"], "mm_per_px": res["mm_per_px"]},
                }
        # No tape either -> keep the ORIGINAL photo visible + provisional rectangle so
        # the user can trace over it manually (never a blank grey canvas).
        messages.append("Nessun bollino né nastro rilevato: foto mostrata, correggi il contorno a mano.")
        long_edge = max(w, h)
        mm_per_px = max(long_edge / cv.MAX_RECTIFIED_PX, cv.MIN_MM_PER_PX)
        ih, iw = bgr.shape[:2]
        contour = [[0.0, 0.0], [iw * mm_per_px, 0.0], [iw * mm_per_px, ih * mm_per_px], [0.0, ih * mm_per_px]]
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
        quality = Quality(
            markers_found=len(raw_markers), sharpness=sharp, tape_detected=False, valid=False,
            messages=messages,
        )
        return {
            "markers": [],
            "quality": quality.model_dump(),
            "contour_mm": contour,
            "rectified": {"bytes": buf.tobytes() if ok else None, "w": iw, "h": ih, "mm_per_px": mm_per_px},
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
# Multi-shot capture & stitching (large areas up to ~2x3 m)
# --------------------------------------------------------------------------
def _detect_shot_markers(img_bytes: bytes, bg: str) -> dict:
    bgr = cv.imdecode_exif(img_bytes)
    if bgr is None:
        raise ValueError("Immagine non decodificabile")
    markers = cv.detect_markers(bgr, bg)
    return {"markers_img": [[m["x"], m["y"]] for m in markers], "n_markers": len(markers)}


def shots_with_urls(shots: list) -> list:
    out = []
    for s in shots or []:
        s2 = dict(s)
        s2["photo_url"] = file_url(s.get("photo_path"))
        out.append(s2)
    return out


@api_router.post("/projects/{project_id}/shots")
async def add_shot(project_id: str, file: UploadFile = File(...)):
    doc = await get_project_doc(project_id)
    data = await file.read()
    shot_id = uuid.uuid4().hex
    path = f"{store.APP_NAME}/shots/{project_id}/{shot_id}.jpg"
    await run_in_threadpool(store.put_object, path, data, file.content_type or "image/jpeg")
    try:
        det = await run_in_threadpool(_detect_shot_markers, data, doc["background_mode"])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    shots = doc.get("shots") or []
    shot = {
        "id": shot_id,
        "order": len(shots),
        "photo_path": path,
        "n_markers": det["n_markers"],
        "markers_img": det["markers_img"],
        "anchored": False,
    }
    shots.append(shot)
    await db.projects.update_one(
        {"_id": doc["_id"]},
        {"$set": {"shots": shots, "capture_mode": "multi", "status": "captured", "updated_at": now_iso()}},
    )
    shot_out = dict(shot)
    shot_out["photo_url"] = file_url(path)
    return shot_out


@api_router.get("/projects/{project_id}/shots")
async def list_shots(project_id: str):
    doc = await get_project_doc(project_id)
    return shots_with_urls(doc.get("shots"))


@api_router.delete("/projects/{project_id}/shots/{shot_id}")
async def delete_shot(project_id: str, shot_id: str):
    doc = await get_project_doc(project_id)
    shots = [s for s in (doc.get("shots") or []) if s.get("id") != shot_id]
    for i, s in enumerate(shots):
        s["order"] = i
    await db.projects.update_one({"_id": doc["_id"]}, {"$set": {"shots": shots, "updated_at": now_iso()}})
    return {"ok": True, "count": len(shots)}


def _run_stitch(project: dict, shot_imgs: list) -> dict:
    """shot_imgs: list of (shot_dict, img_bytes)."""
    shots = []
    for sd, img_bytes in shot_imgs:
        bgr = cv.imdecode_exif(img_bytes)
        if bgr is None:
            continue
        shots.append({"id": sd["id"], "order": sd.get("order", 0), "bgr": bgr})
    if not shots:
        return {"error": "Nessuno scatto valido da unire."}
    return stitcher.stitch(project, shots)


@api_router.post("/projects/{project_id}/stitch")
async def stitch_project(project_id: str):
    doc = await get_project_doc(project_id)
    shots = doc.get("shots") or []
    if not shots:
        raise HTTPException(status_code=400, detail="Aggiungi almeno uno scatto")

    shot_imgs = []
    for sd in shots:
        try:
            img_bytes, _ = await run_in_threadpool(store.get_object, sd["photo_path"])
            shot_imgs.append((sd, img_bytes))
        except Exception:  # noqa: BLE001
            continue

    result = await run_in_threadpool(_run_stitch, doc, shot_imgs)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])

    updates = {
        "contour_mm": result["contour_mm"],
        "mm_per_px": result["mm_per_px"],
        "rectified_w_px": result["w_px"],
        "rectified_h_px": result["h_px"],
        "status": "processed",
        "updated_at": now_iso(),
    }
    if result.get("preview_bytes"):
        rpath = f"{store.APP_NAME}/rectified/{project_id}/{uuid.uuid4()}.jpg"
        await run_in_threadpool(store.put_object, rpath, result["preview_bytes"], "image/jpeg")
        updates["rectified_path"] = rpath

    anchored = set(result["anchored_ids"])
    for s in shots:
        s["anchored"] = s["id"] in anchored
    updates["shots"] = shots

    await db.projects.update_one({"_id": doc["_id"]}, {"$set": updates})
    return {
        "anchored": result["anchored_ids"],
        "unanchored": result["unanchored_ids"],
        "tape_detected": result["tape_detected"],
        "n_global_markers": result["n_global_markers"],
        "plane_w_mm": result["plane_w_mm"],
        "plane_h_mm": result["plane_h_mm"],
        "rectified_url": file_url(updates.get("rectified_path")),
        "contour_points": len(result["contour_mm"]),
    }



# --------------------------------------------------------------------------
# Markerless photogrammetry capture for flat pieces (many angled photos)
# --------------------------------------------------------------------------
def _pg_with_urls(shots: list) -> list:
    out = []
    for s in shots or []:
        s2 = dict(s)
        s2["photo_url"] = file_url(s.get("photo_path"))
        out.append(s2)
    return out


@api_router.post("/projects/{project_id}/photogram/photos")
async def pg_add_photo(project_id: str, file: UploadFile = File(...)):
    doc = await get_project_doc(project_id)
    data = await file.read()
    pid = uuid.uuid4().hex
    path = f"{store.APP_NAME}/photogram/{project_id}/{pid}.jpg"
    await run_in_threadpool(store.put_object, path, data, file.content_type or "image/jpeg")
    shots = doc.get("photogram_shots") or []
    shot = {"id": pid, "order": len(shots), "photo_path": path}
    shots.append(shot)
    await db.projects.update_one(
        {"_id": doc["_id"]},
        {"$set": {"photogram_shots": shots, "capture_mode": "photogram",
                  "status": "captured", "updated_at": now_iso()}},
    )
    out = dict(shot)
    out["photo_url"] = file_url(path)
    return out


@api_router.get("/projects/{project_id}/photogram/photos")
async def pg_list_photos(project_id: str):
    doc = await get_project_doc(project_id)
    return _pg_with_urls(doc.get("photogram_shots"))


@api_router.delete("/projects/{project_id}/photogram/photos/{photo_id}")
async def pg_delete_photo(project_id: str, photo_id: str):
    doc = await get_project_doc(project_id)
    shots = [s for s in (doc.get("photogram_shots") or []) if s.get("id") != photo_id]
    for i, s in enumerate(shots):
        s["order"] = i
    await db.projects.update_one({"_id": doc["_id"]}, {"$set": {"photogram_shots": shots, "updated_at": now_iso()}})
    return {"ok": True, "count": len(shots)}


def _run_pg_stitch(imgs_bytes: list) -> dict:
    mosaic, warning = photogram.prepare_image(imgs_bytes)
    if mosaic is None:
        return {"error": warning}
    ok, buf = cv2.imencode(".jpg", mosaic, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return {"bytes": buf.tobytes() if ok else None,
            "w": mosaic.shape[1], "h": mosaic.shape[0], "warning": warning}


@api_router.post("/projects/{project_id}/photogram/stitch")
async def pg_stitch(project_id: str):
    doc = await get_project_doc(project_id)
    shots = doc.get("photogram_shots") or []
    if not shots:
        raise HTTPException(status_code=400, detail="Aggiungi almeno una foto")
    imgs_bytes = []
    for s in shots:
        try:
            b, _ = await run_in_threadpool(store.get_object, s["photo_path"])
            imgs_bytes.append(b)
        except Exception:  # noqa: BLE001
            continue
    result = await run_in_threadpool(_run_pg_stitch, imgs_bytes)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    mpath = f"{store.APP_NAME}/photogram/{project_id}/mosaic_{uuid.uuid4().hex}.jpg"
    await run_in_threadpool(store.put_object, mpath, result["bytes"], "image/jpeg")
    await db.projects.update_one(
        {"_id": doc["_id"]},
        {"$set": {"photogram_mosaic_path": mpath, "photogram_mosaic_w": result["w"],
                  "photogram_mosaic_h": result["h"], "updated_at": now_iso()}},
    )
    return {"mosaic_url": file_url(mpath), "w": result["w"], "h": result["h"],
            "warning": result.get("warning")}


def _run_pg_extract(mosaic_bytes: bytes, reference: dict,
                    background_mode: str = "blue_on_white", cut_side: str = "inner") -> dict:
    mosaic = cv.imdecode_exif(mosaic_bytes)
    if mosaic is None:
        raise ValueError("Mosaico non decodificabile")
    return photogram.rectify_and_extract(mosaic, reference, background_mode, cut_side)


@api_router.post("/projects/{project_id}/photogram/extract")
async def pg_extract(project_id: str, body: dict):
    doc = await get_project_doc(project_id)
    mpath = doc.get("photogram_mosaic_path")
    if not mpath:
        raise HTTPException(status_code=400, detail="Prima unisci le foto")
    mosaic_bytes, _ = await run_in_threadpool(store.get_object, mpath)
    bg = doc.get("tape_color") or doc.get("background_mode") or "auto"
    cut = doc.get("cut_side") or "inner"
    try:
        res = await run_in_threadpool(_run_pg_extract, mosaic_bytes, body or {}, bg, cut)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    updates = {
        "contour_mm": res["contour_mm"],
        "mm_per_px": res["mm_per_px"],
        "rectified_w_px": res["w_px"],
        "rectified_h_px": res["h_px"],
        "status": "processed",
        "updated_at": now_iso(),
    }
    if res.get("rectified_bytes"):
        rpath = f"{store.APP_NAME}/rectified/{project_id}/{uuid.uuid4().hex}.jpg"
        await run_in_threadpool(store.put_object, rpath, res["rectified_bytes"], "image/jpeg")
        updates["rectified_path"] = rpath
    await db.projects.update_one({"_id": doc["_id"]}, {"$set": updates})
    saved = await db.projects.find_one({"_id": doc["_id"]})
    s = serialize(saved)
    s["rectified_url"] = file_url(saved.get("rectified_path"))
    s["detected"] = res.get("detected", False)
    return s


def _run_pg_aruco(imgs_bytes: list, marker_mm: float) -> dict:
    imgs = []
    for b in imgs_bytes:
        im = cv.imdecode_exif(b)
        if im is not None:
            imgs.append(im)
    return aruco_stitch.process(imgs, marker_mm)


@api_router.post("/projects/{project_id}/photogram/aruco")
async def pg_aruco(project_id: str, body: dict):
    doc = await get_project_doc(project_id)
    shots = doc.get("photogram_shots") or []
    if not shots:
        raise HTTPException(status_code=400, detail="Aggiungi almeno una foto")
    marker_mm = float((body or {}).get("marker_mm") or 0)
    imgs_bytes = []
    for s in shots:
        try:
            b, _ = await run_in_threadpool(store.get_object, s["photo_path"])
            imgs_bytes.append(b)
        except Exception:  # noqa: BLE001
            continue
    try:
        res = await run_in_threadpool(_run_pg_aruco, imgs_bytes, marker_mm)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    updates = {
        "contour_mm": res["contour_mm"],
        "mm_per_px": res["mm_per_px"],
        "rectified_w_px": res["w_px"],
        "rectified_h_px": res["h_px"],
        "status": "processed",
        "updated_at": now_iso(),
    }
    if res.get("rectified_bytes"):
        rpath = f"{store.APP_NAME}/rectified/{project_id}/{uuid.uuid4().hex}.jpg"
        await run_in_threadpool(store.put_object, rpath, res["rectified_bytes"], "image/jpeg")
        updates["rectified_path"] = rpath
    await db.projects.update_one({"_id": doc["_id"]}, {"$set": updates})
    saved = await db.projects.find_one({"_id": doc["_id"]})
    s = serialize(saved)
    s["rectified_url"] = file_url(saved.get("rectified_path"))
    s["detected"] = res.get("detected", False)
    s["photos_used"] = res.get("photos_used", 0)
    s["markers_found"] = res.get("markers_found", 0)
    return s


@api_router.get("/aruco/sheet.pdf")
async def aruco_sheet(mm: float = 40.0):
    pdf = await run_in_threadpool(aruco_stitch.make_sheet_pdf, float(mm), 8)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="marker_aruco.pdf"'})


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


@api_router.post("/geometry/fill")
async def geometry_fill(req: FillRequest):
    if len(req.contour) < 3:
        raise HTTPException(status_code=422, detail="Contorno non valido per il riempimento")
    try:
        res = await run_in_threadpool(
            geo.fill_pattern, req.contour, req.spacing_mm, req.angle_deg, req.pattern,
            req.style, req.border_mm, req.groove_mm, req.auto_angle, req.board_length_mm,
            req.exclude, req.exclude_margin_mm, req.diamond_height_mm,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("fill_pattern failed (exclude=%d, margin=%s, style=%s, groove=%s)",
                         len(req.exclude or []), req.exclude_margin_mm, req.style, req.groove_mm)
        raise HTTPException(status_code=422, detail=f"Riempimento non riuscito: {e}")
    polylines = (res.get("border") or []) + (res.get("pattern") or [])
    if not polylines:
        raise HTTPException(status_code=422, detail="Nessun riempimento generato (area troppo piccola?)")
    return {
        "polylines": polylines,
        "border_count": len(res.get("border") or []),
        "line_count": len(res.get("pattern") or []),
        "angle_used": res.get("angle_used", req.angle_deg),
    }


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


TIPO_LABEL = {"diamond": "Diamante", "cross": "Incrociato", "lines": "Listelli"}


@api_router.post("/projects/{project_id}/techsheet")
async def techsheet_project(project_id: str, body: dict = None):
    body = body or {}
    doc = await get_project_doc(project_id)
    base, cut_polys, engrave_polys = _compute_final(doc)
    if not cut_polys:
        raise HTTPException(status_code=422, detail="Nessuna dima da riportare in scheda")

    # tipo derived from first fill element pattern
    tipo = "—"
    for el in doc.get("elements", []):
        if el.get("type") == "fill":
            tipo = TIPO_LABEL.get((el.get("params") or {}).get("pattern"), "Listelli")
            break

    from datetime import datetime, timezone
    meta = {
        "company": body.get("company") or "FOAM TEAK",
        "date": body.get("date") or datetime.now(timezone.utc).strftime("%d/%m/%y"),
        "client": body.get("client") or doc.get("name", ""),
        "model": body.get("model") or "",
        "tipo": body.get("tipo") or tipo,
        "color": body.get("color") or "",
        "area_m2": geo.area_m2(base),
    }
    pdf = await run_in_threadpool(techsheet.render_sheet, cut_polys, engrave_polys, meta)
    spath = f"{store.APP_NAME}/techsheet/{project_id}/{uuid.uuid4()}.pdf"
    await run_in_threadpool(store.put_object, spath, pdf, "application/pdf")
    return {"sheet_url": file_url(spath), "size": len(pdf), "area_m2": meta["area_m2"]}


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


@api_router.post("/projects/{project_id}/export/{fmt}")
async def export_project_format(project_id: str, fmt: str, body: dict = None):
    doc = await get_project_doc(project_id)
    _, cut_polys, engrave_polys = _compute_final(doc)
    if (body or {}).get("cut_only"):
        engrave_polys = []
    if not cut_polys and not engrave_polys:
        raise HTTPException(status_code=422, detail="Nessuna geometria da esportare")
    try:
        data, mime, ext = await run_in_threadpool(
            exporters.render, fmt, cut_polys, engrave_polys, (body or {}).get("gcode")
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    path = f"{store.APP_NAME}/exports/{project_id}/{uuid.uuid4()}.{ext}"
    await run_in_threadpool(store.put_object, path, data, mime)
    if fmt == "dxf":
        await db.projects.update_one(
            {"_id": doc["_id"]}, {"$set": {"dxf_path": path, "status": "exported", "updated_at": now_iso()}}
        )
    return {"url": file_url(path), "size": len(data), "format": fmt, "ext": ext}


@api_router.post("/boats/{boat_id}/export/{fmt}")
async def export_boat_format(boat_id: str, fmt: str, body: dict = None):
    await get_boat_doc(boat_id)
    pieces = await _boat_pieces(boat_id)
    nested = await run_in_threadpool(_boat_nested, pieces)
    if nested.get("count", 0) == 0:
        raise HTTPException(status_code=422, detail="Nessun pezzo pronto da esportare")
    cut_polys = nested["cut"]
    engrave_polys = [] if (body or {}).get("cut_only") else nested["engrave"]
    try:
        data, mime, ext = await run_in_threadpool(
            exporters.render, fmt, cut_polys, engrave_polys, (body or {}).get("gcode")
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    path = f"{store.APP_NAME}/exports/{boat_id}/nested_{uuid.uuid4()}.{ext}"
    await run_in_threadpool(store.put_object, path, data, mime)
    return {
        "url": file_url(path), "size": len(data), "format": fmt, "ext": ext,
        "count": nested["count"], "overflow": nested.get("overflow", False),
    }


# --------------------------------------------------------------------------
# Vectorize a logo / lettering from a photo -> polylines + DXF
# --------------------------------------------------------------------------
@api_router.post("/vectorize")
async def vectorize_photo(
    file: UploadFile = File(...),
    threshold: int = Form(-1),
    invert: bool = Form(True),
    target_width_mm: float = Form(200.0),
    simplify: float = Form(0.005),
    subject: str = Form("logo"),
    internals: bool = Form(False),
    roi: str = Form(""),
    clean: bool = Form(False),
):
    data = await file.read()
    roi_obj = None
    if roi:
        try:
            import json as _json
            roi_obj = _json.loads(roi)
        except Exception:  # noqa: BLE001
            roi_obj = None
    try:
        res = await run_in_threadpool(
            vec.vectorize_image, data, threshold, invert, target_width_mm, simplify, 0.0008, subject, internals, True, roi_obj, clean
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    uid = uuid.uuid4()
    preview_url = None
    if res.get("preview"):
        ppath = f"{store.APP_NAME}/vectorize/{uid}_preview.png"
        await run_in_threadpool(store.put_object, ppath, res["preview"], "image/png")
        preview_url = file_url(ppath)

    dxf_bytes = await run_in_threadpool(build_dxf, res["polylines"], [])
    dpath = f"{store.APP_NAME}/vectorize/{uid}.dxf"
    await run_in_threadpool(store.put_object, dpath, dxf_bytes, "application/dxf")

    return {
        "polylines": res["polylines"],
        "width_mm": res["width_mm"],
        "height_mm": res["height_mm"],
        "count": res["count"],
        "preview_url": preview_url,
        "dxf_url": file_url(dpath),
    }


@api_router.post("/projects/{project_id}/elements")
async def add_element(project_id: str, payload: dict):
    doc = await get_project_doc(project_id)
    element = {
        "id": payload.get("id") or str(uuid.uuid4()),
        "type": payload.get("type", "polyline"),
        "layer": payload.get("layer", "ENGRAVE"),
        "polylines": payload.get("polylines", []),
        "params": payload.get("params", {}),
    }
    elements = list(doc.get("elements") or [])
    elements.append(element)
    await db.projects.update_one(
        {"_id": doc["_id"]},
        {"$set": {"elements": elements, "status": "edited", "updated_at": now_iso()}},
    )
    saved = await db.projects.find_one({"_id": doc["_id"]})
    return serialize(saved)



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
    if file_path.rsplit(".", 1)[-1].lower() in ("dxf", "pdf", "svg", "nc", "png"):
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
