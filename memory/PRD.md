# EVA Boat Mat Digitizer — PRD

## Problem Statement
App per estrarre dime precise di tappeti in EVA da foto di aree piane delimitate da nastro,
con editor vettoriale e texture, ed export DXF pronto per fresa CNC. Mobile (Expo) + backend
FastAPI condiviso; la Computer Vision gira sul backend.

## Fix (2026-06b) — Rendering barca: drag pezzi non funzionava su touch (rimbalzo/nessuno spostamento)
- CAUSA 1: `fit` era un `useMemo([pieces])` → ad ogni move ricalcolava e ri-centrava la vista (rientro).
  FIX: `fit` è ora uno `state` calcolato UNA VOLTA per caricamento; `load()` lo resetta a null.
- CAUSA 2: l'hit-test usava `nativeEvent.locationX` che su touch è relativo al figlio toccato
  (l'`<Svg>`/`<Polygon>`), non alla View col PanResponder → selezione sbagliata o pezzo che non si
  muoveva. FIX: hit-test con coordinate di PAGINA `gestureState.x0/y0` meno l'offset della canvas
  misurato con `measureInWindow` (`canvasRef`, aggiornato in onLayout). `<Svg pointerEvents="none">`
  così i tocchi arrivano sempre alla canvas. Verificato: offset misurato {0,52}, pezzo trascinato
  e mantenuto in posizione, nessun rientro.
- FEATURE: "PEZZI SOVRAPPOSTI" — rilevo le sovrapposizioni tra pezzi (contenimento vertice + incrocio
  bordi in coord mondo); i pezzi sovrapposti hanno bordo ROSSO tratteggiato + banner di avviso.
- FEATURE: pulsante "ADATTA VISTA" (icona maximize in alto a destra della tela) ri-centra e rifitta
  tutti i pezzi (`setFit(computeFit(...))`).

## Fix (2026-06) — Rendering barca: i pezzi tornavano alla posizione iniziale durante il drag
- BUG: in `render/[id].tsx` la trasformazione della vista `fit` era un `useMemo([pieces, cw])`;
  ad ogni `onPanResponderMove` (che aggiorna `pieces`) il bounding box del mondo veniva ricalcolato
  e la vista ri-scalata/ri-centrata → il pezzo trascinato sembrava "tornare" al suo posto.
- FIX: `fit` è ora uno `state` calcolato UNA SOLA VOLTA per caricamento (via effetto quando `fit===null`
  e `cw` noto). `load()` resetta `fit=null` per rifittare sui dati appena caricati; durante il drag
  la vista resta STABILE. Verificato: pezzo trascinato resta nella nuova posizione, nessun rientro.

## Feature (2026-06) — Anteprima VETTORIALE zoomabile (Vettorizza)
- Nuovo componente `src/components/VectorPreview.tsx`: disegna le polilinee del risultato
  (`result.polylines`, mm, Y-giù) come SVG vettoriale con pinch/pan + pulsanti zoom +/−/fit
  (viewBox-based, stesso pattern dell'editor). Usa un unico `<Path>` con `fillRule="evenodd"`
  così i fori (contorni interni delle lettere/emblemi) si vedono correttamente, con griglia mm
  adattiva. Filtra i punti non finiti per evitare crash di render.
- `vectorize.tsx`: toggle VETTORE / IMMAGINE sotto la preview (default VETTORE dopo l'analisi).
  Il risultato è ora esplorabile come disegno vettoriale nitido a qualsiasi zoom invece della sola
  anteprima PNG. Verificato: forma con foro evenodd + cerchio, zoom mantiene linee nette.

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

## Feature (2026-08-18) — PUNTI NERI (contorno da punti d'angolo, forme irregolari)
- Caso reale: nastro di carta BEIGE su legno marrone = contrasto troppo basso per il rilevamento a
  colori/texture. L'utente segna i vertici con PUNTI NERI. Nuova modalità nel flusso FOTO+RIFERIMENTO.
- Backend (`cv_pipeline.detect_black_dots` + `order_points_tsp`): rileva i punti scuri (soglia
  adattiva + gate di dimensione/contrasto per scartare i nodi del legno) e li ordina in un anello
  chiuso (nearest-neighbour + 2-opt) → contorno anche per forme a L/irregolari.
  `photogram.rectify_and_extract` rtype "dots": scala dai 2 punti a distanza nota (come 'line'),
  accetta una lista `dots` ripulita dall'utente o auto-rileva. Endpoint `POST
  /projects/{id}/photogram/detect-dots`.
- Frontend (`photogram/[id].tsx`): segmented "PUNTI NERI", pulsante RILEVA PUNTI, toggle IMPOSTA
  SCALA (tocca 2 punti + mm), tocco sulla foto per aggiungere/rimuovere i punti outline (cerchi
  arancioni), poi ESTRAI CONTORNO. La rifinitura finale (spostare/aggiungere/eliminare) resta
  disponibile nell'editor. Verificato: foto reale a L → contorno 6 punti, bbox ~545×1235mm; UI senza errori.

## Fix (2026-08-17f) — Nastro BIANCO su fondo SCURO non rilevato senza marker
- Il rilevamento "bianco"/white_on_dark usava una soglia fissa (V>165) che con luce non uniforme si
  spezzava, e l'AUTO scartava il bianco quando la frazione superava il cap. Inoltre, scegliendo "BIANCO"
  esplicitamente, il codice ripiegava su auto e falliva.
- FIX (`cv_pipeline.tape_mask` bianco): soglia adattiva = luminosità fissa (V>=150, bassa saturazione)
  UNIONE Otsu sul canale V, con guardia anti-sovra-selezione (se Otsu prende >55% del frame usa solo la
  soglia fissa) e rimozione dei pixel colorati (S>110). `_tape_score` cap alzato a 0.75.
- FIX (`photogram._segment_tape`): se l'utente sceglie un colore specifico (es. BIANCO) viene
  **provato per primo e rispettato**, con fallback ad AUTO solo se non produce un contorno valido.
- FIX (`server._run_pipeline` ramo auto): il colore scelto (incl. white_on_dark) è ora rispettato senza
  gate rigido. Verificato: fondo scuro texturizzato + nastro bianco con ombra → tape_detected True
  (pref bianco/auto/white_on_dark); regressione nastro blu su bianco OK.

## Fix + Feature (2026-08-17e) — Diamante restituiva righe + Altezza diamante
- BUG: il pattern "diamond" usava `_hatch(angle)` + `_hatch(-angle)`; con angolo 0 (default del
  modale RIEMPI) le due famiglie coincidevano → uscivano RIGHE invece di diamanti. Il preset
  funzionava solo perché forzava 45°.
- FIX (`geometry_ops.fill_pattern`): il diamante ora genera due famiglie a `angle ± atan2(H, W)` con
  spacing perpendicolare `(W*H)/hypot(W,H)` → diamanti reali di larghezza W e altezza H, per qualsiasi
  orientamento (mai collassano). Nuovo parametro `diamond_height_mm`.
- FEATURE: campo "ALTEZZA DIAMANTE (mm)" nel modale RIEMPI (mostrato solo per DIAMANTE) + tipo in
  `FillRequest`. Preset DIAMANTE aggiornato (W60 H60, angolo 0). Verificato: W20×H60 → diamanti alti e
  stretti; W60×H120 dirs ~63/117; W60×H30 dirs ~27/153. Nessun crash.

## Fix (2026-08-17d) — crash "Uncaught Error" su RIEMPI AREA con scritta/logo
- Causa: errore di RENDER nel frontend (react-native-svg) quando un `<Polyline>`/`<Polygon>`
  riceveva punti non finiti/malformati (possibile logo SVG o geometria degenere). Il client API
  converte già gli errori HTTP in toast, quindi il crash NON era una risposta backend.
- Fix frontend (`editor/[id].tsx`): `ptsStr` ora filtra i punti non finiti/malformati e salta i
  polyline vuoti in fase di render (contorno, fillet preview, elementi, fill) → nessun crash possibile.
- Fix backend (`server.py /geometry/fill`): avvolto in try/except → mai più 500, ritorna 422 con
  messaggio e logga la traceback completa (per diagnosi se ricapita).
- Nota: non riproducibile con testo "EVA 40"/vari (text_to_polylines e svg_to_polylines verificati
  puliti, nessun NaN); l'hardening copre qualsiasi sorgente.

## Implemented (2026-08-17c)
- ✅ **Punti bianchi sul nastro** (`cv_pipeline.detect_tape_corner_dots`): rileva i segni di
  pennarello BIANCO disegnati sul nastro (es. bianco su nastro blu) come i 4 angoli di riferimento
  (più precisi degli angoli del nastro). Integrato in `_run_pipeline` (SCATTO SINGOLO auto): prova
  prima i punti bianchi, poi ripiega sugli angoli del nastro. Validato su immagine sintetica.
- ✅ **RACCORDO angoli con anteprima LIVE** (`geometry_ops.apply_fillet` riscritto a fillet per-angolo
  ad archi tangenti — mantiene i lati dritti, arrotonda solo gli spigoli col raggio dato, clamp per
  angolo). L'editor mostra l'anteprima arrotondata in tempo reale (`roundPolygon` in editor/[id].tsx,
  stesso algoritmo del backend → WYSIWYG con l'export) + chip preset 0/5/10/20 mm. Il contorno "vivo"
  (spigoloso) resta tratteggiato/attenuato sotto. Export SVG/DXF applicano lo stesso fillet.

## Implemented (2026-08-17b)
- ✅ **Nastro multi-colore + AUTO** (`cv_pipeline.tape_mask`/`best_tape_color`/`detect_tape_quad`):
  rilevamento nastro per blu/azzurro, giallo, verde, rosso, bianco. Nuovo campo `Project.tape_color`
  (default "auto"). Selettore "Colore nastro" in `new-project` (AUTO + colori). AUTO sceglie il colore
  che racchiude meglio un'area (buco interno). Testato 12/12 (iteration_13).
- ✅ **SCATTO SINGOLO automatico** (`server._run_pipeline`): senza bollini rileva il nastro (colore
  auto o scelto), ne prende i 4 angoli esterni come riferimento (interasse noto) e ricava il contorno
  del tappeto delimitato dal nastro, salvando SEMPRE la foto raddrizzata (mai tela grigia). Senza nastro:
  mostra comunque la foto originale + rettangolo provvisorio da correggere. Verificato sulla foto reale
  (~916×655mm) e su nastri sintetici giallo/verde/rosso/blu.

## Implemented (2026-08-17)
- ✅ **Rilevamento NASTRO nel flusso FOTO+RIFERIMENTO** (`photogram._segment_tape`, `rectify_and_extract`):
  dopo il raddrizzamento con i 4 angoli toccati (RETTANGOLO) o la linea, il contorno viene estratto
  seguendo il NASTRO colorato (HSV blu/bianco, bordo interno/esterno da `cut_side`), con fallback a
  GrabCut. Caso d'uso reale: tappeto delimitato da nastro azzurro + 4 punti neri d'angolo, foto singola
  dall'alto (niente bollini). Verificato end-to-end sulla foto reale utente: foto raddrizzata VISIBILE
  in editor + contorno che segue il nastro (~919×657mm). Endpoint `pg_extract` passa `background_mode`+`cut_side`.
- ✅ **Foto sempre visibile in editor**: la causa del "riquadro grigio/vuoto" era che la pipeline
  SCATTO SINGOLO non salvava l'immagine raddrizzata quando non trovava ≥4 bollini (nella foto utente
  venivano rilevate per errore le cifre della data). Il flusso FOTO+RIFERIMENTO ora salva sempre la
  raddrizzata e rileva il nastro.
- ✅ **UX photogram**: "USA FOTO + RIFERIMENTO" è ora l'azione PRIMARIA (ArUco declassato a link
  secondario per pezzi molto grandi). Istruzioni aggiornate per tappeti delimitati dal nastro + 4 punti
  d'angolo. `new-project` info photogram aggiornata.
- ✅ **Doghe teak dal centro** (`boat_render.render`): le doghe del rendering ora sono simmetriche
  rispetto al centro del pezzo (doga centrale a k=0, le altre a specchio verso i bordi) invece di
  partire da un lato (`np.arange` → range simmetrico).
- ✅ **Decode EXIF-aware** (`cv_pipeline.imdecode_exif`) usato in tutte le decodifiche di foto caricate
  (robustezza orientamento; OpenCV 5.0 lo gestisce già, questo è un fallback via Pillow).

## Implemented (2026-08-15)
- ✅ **RENDERING BARCA (colori EVA per pezzo)** (`boat_render.py`, `render/[id].tsx`): schermata di
  composizione per barca: ogni pezzo appare a colori e si può **trascinare/ruotare** per comporre il
  piano; colore EVA per singolo pezzo (Marrone/Grigio/Nero/Beige) e riga/scanalatura (Bianco/Nero).
  Backend render (matplotlib) con righe teak, legenda e area totale → `GET /boats/{id}/render.{png|pdf}`.
  Nuovi campi Project: eva_color, groove_color, layout_x/y/rot (PATCH). Pulsante in boat/[id].
- ✅ **Rotazione pezzo nell'editor** (`editor/[id].tsx`, `rotatePiece`): riga "RUOTA PEZZO" nella
  scheda PUNTI con ⟲90° / −1° / +1° / ⟳90°. Ruota contorno + elementi attorno al centro del bbox
  e salva. Verificato (quote si scambiano a 90°).
- ✅ **ArUco multi-foto per pezzi grandi/complessi** (`aruco_stitch.py`): l'utente stampa un foglio
  di marker ArUco (`GET /api/aruco/sheet.pdf?mm=`, DICT_4X4_50, matplotlib), ne appoggia alcuni sul
  piano attorno al pezzo, scatta più foto sovrapposte (ogni foto condivide ≥1 marker). Il backend
  rileva i marker, costruisce un frame mondo metrico (anchor + propagazione via omografie/BFS),
  compone un ORTHO-MOSAICO in mm (blending) e segmenta il contorno. Endpoint
  `POST /projects/{id}/photogram/aruco {marker_mm}`. Gestisce aree grandi che non entrano in una
  foto. Backend 9/9 test; UI verificata. Rimosso OpenCV Stitcher (causava crash nativi).
- ✅ **FOTO + RIFERIMENTO (foto singola, fallback)**: `/photogram/stitch` ora sceglie la foto più
  nitida (in-process, crash-safe) + riferimento manuale RETTANGOLO/LINEA con **punti trascinabili**
  (PanResponder) → `/photogram/extract` → contorno in mm → editor.
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
