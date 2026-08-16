#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: |
  EVA Boat Mat Digitizer. New feature: a project (boat) contains one or more mat pieces.
  Each piece keeps the existing single-mat flow (photo -> editor -> texture -> DXF).
  Need: boat grouping with named pieces, an A4 panoramic PDF with all pieces auto-arranged
  (nested), and a single EVA sheet (900x2400 mm) DXF nesting all pieces (plus single-piece DXF).

backend:
  - task: "Boat CRUD (create/list/get/patch/delete) + pieces grouping via boat_id"
    implemented: true
    working: true
    file: "backend/server.py, backend/models.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Added boats collection + endpoints. Pieces are projects with boat_id + piece_name. Verified via curl: create boat, create 2 pieces, get boat returns pieces."
  - task: "Nesting + assembled A4 PDF (/boats/{id}/assembly) on EVA sheet 900x2400"
    implemented: true
    working: true
    file: "backend/nesting.py, backend/assembly.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Shelf nesting bbox-based. PDF verified via analyze tool: title, sheet 900x2400, both pieces labeled with names+sizes, total area."
  - task: "Nested single-sheet DXF (/boats/{id}/nested-dxf)"
    implemented: true
    working: true
    file: "backend/nesting.py, backend/dxf_builder.py, backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Combines all pieces cut+engrave translated into sheet slots. Verified 15KB DXF for 2 pieces."

frontend:
  - task: "Home lists boats + create-boat modal"
    implemented: true
    working: true
    file: "frontend/app/index.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Screenshot verified boat list + NUOVO PROGETTO."
  - task: "Boat detail screen: piece list, add piece, assembly PDF, nested DXF"
    implemented: true
    working: true
    file: "frontend/app/boat/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: true
        -agent: "main"
        -comment: "Screenshot verified pieces list + PDF ASSEMBLATO + DXF FOGLIO UNICO + AGGIUNGI PEZZO buttons."
  - task: "New piece form under boat (piece_name + boat_id)"
    implemented: true
    working: "NA"
    file: "frontend/app/new-project.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
        -working: "NA"
        -agent: "main"
        -comment: "Repurposed new-project to create a piece under a boat. Not yet UI-tested end-to-end (camera step needs device)."

metadata:
  created_by: "main_agent"
  version: "1.1"
  test_sequence: 1
  run_ui: false

