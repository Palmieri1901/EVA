# EVA Boat Mat Digitizer — PRD

## Problem Statement
App per estrarre dime precise di tappeti in EVA da foto di aree piane delimitate da nastro,
con editor vettoriale e texture, ed export DXF pronto per fresa CNC. Mobile (Expo) + backend
FastAPI condiviso; la Computer Vision gira sul backend.

## Users
- Artigiani/laboratori che tagliano tappeti EVA per barche.
- Officine con fresa CNC che vogliono digitalizzare sagome senza rilievi manuali.

## Architecture
- **Frontend**: Expo Router (React Native + TS). Screens: Projects (index), NewProject,
  Capture (expo-camera + HUD + livella accelerometro), Editor (SVG canvas pan/zoom, editing
  punti, offset/raccordo, texture), Export (wireframe + DXF share). Brutalist LIGHT design
  (Space Grotesk + IBM Plex Mono, 0 radius, 2pt borders, arancio industriale).
- **Backend**: FastAPI. Moduli: `cv_pipeline.py` (marker detection ellisse sub-pixel,
  homography, raddrizzamento, segmentazione nastro HSV, vettorializzazione), `geometry_ops.py`
  (offset shapely, raccordo, text→path via matplotlib, svg→path, pattern track),
  `dxf_builder.py` (ezdxf, layer CUT/ENGRAVE, mm), `storage_client.py` (Emergent Object Storage).
- **DB**: MongoDB (progetti + geometria + elementi). **Storage**: Emergent Object Storage (foto, rettificate, DXF).

## Core requirements (static)
1. Setup progetto: modalità sfondo (blu su bianco / bianco su scuro), diametro bollini,
   interasse noto largh×alt (scala precisa), lato taglio nastro, offset lama.
2. Cattura guidata con HUD (4 angoli + centro), livella, fallback galleria.
3. CV: rilevamento marker → omografia → raddrizzamento → bordo nastro → contorno vettoriale mm.
4. Editor: sposta/aggiungi/elimina punti (nudge preciso mm), raccordo, offset, misure in mm, griglia.
5. Texture/scritte/forme: testo→vettoriale, import SVG, pattern track, forme (rect/circle/line),
   layer INCISIONE (ENGRAVE) / TAGLIO (CUT).
6. Export DXF in mm con layer distinti; progetti salvati, storico, riesportazione.

## Implemented (2026-08-15)
- ✅ Backend CV pipeline completa (Fase 1+2): marker (RETR_LIST, ellisse), homography da
  interasse noto, raddrizzamento, segmentazione HSV nastro (blu/bianco), contorno inner/outer,
  simplify. Validata con immagine sintetica (5 marker + nastro).
- ✅ Export DXF con layer CUT/ENGRAVE (ezdxf, unità mm) — validato end-to-end via API.
- ✅ Geometria: offset/raccordo (shapely), testo→path (matplotlib DejaVu), SVG→path (svgpathtools),
  pattern track (Fase 4).
- ✅ Object Storage per foto/rettificate/DXF.
- ✅ Frontend: Projects, NewProject (form + tastiera), Capture (camera+HUD+livella+galleria),
  Editor (canvas SVG pan/zoom/tap-select, nudge, add/del punti, offset/raccordo, pannello texture,
  modale aggiunta elementi), Export (wireframe + share/download DXF). Design brutalista applicato.
- ✅ **Fase 5 Multi-scatto & stitching** (`stitch.py`): primo scatto ancora il piano dal riquadro
  di riferimento (interasse noto), scatti successivi agganciati via marker condivisi (RANSAC
  similarity → omografia con ≥4 condivisi), warp+merge maschere nastro in un raster globale,
  contorno completo vettorizzato. Endpoint shots CRUD + /stitch. UI: toggle singolo/multi in
  NewProject, schermata /shots/[id], modalità scatto della camera. Validato 2/2 scatti sintetici.
- ✅ **Riempi area con texture** (`geometry_ops.fill_pattern` + /api/geometry/fill): riempie il
  contorno (clip poligono) con texture teak diamante/incrociato/righe, stile SEMPLICE o BORDATO
  (cornice inset + campo), layer INCISIONE/TAGLIO. Pulsante "RIEMPI AREA" nell'editor.
- ✅ **Import loghi SVG da file** (editor · modale SCRITTA/LOGO tipo SVG): pulsante "IMPORTA FILE
  SVG" (expo-document-picker + expo-file-system) legge un file .svg, ne estrae i tracciati <path>
  via `/api/geometry/svg` (svgpathtools) e li inserisce come elemento posizionabile/scalabile,
  con scelta layer INCISIONE/TAGLIO. Il path SVG resta anche modificabile a mano.
- ✅ **Area pulita attorno a scritte/logo**: nel riempimento texture, campo "Area pulita attorno a
  scritte/logo (mm)" (default 15, modificabile, 0 = off) che lascia un'area senza texture attorno
  a TUTTE le scritte e i loghi (`fill_pattern` riempie le forme chiuse + margine e le sottrae dal
  campo). L'area vuota è **delimitata da un solco** di contorno (centerline se solco=0, canale
  inciso se solco>0).
- ✅ Rimossi i valori di esempio di default (testo "EVA", SVG stella, placeholder "Es. Mattia
  Yacht"): campi ora vuoti con placeholder neutri.

## Backlog (prioritized)
- **P0**: Test reali su fresa (Fase 6), correzione manuale bordo più ricca in caso di CV fallita.
- **P1**: Multi-scatto/stitching per aree 2×3 m + calibrazione lente (Fase 5).
- **P1**: Libreria pattern predefiniti navigabile + editor pattern.
- **P2**: Nesting più dime su foglio, export G-code, marker di controllo indipendenti,
  suggerimento automatico posizione marker.

## Next tasks
1. Testing agent end-to-end (backend + frontend).
2. Rifinire correzione manuale del bordo (Fase 6).
3. Multi-scatto (Fase 5).
