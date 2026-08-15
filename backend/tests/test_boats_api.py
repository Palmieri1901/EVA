"""Tests for the Boat (project group) feature - boats CRUD, pieces under
boat, assembly PDF and nested DXF endpoints."""
from __future__ import annotations

import os
import pytest
import requests

BASE_URL = os.environ["EXPO_PUBLIC_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    yield sess
    sess.close()


@pytest.fixture(scope="module")
def boat_id(s):
    r = s.post(f"{API}/boats", json={"name": "TEST_boat_feature"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "id" in j
    assert j["name"] == "TEST_boat_feature"
    assert j["piece_count"] == 0
    assert j["thumb_url"] is None
    bid = j["id"]
    yield bid
    # cleanup
    s.delete(f"{API}/boats/{bid}")


# ---------- Boats CRUD ----------
class TestBoatsCRUD:
    def test_list_contains_new_boat(self, s, boat_id):
        r = s.get(f"{API}/boats")
        assert r.status_code == 200
        boats = r.json()
        ids = [b["id"] for b in boats]
        assert boat_id in ids
        b = next(b for b in boats if b["id"] == boat_id)
        assert "piece_count" in b
        assert "thumb_url" in b

    def test_get_boat_empty_pieces(self, s, boat_id):
        r = s.get(f"{API}/boats/{boat_id}")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["id"] == boat_id
        assert isinstance(j.get("pieces"), list)
        assert len(j["pieces"]) == 0

    def test_patch_boat_rename(self, s, boat_id):
        r = s.patch(f"{API}/boats/{boat_id}", json={"name": "TEST_boat_renamed"})
        assert r.status_code == 200, r.text
        # GET to verify persistence
        g = s.get(f"{API}/boats/{boat_id}").json()
        assert g["name"] == "TEST_boat_renamed"

    def test_get_boat_invalid_id(self, s):
        r = s.get(f"{API}/boats/not-an-oid")
        assert r.status_code == 400

    def test_get_boat_missing(self, s):
        r = s.get(f"{API}/boats/507f1f77bcf86cd799439011")
        assert r.status_code == 404


# ---------- Pieces under a boat + assembly + nested DXF ----------
class TestBoatPiecesAndAssembly:
    """Create boat + 2 pieces, PATCH contour_mm rectangle on each, then call
    assembly & nested-dxf endpoints. Also tests the empty-boat 422 branch."""

    piece_ids: list = []

    def test_00_empty_boat_assembly_returns_422(self, s):
        # Boat with 0 pieces must produce 422 for /assembly
        r = s.post(f"{API}/boats", json={"name": "TEST_empty_boat"})
        empty_id = r.json()["id"]
        try:
            g = s.get(f"{API}/boats/{empty_id}/assembly")
            assert g.status_code == 422, g.text
            # Also nested-dxf
            g2 = s.post(f"{API}/boats/{empty_id}/nested-dxf")
            assert g2.status_code == 422, g2.text
        finally:
            s.delete(f"{API}/boats/{empty_id}")

    def test_01_create_two_pieces(self, s, boat_id):
        for i, dims in enumerate([(600, 400), (500, 300)]):
            w, h = dims
            payload = {
                "name": f"TEST_piece_{i+1}",
                "piece_name": f"Pezzo {i+1}",
                "boat_id": boat_id,
                "ref_width_mm": w,
                "ref_height_mm": h,
            }
            r = s.post(f"{API}/projects", json=payload)
            assert r.status_code == 200, r.text
            j = r.json()
            assert j["boat_id"] == boat_id
            assert j["piece_name"] == f"Pezzo {i+1}"
            TestBoatPiecesAndAssembly.piece_ids.append(j["id"])
        assert len(TestBoatPiecesAndAssembly.piece_ids) == 2

    def test_02_filter_projects_by_boat_id(self, s, boat_id):
        r = s.get(f"{API}/projects", params={"boat_id": boat_id})
        assert r.status_code == 200
        pieces = r.json()
        assert len(pieces) == 2
        for p in pieces:
            assert p["boat_id"] == boat_id
            assert p["id"] in TestBoatPiecesAndAssembly.piece_ids

    def test_03_boat_get_returns_pieces_array(self, s, boat_id):
        r = s.get(f"{API}/boats/{boat_id}")
        j = r.json()
        assert len(j["pieces"]) == 2
        for p in j["pieces"]:
            assert p["boat_id"] == boat_id
            assert "piece_name" in p

    def test_04_boats_list_piece_count(self, s, boat_id):
        r = s.get(f"{API}/boats")
        b = next(x for x in r.json() if x["id"] == boat_id)
        assert b["piece_count"] == 2

    def test_05_assembly_before_contour_returns_422(self, s, boat_id):
        # Pieces have no contour_mm set yet -> should be 422
        r = s.get(f"{API}/boats/{boat_id}/assembly")
        assert r.status_code == 422, r.text

    def test_06_patch_contour_on_pieces(self, s):
        # PATCH each piece with a rectangular contour_mm
        rects = [
            [[0.0, 0.0], [600.0, 0.0], [600.0, 400.0], [0.0, 400.0]],
            [[0.0, 0.0], [500.0, 0.0], [500.0, 300.0], [0.0, 300.0]],
        ]
        for pid, poly in zip(TestBoatPiecesAndAssembly.piece_ids, rects):
            r = s.patch(f"{API}/projects/{pid}", json={"contour_mm": poly})
            assert r.status_code == 200, r.text
            g = s.get(f"{API}/projects/{pid}").json()
            assert len(g["contour_mm"]) == 4

    def test_07_boat_assembly_pdf(self, s, boat_id):
        r = s.get(f"{API}/boats/{boat_id}/assembly", timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["count"] == 2
        assert j["sheet_url"].startswith("/api/files/")
        assert j["sheet_url"].endswith(".pdf")
        assert j["size"] > 100
        assert "overflow" in j
        assert j["total_area_m2"] > 0.0
        # Fetch the PDF back
        fpath = j["sheet_url"].replace("/api/files/", "")
        fr = s.get(f"{API}/files/{fpath}")
        assert fr.status_code == 200
        assert fr.content[:4] == b"%PDF"

    def test_08_boat_nested_dxf(self, s, boat_id):
        r = s.post(f"{API}/boats/{boat_id}/nested-dxf", timeout=60)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["count"] == 2
        assert j["dxf_url"].endswith(".dxf")
        assert j["size"] > 0
        assert "overflow" in j
        fpath = j["dxf_url"].replace("/api/files/", "")
        fr = s.get(f"{API}/files/{fpath}")
        assert fr.status_code == 200
        # DXF is ASCII, starts with a section header
        head = fr.content[:200].decode("ascii", errors="ignore").upper()
        assert "SECTION" in head or "0" in head

    def test_09_cascade_soft_delete_pieces(self, s):
        # Create a temp boat with a piece, delete boat, ensure piece is soft-deleted too
        rb = s.post(f"{API}/boats", json={"name": "TEST_cascade_boat"})
        bid = rb.json()["id"]
        rp = s.post(
            f"{API}/projects",
            json={"name": "TEST_cascade_piece", "piece_name": "P1", "boat_id": bid},
        )
        pid = rp.json()["id"]
        # Delete boat
        rd = s.delete(f"{API}/boats/{bid}")
        assert rd.status_code == 200 and rd.json()["ok"] is True
        # Boat should now 404
        assert s.get(f"{API}/boats/{bid}").status_code == 404
        # Piece should also be soft-deleted -> 404 and not in list
        assert s.get(f"{API}/projects/{pid}").status_code == 404
        # Not in projects list filtered by that boat
        r = s.get(f"{API}/projects", params={"boat_id": bid})
        assert all(p["id"] != pid for p in r.json())

    def test_10_cleanup_pieces(self, s):
        # Soft delete the two test pieces
        for pid in TestBoatPiecesAndAssembly.piece_ids:
            s.delete(f"{API}/projects/{pid}")