test_plan:
  current_focus:
    - "Boat CRUD (create/list/get/patch/delete) + pieces grouping via boat_id"
    - "Nesting + assembled A4 PDF (/boats/{id}/assembly) on EVA sheet 900x2400"
    - "Nested single-sheet DXF (/boats/{id}/nested-dxf)"
    - "Home lists boats + create-boat modal"
    - "Boat detail screen: piece list, add piece, assembly PDF, nested DXF"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    -agent: "main"
    -message: |
      NEW ROUND — multi-format export + laser machine mode + photo vectorization.
      Please test BACKEND thoroughly:
      1) POST /api/projects/{id}/export/{fmt} for fmt in dxf,svg,pdf,png,gcode. Create a boat+piece,
         PATCH contour_mm rectangle and add an ENGRAVE element, then export each format. Also test
         body {"cut_only": true} => engrave omitted (laser). And gcode with body
         {"gcode":{"flavor":"mach3","include_engrave":false,"cut_depth_mm":5}}.
      2) POST /api/boats/{id}/export/{fmt} same formats + cut_only for the nested sheet.
      3) POST /api/vectorize (multipart: file=<image>, form fields threshold=-1, invert=true,
         target_width_mm=300). Use a synthetic black-text-on-white PNG. Expect polylines, width_mm,
         height_mm, count>0, preview_url, dxf_url.
      4) POST /api/projects/{id}/elements with body {type:'polyline',layer:'CUT',polylines:[[...]],params:{}}
         appends an element and returns the project with status 'edited'.
      FRONTEND (web preview only): home shows two machine buttons FRESA CNC / LASER (persist selection),
      a 'VETTORIZZA LOGO / SCRITTA DA FOTO' entry that opens /vectorize screen with FOTOCAMERA/GALLERIA,
      width mm, invert + auto-threshold toggles, ANALIZZA. Do NOT attempt real camera capture on web.
      Export modal: on a boat detail screen 'ESPORTA FOGLIO' opens a format bar; in LASER mode only
      DXF+SVG chips show, in CNC mode all 5 show incl. G-CODE params.
      Earlier round (boat CRUD, assembly PDF, nested DXF) already passed 16/16.
    -agent: "main"
    -message: |
      Implemented boat-grouping feature. Please test BACKEND boat endpoints thoroughly:
      POST /api/boats, GET /api/boats, GET /api/boats/{id}, PATCH, DELETE (cascades to pieces),
      POST /api/projects with boat_id+piece_name, GET /api/projects?boat_id=..,
      GET /api/boats/{id}/assembly (A4 PDF), POST /api/boats/{id}/nested-dxf.
      For assembly/nested-dxf create a boat + 2 pieces and PATCH contour_mm before calling.
      No auth. Backend at internal URL. For FRONTEND (web preview) test navigation only:
      home boat list, create boat modal, open boat detail, add-piece form fields.
      Camera capture cannot be tested on web; skip actual photo capture.
    -agent: "main"
    -message: |
      NEW: Added COLOR logo tracing engine using vtracer (multi-colour region tracing) for
      photos of coloured emblems (e.g. BMW). Please test BACKEND only:
      POST /api/vectorize with form field subject=colore (also pass file=<any coloured logo image>,
      target_width_mm=200, roi optional). Expect: HTTP 200, count>0, width_mm/height_mm present,
      preview_url (a rendered COLOUR png), dxf_url. Also verify REGRESSION: subject=scritta,
      subject=logo, subject=cerchio still return 200 with polylines on a simple image.
      Use any coloured logo image (or generate a synthetic one with coloured shapes + text).
      No auth. Do NOT test frontend (image picker cannot be automated on web).
    -agent: "main"
    -message: |
      NEW FEATURE: Markerless photogrammetry capture for FLAT pieces (module backend/photogram.py,
      screen frontend/app/photogram/[id].tsx). Flow: upload several photos of a flat piece ->
      combine into one mosaic (OpenCV Stitcher) -> user marks a known-size reference (rectangle=4
      points+WxH, or line=2 points+length) on the mosaic -> rectify/scale + segment the piece
      outline -> project gets contour_mm + rectified image + mm_per_px, status 'processed', then
      opens the editor.

      TEST BACKEND (endpoints, no auth, /api prefix):
      1) POST /api/projects/{id}/photogram/photos (multipart file=<image>) -> returns {id, photo_url}.
      2) GET /api/projects/{id}/photogram/photos -> list.
      3) DELETE /api/projects/{id}/photogram/photos/{photo_id} -> {ok:true}.
      4) POST /api/projects/{id}/photogram/stitch -> {mosaic_url, w, h, warning?}. (Needs >=1 photo.)
      5) POST /api/projects/{id}/photogram/extract with JSON body
         {"type":"line","points":[[x0,y0],[x1,y1]],"length_mm":150} -> project with status 'processed',
         contour_mm non-empty, mm_per_px>0, rectified_url set, detected bool.
         Also test {"type":"rect","points":[[..]x4],"width_mm":210,"height_mm":297}.
         Error cases: extract before stitch -> 400; missing dims -> 422; wrong point count -> 422.
      Setup: create a boat, then a project with capture_mode='photogram'. Upload 2-3 photos
      (any images). Use synthetic images if needed.

      TEST FRONTEND (web preview): there is a pre-seeded project id 6a81744777f2fd398faa2c4b
      (capture_mode photogram, already has photos + mosaic). Navigate to
      /photogram/6a81744777f2fd398faa2c4b. Capture phase shows photo tiles + SCATTA/GALLERIA/
      'UNISCI FOTO'. Do NOT try the gallery/camera picker (native dialog, not automatable).
      Click 'UNISCI FOTO' -> Reference phase appears with RETTANGOLO/LINEA toggle, a tappable mosaic
      canvas (testID pg-canvas), 'AZZERA PUNTI', dim inputs (pg-width/pg-height or pg-length) and
      'ESTRAI CONTORNO' (testID pg-extract). Select LINEA (pg-reftype-line), tap 2 points on the
      canvas (points counter should go 2/2), enter pg-length=150, tap pg-extract -> should navigate
      to /editor/{id}. Report if tapping registers points and extract succeeds.
    -agent: "main"
    -message: |
      FIXED the iter11 frontend bug + hardened + optimised (all re-verified):
      1) onImgPress in photogram/[id].tsx now falls back to nativeEvent.offsetX/offsetY (RN-Web) and
         guards non-finite values -> tap registers points correctly (verified: LINE 2/2 + RECT).
      2) photogram.rectify_and_extract validates points via _clean_points() -> invalid/null points
         return HTTP 422 (verified) instead of 500.
      3) PERFORMANCE: GrabCut now runs on a 600px downscaled copy (contour scaled back) -> extract
         dropped from 19-44s (which caused 502 at the ingress) to ~1.5s. Verified line+rect 200 OK.
      4) Fixed a pre-existing 500 in server.py _run_pipeline (<4 markers fallback used
         geo.simplify_contour_mm which doesn't exist -> now cv.simplify_contour_mm).
      Full UI e2e now works: capture -> UNISCI FOTO -> reference (line/rect) -> tap points ->
      ESTRAI CONTORNO -> navigates to /editor with the rectified mosaic + editable contour
      (23 pts, ~339x428mm). No further retest strictly required; feature confirmed working.