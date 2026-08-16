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
- ✅ **Fotogrammetria multi-foto per pezzi PIATTI (senza bollini)** (`photogram.py`, schermata
  `photogram/[id].tsx`, `capture_mode=photogram`): l'utente scatta 3–8 foto del pezzo da varie
  angolazioni a ~1 m; le foto vengono unite in un unico mosaico (OpenCV Stitcher, fallback prima
  foto), poi l'utente marca sul mosaico un riferimento di misura nota — RETTANGOLO (4 angoli +
  larghezza×altezza → raddrizzamento prospettico completo) oppure LINEA (2 punti + lunghezza →
  sola scala) — e il backend rettifica/scala e segmenta il contorno del pezzo (GrabCut su copia
  ridotta ~600px per velocità, ~1.5s) restituendolo come `contour_mm` + immagine rettificata +
  `mm_per_px`; il pezzo passa a `processed` e si apre l'editor per rifinire ed esportare in DXF.
  Endpoints: `/projects/{id}/photogram/photos` (POST/GET/DELETE), `/photogram/stitch`,
  `/photogram/extract`. Backend 15/15 test; flusso UI verificato end-to-end.
- ✅ Fix: `server.py:_run_pipeline` fallback <4 bollini usava `geo.simplify_contour_mm`
  (inesistente) → corretto in `cv.simplify_contour_mm` (crash 500 pre-esistente).
- ✅ **Motore COLORE loghi (vtracer)** (`vectorize.py`, modalità `subject=colore`): traccia loghi/emblemi
  MULTICOLORE (es. BMW) segmentando le regioni di colore con `vtracer` (spline morbide) e restituisce
  un'anteprima A COLORI (SVG→PNG via cairosvg). Superiore alla soglia grigia su foto lucide. UI
  Vettorizza: pulsante COLORE (default), controlli soglia/inverti/dettagli nascosti in questa modalità.
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
- ✅ **Progetti multi-pezzo (imbarcazioni)**: un progetto = un'imbarcazione che contiene 1+ pezzi
  (tappeti), ognuno con nome (es. Plancetta/Pozzetto) e col flusso singolo esistente. Nuova
  collezione `boats`; i pezzi restano in `projects` con `boat_id`+`piece_name`. Schermate: home
  lista imbarcazioni + modale creazione, `boat/[id]` con lista pezzi/aggiungi pezzo.
- ✅ **PDF A4 panoramico assemblato** (`assembly.py` + `/boats/{id}/assembly`): tutti i pezzi
  annidati automaticamente sul foglio EVA con nomi e quote.
- ✅ **Nesting su foglio EVA 900×2400 mm** (`nesting.py`): DXF foglio unico con tutti i pezzi
  annidati (`/boats/{id}/nested-dxf`), oltre al DXF per singolo pezzo. Flag overflow se superano
  un foglio.
- ✅ **Export multi-formato** (`exporters.py` + `/projects/{id}/export/{fmt}` e `/boats/{id}/export/{fmt}`):
  DXF, SVG, PDF (disegno pulito con quote), PNG, G-code (GRBL/Mach3 con parametri fresa
  configurabili). Flag `cut_only` per esportare solo il TAGLIO.
- ✅ **Selettore macchina** (home, context `machine.tsx` persistito): due pulsanti FRESA CNC / LASER.
  In modalità LASER l'export offre solo DXF/SVG in solo-TAGLIO (per tagliare la gomma dei gommoni).
- ✅ **Tracciamento vettoriale con potrace** (`vectorize.py`): la pipeline a soglia/GrabCut usa
  potrace (raster→vettoriale) per curve morbide; fallback automatico ad approxPolyDP se assente.
  Cerchio+Dettagli (cerchio+croce/lettere interne), selezione cerchio più centrale, Ripulisci
  rumore (scarta contorni <5% del maggiore), e ROI trascinabile/ridimensionabile con maniglia.
- ✅ **Selezione area (ROI), Rileva cerchi, Cursore soglia** nella schermata Vettorizza:
  ROI = rettangolo trascinabile sull'immagine (param `roi` {x,y,w,h}, ritaglio server-side);
  CERCHIO = `subject=cerchio` con HoughCircles + fallback minEnclosingCircle (dischi pieni) →
  contorno tondo perfetto; slider soglia 0-255 con AUTO. Inoltre in LOGO/OGGETTO viene rilevato
  **automaticamente il cerchio dominante centrato** (es. emblema BMW) e restituito come cerchio
  pulito, evitando blob confusi; i soggetti non tondi vengono tracciati normalmente.
- ✅ **Vettorizza da foto — pipeline robusta** (`vectorize.py`): auto-crop bande uniformi,
  CLAHE+bilaterale, **GrabCut** per rimuovere lo sfondo (logo/oggetto), soglia intensità per
  scritte/soglia manuale/dettagli interni, smoothing Chaikin. Ritaglio abilitato nel picker
  (`allowsEditing`). Nota: per loghi dettagliati a colori serve ritaglio stretto/foto pulita; il
  tracciamento automatico è ottimale per silhouette/sagome.
- ✅ **Vettorizza logo/scritta da foto** (`vectorize.py` + `/api/vectorize`, schermata `/vectorize`):
  da una foto (scuro su sfondo chiaro) traccia i contorni (OpenCV), scala alla larghezza reale in
  mm, genera DXF scaricabile e/o lo inserisce come elemento in un tappeto
  (`/projects/{id}/elements`, layer TAGLIO/INCISIONE). Anteprima del tracciato inclusa. Selettore
  **cosa rilevare** (Scritta/Logo/Oggetto → preset area+semplificazione, "Oggetto" tiene solo la
  forma più grande) e toggle **Dettagli interni** (RETR_CCOMP: fori delle lettere/linee interne).

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
