import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import Svg, { Circle, G, Image as SvgImage, Line, Polygon, Polyline } from "react-native-svg";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import { runOnJS } from "react-native-reanimated";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import * as DocumentPicker from "expo-document-picker";
import * as FileSystem from "expo-file-system/legacy";

import { absUrl, api, ElementT, Layer, ProjectT } from "@/src/api";
import { Btn, Segmented } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

type Pt = number[];
const uid = () => `${Date.now()}_${Math.floor(Math.random() * 1e5)}`;
const TEAK = "#C08A3E";
const TEAK_EDGE = "#6B4A1F";
const CAULK = "#2B2622";

function bboxOf(pts: Pt[]) {
  if (!pts.length) return { minX: 0, minY: 0, w: 100, h: 100, cx: 50, cy: 50 };
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const minX = Math.min(...xs), minY = Math.min(...ys), maxX = Math.max(...xs), maxY = Math.max(...ys);
  return { minX, minY, w: maxX - minX, h: maxY - minY, cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 };
}
function perimeter(pts: Pt[]) {
  let t = 0;
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    t += Math.hypot(a[0] - b[0], a[1] - b[1]);
  }
  return t;
}
const ptsStr = (arr: Pt[]) =>
  (arr || [])
    .filter(
      (p) =>
        Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1])
    )
    .map((p) => `${p[0]},${p[1]}`)
    .join(" ");

// True CAD fillet: round each corner with a circular arc of `r`, keeping the
// straight edges in place. Mirrors backend geometry_ops.apply_fillet so the
// editor preview matches the exported geometry.
function roundPolygon(points: Pt[], r: number, seg = 10): Pt[] {
  if (r <= 0 || points.length < 3) return points;
  let pts = points.map((p) => [p[0], p[1]]);
  const first = pts[0], last = pts[pts.length - 1];
  if (pts.length >= 2 && Math.abs(first[0] - last[0]) < 1e-6 && Math.abs(first[1] - last[1]) < 1e-6) {
    pts = pts.slice(0, -1);
  }
  const n = pts.length;
  if (n < 3) return points;
  const out: Pt[] = [];
  for (let i = 0; i < n; i++) {
    const prev = pts[(i - 1 + n) % n];
    const cur = pts[i];
    const nxt = pts[(i + 1) % n];
    const v1x = prev[0] - cur[0], v1y = prev[1] - cur[1];
    const v2x = nxt[0] - cur[0], v2y = nxt[1] - cur[1];
    const l1 = Math.hypot(v1x, v1y), l2 = Math.hypot(v2x, v2y);
    if (l1 < 1e-6 || l2 < 1e-6) { out.push([cur[0], cur[1]]); continue; }
    const u1 = [v1x / l1, v1y / l1], u2 = [v2x / l2, v2y / l2];
    const dot = Math.max(-1, Math.min(1, u1[0] * u2[0] + u1[1] * u2[1]));
    const theta = Math.acos(dot);
    if (theta < 1e-3 || theta > Math.PI - 1e-3) { out.push([cur[0], cur[1]]); continue; }
    const half = theta / 2;
    let t = r / Math.tan(half);
    t = Math.min(t, Math.min(l1, l2) * 0.5);
    const rr = t * Math.tan(half);
    const p1 = [cur[0] + u1[0] * t, cur[1] + u1[1] * t];
    const p2 = [cur[0] + u2[0] * t, cur[1] + u2[1] * t];
    let bx = u1[0] + u2[0], by = u1[1] + u2[1];
    const bl = Math.hypot(bx, by);
    if (bl < 1e-6) { out.push([cur[0], cur[1]]); continue; }
    bx /= bl; by /= bl;
    const cx = cur[0] + bx * (rr / Math.sin(half));
    const cy = cur[1] + by * (rr / Math.sin(half));
    const a1 = Math.atan2(p1[1] - cy, p1[0] - cx);
    const a2 = Math.atan2(p2[1] - cy, p2[0] - cx);
    let da = a2 - a1;
    while (da <= -Math.PI) da += 2 * Math.PI;
    while (da > Math.PI) da -= 2 * Math.PI;
    for (let k = 0; k <= seg; k++) {
      const a = a1 + da * (k / seg);
      out.push([cx + rr * Math.cos(a), cy + rr * Math.sin(a)]);
    }
  }
  return out;
}

function niceStep(vw: number) {
  const target = vw / 8;
  const steps = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
  for (const s of steps) if (s >= target) return s;
  return 1000;
}

export default function Editor() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();

  const [project, setProject] = useState<ProjectT | null>(null);
  const [contour, setContour] = useState<Pt[]>([]);
  const [elements, setElements] = useState<ElementT[]>([]);
  const [selNode, setSelNode] = useState<number | null>(null);
  const [selElement, setSelElement] = useState<string | null>(null);
  const [mode, setMode] = useState<"points" | "texture">("points");
  const [step, setStep] = useState(1);
  const [teak, setTeak] = useState(false);
  const [offset, setOffset] = useState("0");
  const [fillet, setFillet] = useState("0");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [canvas, setCanvas] = useState({ w: 1, h: 1 });
  const [vb, setVb] = useState({ x: 0, y: 0, w: 100 });
  const vbStart = useRef({ x: 0, y: 0, w: 100 });
  const aspect = canvas.h / canvas.w;

  // add-element modal
  const [addOpen, setAddOpen] = useState(false);
  const [elType, setElType] = useState<"text" | "track" | "rect" | "circle" | "line" | "svg" | "dxf" | "junction">("text");
  const [elLayer, setElLayer] = useState<Layer>("ENGRAVE");
  const [textVal, setTextVal] = useState("");
  const [sizeVal, setSizeVal] = useState("40");
  const [spacingVal, setSpacingVal] = useState("15");
  const [angleVal, setAngleVal] = useState("45");
  const [svgVal, setSvgVal] = useState("");
  const [svgFileName, setSvgFileName] = useState<string | null>(null);
  const [svgPicking, setSvgPicking] = useState(false);
  const [dxfVal, setDxfVal] = useState("");
  const [dxfFileName, setDxfFileName] = useState<string | null>(null);
  const [dxfPicking, setDxfPicking] = useState(false);
  const [addBusy, setAddBusy] = useState(false);

  // fill-area modal
  const [fillOpen, setFillOpen] = useState(false);
  const [fillPattern, setFillPattern] = useState<"diamond" | "cross" | "lines">("diamond");
  const [fillSpacing, setFillSpacing] = useState("20");
  const [fillAngle, setFillAngle] = useState("0");
  const [fillAuto, setFillAuto] = useState(false);
  const [fillGroove, setFillGroove] = useState("4");
  const [fillBoard, setFillBoard] = useState("0");
  const [fillDiamondHeight, setFillDiamondHeight] = useState("60");
  const [fillStyle, setFillStyle] = useState<"semplice" | "bordato" | "bordo">("semplice");
  const [fillBorder, setFillBorder] = useState("40");
  const [fillCornerRadius, setFillCornerRadius] = useState("60");
  const [fillPlankEase, setFillPlankEase] = useState("0");
  const [fillClearMargin, setFillClearMargin] = useState("15");
  const [fillLayer, setFillLayer] = useState<Layer>("ENGRAVE");
  const [fillBusy, setFillBusy] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const p = await api.getProject(id);
      setProject(p);
      setContour(p.contour_mm || []);
      setElements(p.elements || []);
      setOffset(String(p.blade_offset_mm ?? 0));
      setFillet(String(p.fillet_radius_mm ?? 0));
    } catch (e: any) {
      toast(e.message || "Errore caricamento", "error");
    } finally {
      setLoading(false);
    }
  }, [id, toast]);

  useEffect(() => {
    load();
  }, [load]);

  // fit viewBox to contour when canvas & contour ready
  const fitView = useCallback(() => {
    const src = contour.length ? contour : [[0, 0], [project?.ref_width_mm || 100, project?.ref_height_mm || 100]];
    const bb = bboxOf(src);
    const pad = Math.max(bb.w, bb.h) * 0.15 + 10;
    const w = Math.max(bb.w + pad * 2, 10);
    setVb({ x: bb.minX - pad, y: bb.minY - pad, w });
  }, [contour, project]);

  useEffect(() => {
    if (!loading && canvas.w > 1) fitView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, canvas.w]);

  const vh = vb.w * aspect;
  const scale = vb.w / canvas.w; // mm per screen px
  const nodeR = scale * 7;
  const sw = scale * 1.4;
  const gridStep = niceStep(vb.w);

  const toMM = (sx: number, sy: number): Pt => [vb.x + (sx / canvas.w) * vb.w, vb.y + (sy / canvas.h) * vh];

  const selectNearest = (sx: number, sy: number) => {
    const [mx, my] = toMM(sx, sy);
    if (mode === "texture") {
      let bestId: string | null = null, bestDe = 1e18;
      elements.forEach((el) => {
        el.polylines.forEach((pl) => {
          pl.forEach((p) => {
            const d = Math.hypot(p[0] - mx, p[1] - my);
            if (d < bestDe) { bestDe = d; bestId = el.id; }
          });
        });
      });
      if (bestId && bestDe < scale * 26) {
        Haptics.selectionAsync().catch(() => {});
        setSelElement(bestId);
      } else {
        setSelElement(null);
      }
      return;
    }
    let best = -1, bestD = 1e18;
    contour.forEach((p, i) => {
      const d = Math.hypot(p[0] - mx, p[1] - my);
      if (d < bestD) { bestD = d; best = i; }
    });
    if (best >= 0 && bestD < scale * 22) {
      Haptics.selectionAsync().catch(() => {});
      setSelNode(best);
    } else {
      setSelNode(null);
    }
  };

  const tap = Gesture.Tap().maxDuration(250).onEnd((e) => {
    runOnJS(selectNearest)(e.x, e.y);
  });
  const pan = Gesture.Pan()
    .minDistance(4)
    .onBegin(() => { vbStart.current = { ...vb }; })
    .onUpdate((e) => {
      const nx = vbStart.current.x - (e.translationX / canvas.w) * vbStart.current.w;
      const ny = vbStart.current.y - (e.translationY / canvas.h) * (vbStart.current.w * aspect);
      runOnJS(setVb)({ x: nx, y: ny, w: vbStart.current.w });
    });
  const pinch = Gesture.Pinch()
    .onBegin(() => { vbStart.current = { ...vb }; })
    .onUpdate((e) => {
      const cx = vbStart.current.x + vbStart.current.w / 2;
      const cy = vbStart.current.y + (vbStart.current.w * aspect) / 2;
      const nw = Math.min(Math.max(vbStart.current.w / e.scale, 5), 20000);
      runOnJS(setVb)({ x: cx - nw / 2, y: cy - (nw * aspect) / 2, w: nw });
    });
  const composed = Gesture.Simultaneous(pinch, Gesture.Exclusive(pan, tap));

  const zoom = (f: number) => {
    const cx = vb.x + vb.w / 2, cy = vb.y + vh / 2;
    const nw = Math.min(Math.max(vb.w * f, 5), 20000);
    setVb({ x: cx - nw / 2, y: cy - (nw * aspect) / 2, w: nw });
  };

  const nudge = (dx: number, dy: number) => {
    if (selNode === null) return;
    Haptics.selectionAsync().catch(() => {});
    setContour((c) => c.map((p, i) => (i === selNode ? [p[0] + dx, p[1] + dy] : p)));
  };
  const addNode = () => {
    if (!contour.length) return;
    const i = selNode ?? 0;
    const a = contour[i], b = contour[(i + 1) % contour.length];
    const mid: Pt = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const next = [...contour];
    next.splice(i + 1, 0, mid);
    setContour(next);
    setSelNode(i + 1);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
  };
  const delNode = () => {
    if (selNode === null || contour.length <= 3) return;
    setContour((c) => c.filter((_, i) => i !== selNode));
    setSelNode(null);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
  };

  const rotatePiece = (deg: number) => {
    if (contour.length < 2) return;
    const bb = bboxOf(contour);
    const r = (deg * Math.PI) / 180, cos = Math.cos(r), sin = Math.sin(r);
    const rot = (p: Pt): Pt => {
      const x = p[0] - bb.cx, y = p[1] - bb.cy;
      return [bb.cx + x * cos - y * sin, bb.cy + x * sin + y * cos];
    };
    const newContour = contour.map(rot);
    const newElements = elements.map((e) => ({ ...e, polylines: e.polylines.map((pl) => pl.map(rot)) }));
    setContour(newContour);
    setElements(newElements);
    setSelNode(null);
    Haptics.selectionAsync().catch(() => {});
    save({ contour_mm: newContour, elements: newElements });
  };

  const elCenter = (el: ElementT) => {
    const pts = el.polylines.flat();
    if (!pts.length) return { x: 0, y: 0 };
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2 };
  };
  const applyEl = async (id: string, fn: (p: Pt) => Pt) => {
    const next = elements.map((e) =>
      e.id === id ? { ...e, polylines: e.polylines.map((pl) => pl.map(fn)) } : e
    );
    setElements(next);
    await save({ elements: next });
    scheduleRefill(next);
  };
  const moveEl = (dx: number, dy: number) => {
    if (!selElement) return;
    Haptics.selectionAsync().catch(() => {});
    applyEl(selElement, (p) => [p[0] + dx, p[1] + dy]);
  };
  const rotateEl = (deg: number) => {
    if (!selElement) return;
    const el = elements.find((e) => e.id === selElement);
    if (!el) return;
    const c = elCenter(el);
    const r = (deg * Math.PI) / 180, cos = Math.cos(r), sin = Math.sin(r);
    Haptics.selectionAsync().catch(() => {});
    applyEl(selElement, (p) => {
      const x = p[0] - c.x, y = p[1] - c.y;
      return [c.x + x * cos - y * sin, c.y + x * sin + y * cos];
    });
  };
  const scaleEl = (f: number) => {
    if (!selElement) return;
    const el = elements.find((e) => e.id === selElement);
    if (!el) return;
    const c = elCenter(el);
    Haptics.selectionAsync().catch(() => {});
    applyEl(selElement, (p) => [c.x + (p[0] - c.x) * f, c.y + (p[1] - c.y) * f]);
  };

  const save = useCallback(
    async (extra: any = {}) => {
      if (!id) return false;
      const body = {
        contour_mm: contour,
        elements,
        blade_offset_mm: parseFloat(offset) || 0,
        fillet_radius_mm: parseFloat(fillet) || 0,
        status: "edited",
        ...extra,
      };
      try {
        await api.updateProject(id, body);
        return true;
      } catch (e: any) {
        toast(e?.message || "Salvataggio non riuscito", "error");
        return false;
      }
    },
    [id, contour, elements, offset, fillet]
  );

  const onBack = async () => {
    await save();
    router.replace("/");
  };
  const goExport = async () => {
    setSaving(true);
    try {
      const ok = await save();
      if (ok) router.push(`/export/${id}` as any);
    } finally {
      setSaving(false);
    }
  };

  const pickSvgFile = async () => {
    setSvgPicking(true);
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ["image/svg+xml", "text/xml", "application/xml", "*/*"],
        copyToCacheDirectory: true,
        multiple: false,
      });
      if (res.canceled || !res.assets?.length) return;
      const asset = res.assets[0];
      const name = asset.name || "logo.svg";
      if (!/\.svg$/i.test(name) && asset.mimeType !== "image/svg+xml") {
        toast("Seleziona un file .svg valido", "error");
        return;
      }
      const content = await FileSystem.readAsStringAsync(asset.uri, {
        encoding: FileSystem.EncodingType.UTF8,
      });
      if (!content || !/<path/i.test(content)) {
        toast("SVG senza tracciati <path> utilizzabili", "error");
        return;
      }
      setSvgVal(content);
      setSvgFileName(name);
      Haptics.selectionAsync().catch(() => {});
      toast(`Logo "${name}" caricato · premi AGGIUNGI`, "success");
    } catch (e: any) {
      toast(e.message || "Errore importazione SVG", "error");
    } finally {
      setSvgPicking(false);
    }
  };

  const pickDxfFile = async () => {
    setDxfPicking(true);
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: ["image/vnd.dxf", "application/dxf", "application/octet-stream", "*/*"],
        copyToCacheDirectory: true,
        multiple: false,
      });
      if (res.canceled || !res.assets?.length) return;
      const asset = res.assets[0];
      const name = asset.name || "logo.dxf";
      if (!/\.dxf$/i.test(name)) {
        toast("Seleziona un file .dxf valido", "error");
        return;
      }
      const content = await FileSystem.readAsStringAsync(asset.uri, {
        encoding: FileSystem.EncodingType.UTF8,
      });
      if (!content || !/(SECTION|ENTITIES|LINE|POLYLINE|CIRCLE)/i.test(content)) {
        toast("DXF senza geometrie utilizzabili", "error");
        return;
      }
      setDxfVal(content);
      setDxfFileName(name);
      Haptics.selectionAsync().catch(() => {});
      toast(`Logo DXF "${name}" caricato · premi AGGIUNGI`, "success");
    } catch (e: any) {
      toast(e.message || "Errore importazione DXF", "error");
    } finally {
      setDxfPicking(false);
    }
  };

  const confirmAdd = async () => {
    const bb = bboxOf(contour);
    setAddBusy(true);
    try {
      let polylines: number[][][] = [];
      if (elType === "text") {
        const r = await api.geoText({
          text: textVal, height_mm: parseFloat(sizeVal) || 30,
          x: bb.minX + 10, y: bb.cy, layer: elLayer,
        });
        polylines = r.polylines;
      } else if (elType === "svg") {
        const r = await api.geoSvg({ svg: svgVal, width_mm: parseFloat(sizeVal) || 100, x: bb.cx - (parseFloat(sizeVal) || 100) / 2, y: bb.minY + 10, layer: elLayer });
        polylines = r.polylines;
      } else if (elType === "dxf") {
        const w = parseFloat(sizeVal) || 100;
        const r = await api.geoDxf({ dxf: dxfVal, width_mm: w, x: bb.cx - w / 2, y: bb.minY + 10, layer: elLayer });
        polylines = r.polylines;
      } else if (elType === "track") {
        const r = await api.geoTrack({
          x: bb.minX, y: bb.minY, width_mm: bb.w, height_mm: bb.h,
          spacing_mm: parseFloat(spacingVal) || 15, angle_deg: parseFloat(angleVal) || 45, layer: elLayer,
        });
        polylines = r.polylines;
      } else if (elType === "rect") {
        const w = parseFloat(sizeVal) || 100, h = w * 0.6;
        const x = bb.cx - w / 2, y = bb.cy - h / 2;
        polylines = [[[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]];
      } else if (elType === "circle") {
        const r = (parseFloat(sizeVal) || 60) / 2;
        const pts: number[][] = [];
        for (let a = 0; a <= 48; a++) {
          const t = (a / 48) * Math.PI * 2;
          pts.push([bb.cx + r * Math.cos(t), bb.cy + r * Math.sin(t)]);
        }
        polylines = [pts];
      } else if (elType === "line") {
        const w = parseFloat(sizeVal) || 100;
        polylines = [[[bb.cx - w / 2, bb.cy], [bb.cx + w / 2, bb.cy]]];
      } else if (elType === "junction") {
        // Straight junction/seam: looks like an engraved line but is a real CUT.
        // The mat is adhesive, so no mechanical teeth are needed — the two parts
        // are simply butted together and stuck down. Splits a large/complex mat.
        const len = parseFloat(sizeVal) || bb.w;
        polylines = [[[bb.cx - len / 2, bb.cy], [bb.cx + len / 2, bb.cy]]];
      }
      if (!polylines.length) throw new Error("Nessuna geometria generata");
      // a junction is always a CUT (giunzione/taglio), regardless of the selector
      const layer: Layer = elType === "junction" ? "CUT" : elLayer;
      const el: ElementT = { id: uid(), type: elType, layer, polylines, params: {} };
      let next = [...elements, el];
      // If the piece already has a texture, re-cut it so the configured clear
      // space + border is left around the newly inserted element too.
      next = await rebuildFills(next);
      setElements(next);
      setSelElement(el.id);
      await save({ elements: next });
      setAddOpen(false);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast("Elemento aggiunto · trascina/sposta per posizionarlo", "success");
    } catch (e: any) {
      toast(e.message || "Errore aggiunta elemento", "error");
    } finally {
      setAddBusy(false);
    }
  };

  const delElement = async (eid: string) => {
    let next = elements.filter((e) => e.id !== eid);
    if (selElement === eid) setSelElement(null);
    // re-cut textures so the space around the removed element closes back up
    next = await rebuildFills(next);
    setElements(next);
    await save({ elements: next });
  };

  const runFill = async (opts: {
    pattern: "diamond" | "cross" | "lines";
    spacing: number;
    angle: number;
    auto: boolean;
    style: "semplice" | "bordato" | "bordo";
    border: number;
    groove: number;
    board: number;
    diamondHeight?: number;
    cornerRadius?: number;
    plankEase?: number;
    layer: Layer;
    clearMargin?: number;
    setBusy?: (b: boolean) => void;
  }) => {
    if (contour.length < 3) {
      toast("Contorno non valido", "error");
      return;
    }
    opts.setBusy?.(true);
    try {
      // keep-out zones: inserted elements (text, logos/svg, circles, rects,
      // lines, tracks, vectorized polylines) get the clear margin around them.
      // Junctions are excluded: they're just a CUT seam through the textured mat,
      // so the texture must flow across them uninterrupted.
      const clear = opts.clearMargin ?? 0;
      const exclude: number[][][] =
        clear > 0
          ? elements
              .filter((e) => e.type !== "fill" && e.type !== "junction")
              .flatMap((e) => e.polylines)
          : [];
      const r = await api.geoFill({
        contour,
        spacing_mm: opts.spacing || 20,
        angle_deg: opts.angle || 0,
        auto_angle: opts.auto,
        pattern: opts.pattern,
        style: opts.style,
        border_mm: opts.border || 30,
        groove_mm: opts.groove || 0,
        board_length_mm: opts.board || 0,
        diamond_height_mm: opts.diamondHeight || 0,
        corner_radius_mm: opts.cornerRadius || 0,
        plank_ease_mm: opts.plankEase || 0,
        exclude,
        exclude_margin_mm: clear,
        layer: opts.layer,
      });
      const el: ElementT = {
        id: uid(),
        type: "fill",
        layer: opts.layer,
        polylines: r.polylines,
        // store the FULL fill setup so the texture can be regenerated later
        // (e.g. to carve the clear space + border around newly added elements).
        params: {
          pattern: opts.pattern,
          style: opts.style,
          spacing: opts.spacing,
          angle: opts.angle,
          auto: opts.auto,
          border: opts.border,
          groove: opts.groove,
          board: opts.board,
          diamondHeight: opts.diamondHeight || 0,
          cornerRadius: opts.cornerRadius || 0,
          plankEase: opts.plankEase || 0,
          clearMargin: clear,
          layer: opts.layer,
        },
      };
      const next = [...elements, el];
      setElements(next);
      await save({ elements: next });
      setFillOpen(false);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast(`Area riempita · ${r.polylines.length} tracciati`, "success");
    } catch (e: any) {
      toast(e.message || "Riempimento fallito", "error");
    } finally {
      opts.setBusy?.(false);
    }
  };

  // Regenerate every existing fill texture so the configured clear space +
  // border is carved around ALL current non-fill elements (used after a new
  // element is inserted/removed on a piece that already has a texture).
  const rebuildFills = async (els: ElementT[]): Promise<ElementT[]> => {
    const fills = els.filter((e) => e.type === "fill");
    if (fills.length === 0) return els;
    const keepout = els.filter((e) => e.type !== "fill" && e.type !== "junction").flatMap((e) => e.polylines);
    const out = [...els];
    for (const f of fills) {
      const pr: any = f.params || {};
      const clear = pr.clearMargin ?? 15;
      const pattern = pr.pattern || "lines";
      const isLines = pattern === "lines";
      const bordato = (pr.style || "semplice") === "bordato";
      try {
        const r = await api.geoFill({
          contour,
          spacing_mm: pr.spacing ?? (isLines ? 60 : 40),
          angle_deg: pr.angle ?? 0,
          // legacy fills lack these — reconstruct a teak-like look for lines
          auto_angle: pr.auto ?? isLines,
          pattern,
          style: pr.style || "semplice",
          border_mm: pr.border ?? 40,
          groove_mm: pr.groove ?? 0,
          board_length_mm: pr.board ?? (isLines && bordato ? 400 : 0),
          diamond_height_mm: pr.diamondHeight ?? 0,
          corner_radius_mm: pr.cornerRadius ?? 0,
          plank_ease_mm: pr.plankEase ?? 0,
          exclude: clear > 0 ? keepout : [],
          exclude_margin_mm: clear,
          layer: pr.layer || f.layer,
        });
        const idx = out.findIndex((e) => e.id === f.id);
        if (idx >= 0) out[idx] = { ...f, polylines: r.polylines };
      } catch {
        // keep the old fill if regeneration fails
      }
    }
    return out;
  };

  // Debounced re-cut after an element is moved/rotated/scaled, so the texture
  // clear space follows the element to its final position (no per-nudge lag).
  const refillTimer = useRef<any>(null);
  const scheduleRefill = (els: ElementT[]) => {
    if (!els.some((e) => e.type === "fill")) return;
    if (refillTimer.current) clearTimeout(refillTimer.current);
    refillTimer.current = setTimeout(async () => {
      const rebuilt = await rebuildFills(els);
      setElements(rebuilt);
      await save({ elements: rebuilt });
    }, 600);
  };

  const confirmFill = () =>
    runFill({
      pattern: fillPattern,
      spacing: parseFloat(fillSpacing),
      angle: parseFloat(fillAngle),
      auto: fillAuto,
      style: fillStyle,
      border: parseFloat(fillBorder),
      groove: parseFloat(fillGroove),
      board: parseFloat(fillBoard),
      diamondHeight: parseFloat(fillDiamondHeight) || 0,
      cornerRadius: parseFloat(fillCornerRadius) || 0,
      plankEase: parseFloat(fillPlankEase) || 0,
      layer: fillLayer,
      clearMargin: parseFloat(fillClearMargin) || 0,
      setBusy: setFillBusy,
    });

  const bumpAngle = (d: number) => {
    setFillAuto(false);
    const cur = parseFloat(fillAngle) || 0;
    let next = (cur + d) % 180;
    if (next < 0) next += 180;
    setFillAngle(String(Math.round(next)));
    Haptics.selectionAsync().catch(() => {});
  };

  const applyPreset = (name: "doghe" | "diamante" | "incrociato") => {
    const clearMargin = parseFloat(fillClearMargin) || 0;
    if (name === "doghe") {
      runFill({ pattern: "lines", spacing: 60, angle: 0, auto: true, style: "bordato", border: 40, groove: 5, board: 400, cornerRadius: 60, plankEase: 8, layer: "ENGRAVE", clearMargin });
    } else if (name === "diamante") {
      runFill({ pattern: "diamond", spacing: 60, angle: 0, auto: false, style: "semplice", border: 30, groove: 4, board: 0, diamondHeight: 60, layer: "ENGRAVE", clearMargin });
    } else {
      runFill({ pattern: "cross", spacing: 40, angle: 0, auto: false, style: "semplice", border: 30, groove: 4, board: 0, layer: "ENGRAVE", clearMargin });
    }
  };

  const bb = useMemo(() => bboxOf(contour), [contour]);
  const perim = useMemo(() => perimeter(contour), [contour]);
  const filletR = parseFloat(fillet) || 0;
  const filletedContour = useMemo(
    () => (filletR > 0 && contour.length >= 3 ? roundPolygon(contour, filletR) : null),
    [contour, filletR]
  );
  const rectUrl = absUrl(project?.rectified_url);
  const imgW = project && project.rectified_w_px > 0 ? project.rectified_w_px * project.mm_per_px : project?.ref_width_mm || 0;
  const imgH = project && project.rectified_h_px > 0 ? project.rectified_h_px * project.mm_per_px : project?.ref_height_mm || 0;

  // grid lines
  const gridLines = useMemo(() => {
    const lines: { x1: number; y1: number; x2: number; y2: number }[] = [];
    const startX = Math.floor(vb.x / gridStep) * gridStep;
    for (let x = startX; x <= vb.x + vb.w; x += gridStep) lines.push({ x1: x, y1: vb.y, x2: x, y2: vb.y + vh });
    const startY = Math.floor(vb.y / gridStep) * gridStep;
    for (let y = startY; y <= vb.y + vh; y += gridStep) lines.push({ x1: vb.x, y1: y, x2: vb.x + vb.w, y2: y });
    return lines;
  }, [vb, vh, gridStep]);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brand} size="large" />
        <Text style={styles.loadText}>VETTORIALIZZAZIONE...</Text>
      </View>
    );
  }

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      {/* top bar */}
      <View style={styles.topbar}>
        <Pressable testID="editor-back" onPress={onBack} hitSlop={12}>
          <Feather name="arrow-left" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title} numberOfLines={1}>{project?.name}</Text>
        <Pressable testID="editor-export" onPress={goExport} hitSlop={12}>
          {saving ? <ActivityIndicator color={colors.brand} /> : <Feather name="download" size={22} color={colors.brand} />}
        </Pressable>
      </View>

      {/* measurements */}
      <View style={styles.measureBar}>
        <Text style={styles.measure}>W {bb.w.toFixed(1)}mm</Text>
        <Text style={styles.measure}>H {bb.h.toFixed(1)}mm</Text>
        <Text style={styles.measure}>PERIM {perim.toFixed(0)}mm</Text>
        <Text style={styles.measure}>PTS {contour.length}</Text>
      </View>

      {/* canvas */}
      <View style={styles.canvasWrap} onLayout={(e) => setCanvas({ w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height })}>
        <GestureDetector gesture={composed}>
          <Svg width="100%" height="100%" viewBox={`${vb.x} ${vb.y} ${vb.w} ${vh}`}>
            {teak ? (
              <>
                {contour.length >= 3 && (
                  <Polygon points={ptsStr(filletedContour || contour)} fill={TEAK} stroke={TEAK_EDGE} strokeWidth={sw} />
                )}
                {elements.map((el) =>
                  el.polylines.map((pl, j) => {
                    const s = ptsStr(pl);
                    if (!s) return null;
                    const gw = Number(el?.params?.groove) || 0;
                    const color = el.layer === "CUT" ? "#5A0F0F" : CAULK;
                    const strokeW = el.layer === "CUT" ? sw : Math.max(sw, gw * 0.6);
                    return (
                      <Polyline
                        key={`t_${el.id}_${j}`}
                        points={s}
                        fill="none"
                        stroke={color}
                        strokeWidth={strokeW}
                      />
                    );
                  })
                )}
              </>
            ) : (
              <>
                {rectUrl && project ? (
                  <SvgImage
                    href={{ uri: rectUrl }}
                    x={0}
                    y={0}
                    width={imgW}
                    height={imgH}
                    preserveAspectRatio="none"
                    opacity={0.55}
                  />
                ) : null}
                <G>
                  {gridLines.map((l, i) => (
                    <Line key={i} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} stroke={colors.divider} strokeWidth={sw * 0.5} />
                  ))}
                </G>
                {/* elements */}
                {elements.map((el) =>
                  el.polylines.map((pl, j) => {
                    const s = ptsStr(pl);
                    if (!s) return null;
                    return (
                      <Polyline
                        key={`${el.id}_${j}`}
                        points={s}
                        fill="none"
                        stroke={selElement === el.id ? colors.brand : el.layer === "CUT" ? colors.cut : colors.engrave}
                        strokeWidth={selElement === el.id ? sw * 2 : sw}
                      />
                    );
                  })
                )}
                {/* main contour */}
                {contour.length >= 3 && (
                  filletedContour ? (
                    <>
                      {/* sharp source outline, dimmed */}
                      <Polygon points={ptsStr(contour)} fill="none" stroke={colors.brand} strokeWidth={sw * 0.7} strokeOpacity={0.35} strokeDasharray={`${sw * 3},${sw * 3}`} />
                      {/* filleted (rounded) result */}
                      <Polygon points={ptsStr(filletedContour)} fill="rgba(255,69,0,0.10)" stroke={colors.brand} strokeWidth={sw * 1.4} />
                    </>
                  ) : (
                    <Polygon points={ptsStr(contour)} fill="rgba(255,69,0,0.10)" stroke={colors.brand} strokeWidth={sw * 1.4} />
                  )
                )}
                {/* nodes */}
                {mode === "points" &&
                  contour.map((p, i) => (
                    <Circle
                      key={i}
                      cx={p[0]}
                      cy={p[1]}
                      r={selNode === i ? nodeR * 1.5 : nodeR}
                      fill={selNode === i ? colors.brand : colors.surface}
                      stroke={colors.borderStrong}
                      strokeWidth={sw}
                    />
                  ))}
              </>
            )}
          </Svg>
        </GestureDetector>

        {/* teak preview toggle */}
        <Pressable
          testID="teak-toggle"
          onPress={() => setTeak((t) => !t)}
          style={[styles.teakToggle, teak && { backgroundColor: TEAK, borderColor: TEAK_EDGE }]}
        >
          <MaterialCommunityIcons name={teak ? "eye-off" : "palette"} size={16} color={teak ? "#FFF" : colors.onSurface} />
          <Text style={[styles.teakToggleText, teak && { color: "#FFF" }]}>{teak ? "VETTORI" : "ANTEPRIMA TEAK"}</Text>
        </Pressable>

        {/* zoom controls */}
        <View style={styles.zoomCol}>
          <Pressable testID="zoom-in" style={styles.zoomBtn} onPress={() => zoom(0.7)}>
            <Feather name="plus" size={18} color={colors.onSurface} />
          </Pressable>
          <Pressable testID="zoom-out" style={styles.zoomBtn} onPress={() => zoom(1.4)}>
            <Feather name="minus" size={18} color={colors.onSurface} />
          </Pressable>
          <Pressable testID="zoom-fit" style={styles.zoomBtn} onPress={fitView}>
            <MaterialCommunityIcons name="fit-to-screen-outline" size={18} color={colors.onSurface} />
          </Pressable>
        </View>
        <View style={[styles.gridBadge, { pointerEvents: "none" }]}>
          <Text style={styles.gridBadgeText}>GRID {gridStep}mm</Text>
        </View>
      </View>

      {/* mode switch */}
      <View style={styles.modeWrap}>
        <Segmented
          testID="editor-mode"
          value={mode}
          onChange={(v) => setMode(v as any)}
          options={[
            { label: "PUNTI", value: "points" },
            { label: "TEXTURE", value: "texture" },
          ]}
        />
      </View>

      {/* bottom panel */}
      <View style={[styles.panel, { paddingBottom: insets.bottom + space.sm }]}>
        {mode === "points" ? (
          <PointsPanel
            step={step}
            setStep={setStep}
            selected={selNode !== null}
            nudge={nudge}
            addNode={addNode}
            delNode={delNode}
            rotatePiece={rotatePiece}
            offset={offset}
            setOffset={setOffset}
            fillet={fillet}
            setFillet={setFillet}
            onApply={async () => {
              if (await save()) toast("Parametri salvati", "success");
            }}
          />
        ) : (
          <TexturePanel
            elements={elements}
            selId={selElement}
            step={step}
            setStep={setStep}
            onSelect={(id: string) => setSelElement(id)}
            onDeselect={() => setSelElement(null)}
            onMove={moveEl}
            onRotate={rotateEl}
            onScale={scaleEl}
            onAdd={() => setAddOpen(true)}
            onFill={() => setFillOpen(true)}
            onPreset={applyPreset}
            onDelete={delElement}
          />
        )}
      </View>

      {/* add-element modal */}
      <Modal visible={addOpen} transparent animationType="slide" onRequestClose={() => setAddOpen(false)}>
        <View style={styles.modalRoot}>
          <View style={styles.modalCard}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>AGGIUNGI ELEMENTO</Text>
              <Pressable testID="modal-close" onPress={() => setAddOpen(false)} hitSlop={10}>
                <Feather name="x" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: space.lg }}>
              <Text style={styles.modalLabel}>Tipo</Text>
              <View style={styles.typeGrid}>
                {(["text", "svg", "dxf", "track", "rect", "circle", "line", "junction"] as const).map((t) => (
                  <Pressable
                    key={t}
                    testID={`type-${t}`}
                    onPress={() => { setElType(t); if (t === "junction") setSizeVal(String(Math.round(bboxOf(contour).w))); }}
                    style={[styles.typeChip, elType === t && { backgroundColor: colors.surfaceInverse }]}
                  >
                    <Text style={[styles.typeChipText, elType === t && { color: colors.onSurfaceInverse }]}>
                      {t === "junction" ? "GIUNZIONE" : t === "dxf" ? "LOGO DXF" : t.toUpperCase()}
                    </Text>
                  </Pressable>
                ))}
              </View>

              {elType === "text" && (
                <ModalField label="Testo" testID="modal-text" value={textVal} onChangeText={setTextVal} placeholder="Scrivi qui il testo" />
              )}
              {elType === "svg" && (
                <>
                  <Pressable
                    testID="svg-import-file"
                    onPress={pickSvgFile}
                    disabled={svgPicking}
                    style={styles.importBtn}
                  >
                    {svgPicking ? (
                      <ActivityIndicator size="small" color={colors.onSurfaceInverse} />
                    ) : (
                      <>
                        <Feather name="upload" size={16} color={colors.onSurfaceInverse} />
                        <Text style={styles.importBtnText}>IMPORTA FILE SVG</Text>
                      </>
                    )}
                  </Pressable>
                  {svgFileName ? (
                    <Text style={styles.importFileName} numberOfLines={1}>
                      ✓ {svgFileName}
                    </Text>
                  ) : null}
                  <ModalField label="SVG (path)" testID="modal-svg" value={svgVal} onChangeText={setSvgVal} placeholder="Importa un file .svg o incolla qui il codice" multiline />
                </>
              )}
              {elType === "dxf" && (
                <>
                  <Pressable
                    testID="dxf-import-file"
                    onPress={pickDxfFile}
                    disabled={dxfPicking}
                    style={styles.importBtn}
                  >
                    {dxfPicking ? (
                      <ActivityIndicator size="small" color={colors.onSurfaceInverse} />
                    ) : (
                      <>
                        <Feather name="upload" size={16} color={colors.onSurfaceInverse} />
                        <Text style={styles.importBtnText}>IMPORTA FILE DXF</Text>
                      </>
                    )}
                  </Pressable>
                  {dxfFileName ? (
                    <Text style={styles.importFileName} numberOfLines={1}>
                      ✓ {dxfFileName}
                    </Text>
                  ) : (
                    <Text style={styles.modalHint}>Importa un logo/disegno da file .dxf (linee, polilinee, cerchi, archi, spline). Verrà scalato alla dimensione scelta e posizionato al centro.</Text>
                  )}
                </>
              )}
              {(elType === "text" || elType === "svg" || elType === "dxf" || elType === "rect" || elType === "circle" || elType === "line") && (
                <ModalField
                  label={elType === "text" ? "Altezza (mm)" : elType === "circle" ? "Diametro (mm)" : elType === "dxf" || elType === "svg" ? "Larghezza (mm)" : "Dimensione (mm)"}
                  testID="modal-size"
                  value={sizeVal}
                  onChangeText={setSizeVal}
                  keyboardType="decimal-pad"
                />
              )}
              {elType === "track" && (
                <>
                  <ModalField label="Passo (mm)" testID="modal-spacing" value={spacingVal} onChangeText={setSpacingVal} keyboardType="decimal-pad" />
                  <ModalField label="Angolo (°)" testID="modal-angle" value={angleVal} onChangeText={setAngleVal} keyboardType="decimal-pad" />
                </>
              )}
              {elType === "junction" && (
                <>
                  <Text style={styles.modalHint}>Giunzione: sembra un'incisione ma è un TAGLIO. Divide un tappeto grande/complesso (es. attorno alla consolle) in più parti da accostare — il tappeto è adesivo, quindi basta appoggiarle una accanto all'altra. Posiziona/ruota/allunga la linea con le frecce dopo l'inserimento.</Text>
                  <ModalField label="Lunghezza (mm)" testID="modal-size" value={sizeVal} onChangeText={setSizeVal} keyboardType="decimal-pad" />
                </>
              )}

              {elType !== "junction" && (
                <>
                  <Text style={styles.modalLabel}>Layer DXF</Text>
                  <Segmented<Layer>
                    testID="modal-layer"
                    value={elLayer}
                    onChange={setElLayer}
                    options={[
                      { label: "INCISIONE", value: "ENGRAVE" },
                      { label: "TAGLIO", value: "CUT" },
                    ]}
                  />
                </>
              )}
              <View style={{ height: space.lg }} />
              <Btn testID="modal-confirm" label="AGGIUNGI" loading={addBusy} onPress={confirmAdd} />
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* fill-area modal */}
      <Modal visible={fillOpen} transparent animationType="slide" onRequestClose={() => setFillOpen(false)}>
        <View style={styles.modalRoot}>
          <View style={styles.modalCard}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>RIEMPI AREA</Text>
              <Pressable testID="fill-close" onPress={() => setFillOpen(false)} hitSlop={10}>
                <Feather name="x" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: space.lg }}>
              {fillStyle !== "bordo" && (
              <>
              <Text style={styles.modalLabel}>Texture</Text>
              <View style={styles.typeGrid}>
                {([
                  { k: "diamond", label: "DIAMANTE" },
                  { k: "cross", label: "INCROCIATO" },
                  { k: "lines", label: "RIGHE" },
                ] as const).map((t) => (
                  <Pressable
                    key={t.k}
                    testID={`fill-pattern-${t.k}`}
                    onPress={() => setFillPattern(t.k)}
                    style={[styles.typeChip, fillPattern === t.k && { backgroundColor: colors.surfaceInverse }]}
                  >
                    <Text style={[styles.typeChipText, fillPattern === t.k && { color: colors.onSurfaceInverse }]}>{t.label}</Text>
                  </Pressable>
                ))}
              </View>

              <ModalField
                label={fillPattern === "lines" ? "Larghezza doga (mm)" : fillPattern === "diamond" ? "Larghezza diamante (mm)" : "Passo (mm)"}
                testID="fill-spacing"
                value={fillSpacing}
                onChangeText={setFillSpacing}
                keyboardType="decimal-pad"
              />

              {fillPattern === "diamond" && (
                <ModalField
                  label="Altezza diamante (mm)"
                  testID="fill-diamond-height"
                  value={fillDiamondHeight}
                  onChangeText={setFillDiamondHeight}
                  keyboardType="decimal-pad"
                />
              )}
              <Text style={styles.modalLabel}>Orientamento doghe</Text>
              <View style={styles.typeGrid}>
                <Pressable
                  testID="fill-angle-auto"
                  onPress={() => setFillAuto(true)}
                  style={[styles.typeChip, fillAuto && { backgroundColor: colors.brand, borderColor: colors.brand }]}
                >
                  <Text style={[styles.typeChipText, fillAuto && { color: colors.onBrand }]}>AUTO ↳ BORDO</Text>
                </Pressable>
                {([
                  { a: "0", label: "0°" },
                  { a: "45", label: "45°" },
                  { a: "90", label: "90°" },
                ] as const).map((o) => (
                  <Pressable
                    key={o.a}
                    testID={`fill-angle-${o.a}`}
                    onPress={() => { setFillAuto(false); setFillAngle(o.a); }}
                    style={[styles.typeChip, !fillAuto && fillAngle === o.a && { backgroundColor: colors.surfaceInverse }]}
                  >
                    <Text style={[styles.typeChipText, !fillAuto && fillAngle === o.a && { color: colors.onSurfaceInverse }]}>{o.label}</Text>
                  </Pressable>
                ))}
                <View style={{ flexBasis: "100%" }} />
                <View style={{ flex: 1 }}>
                  <ModalField
                    label="Angolo custom (°)"
                    testID="fill-angle"
                    value={fillAngle}
                    onChangeText={(t: string) => { setFillAuto(false); setFillAngle(t); }}
                    keyboardType="decimal-pad"
                  />
                </View>
              </View>

              <View style={styles.rotRow}>
                <Pressable testID="rot-m15" style={styles.rotBtn} onPress={() => bumpAngle(-15)}>
                  <Text style={styles.rotBtnText}>−15°</Text>
                </Pressable>
                <Pressable testID="rot-m5" style={styles.rotBtn} onPress={() => bumpAngle(-5)}>
                  <Text style={styles.rotBtnText}>−5°</Text>
                </Pressable>
                <View style={styles.rotVal}>
                  <MaterialCommunityIcons name="rotate-right" size={14} color={colors.brand} />
                  <Text style={styles.rotValText}>{fillAuto ? "AUTO" : `${Math.round(parseFloat(fillAngle) || 0)}°`}</Text>
                </View>
                <Pressable testID="rot-p5" style={styles.rotBtn} onPress={() => bumpAngle(5)}>
                  <Text style={styles.rotBtnText}>+5°</Text>
                </Pressable>
                <Pressable testID="rot-p15" style={styles.rotBtn} onPress={() => bumpAngle(15)}>
                  <Text style={styles.rotBtnText}>+15°</Text>
                </Pressable>
              </View>
              </>
              )}

              <ModalField label="Spessore solco caulking (mm)" testID="fill-groove" value={fillGroove} onChangeText={setFillGroove} keyboardType="decimal-pad" />

              {fillStyle !== "bordo" && (
                <ModalField label="Lunghezza doga · sfalsata (mm, 0 = continua)" testID="fill-board" value={fillBoard} onChangeText={setFillBoard} keyboardType="decimal-pad" />
              )}

              <ModalField label="Area pulita attorno a scritte, loghi, cerchi ed elementi (mm, 0 = off)" testID="fill-clear" value={fillClearMargin} onChangeText={setFillClearMargin} keyboardType="decimal-pad" />

              <Text style={styles.modalLabel}>Stile</Text>
              <Segmented<"semplice" | "bordato" | "bordo">
                testID="fill-style"
                value={fillStyle}
                onChange={setFillStyle}
                options={[
                  { label: "SEMPLICE", value: "semplice" },
                  { label: "BORDATO", value: "bordato" },
                  { label: "SOLO BORDO", value: "bordo" },
                ]}
              />
              {fillStyle === "bordo" && (
                <Text style={styles.modalHint}>Solo la bordatura perimetrale con i solchi d'angolo, senza doghe interne.</Text>
              )}
              <View style={{ height: space.md }} />
              {(fillStyle === "bordato" || fillStyle === "bordo") && (
                <>
                  <ModalField label="Margine bordo (mm)" testID="fill-border" value={fillBorder} onChangeText={setFillBorder} keyboardType="decimal-pad" />
                  <ModalField label="Raggio angoli bordatura (mm)" testID="fill-corner" value={fillCornerRadius} onChangeText={setFillCornerRadius} keyboardType="decimal-pad" />
                </>
              )}
              {(fillPattern === "lines" && fillStyle !== "bordo") && (
                <ModalField label="Svaso estremità doghe (mm, 0 = off)" testID="fill-ease" value={fillPlankEase} onChangeText={setFillPlankEase} keyboardType="decimal-pad" />
              )}

              <Text style={styles.modalLabel}>Layer DXF</Text>
              <Segmented<Layer>
                testID="fill-layer"
                value={fillLayer}
                onChange={setFillLayer}
                options={[
                  { label: "INCISIONE", value: "ENGRAVE" },
                  { label: "TAGLIO", value: "CUT" },
                ]}
              />
              <View style={{ height: space.lg }} />
              <Btn testID="fill-confirm" label="RIEMPI" loading={fillBusy} onPress={confirmFill} />
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function ModalField({ label, ...props }: any) {
  return (
    <View style={{ marginBottom: space.md }}>
      <Text style={styles.modalLabel}>{label}</Text>
      <TextInput
        {...props}
        placeholderTextColor={colors.onSurfaceTertiary}
        style={[styles.modalInput, props.multiline && { height: 80, textAlignVertical: "top" }]}
      />
    </View>
  );
}

function PointsPanel(props: any) {
  const { step, setStep, selected, nudge, addNode, delNode, rotatePiece, offset, setOffset, fillet, setFillet, onApply } = props;
  return (
    <View>
      <View style={styles.padRow}>
        <View style={styles.dpad}>
          <Pressable testID="nudge-up" style={styles.dbtn} onPress={() => nudge(0, -step)} disabled={!selected}>
            <Feather name="arrow-up" size={18} color={selected ? colors.onSurface : colors.border} />
          </Pressable>
          <View style={styles.dpadMid}>
            <Pressable testID="nudge-left" style={styles.dbtn} onPress={() => nudge(-step, 0)} disabled={!selected}>
              <Feather name="arrow-left" size={18} color={selected ? colors.onSurface : colors.border} />
            </Pressable>
            <View style={[styles.dbtn, { borderColor: colors.brand }]}>
              <Text style={styles.stepText}>{step}mm</Text>
            </View>
            <Pressable testID="nudge-right" style={styles.dbtn} onPress={() => nudge(step, 0)} disabled={!selected}>
              <Feather name="arrow-right" size={18} color={selected ? colors.onSurface : colors.border} />
            </Pressable>
          </View>
          <Pressable testID="nudge-down" style={styles.dbtn} onPress={() => nudge(0, step)} disabled={!selected}>
            <Feather name="arrow-down" size={18} color={selected ? colors.onSurface : colors.border} />
          </Pressable>
        </View>

        <View style={{ flex: 1, gap: space.sm }}>
          <View style={styles.stepChips}>
            {[0.5, 1, 5, 10].map((s) => (
              <Pressable key={s} testID={`step-${s}`} onPress={() => setStep(s)} style={[styles.stepChip, step === s && { backgroundColor: colors.surfaceInverse }]}>
                <Text style={[styles.stepChipText, step === s && { color: colors.onSurfaceInverse }]}>{s}</Text>
              </Pressable>
            ))}
          </View>
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <Pressable testID="add-node" onPress={addNode} style={styles.actBtn}>
              <Feather name="plus" size={16} color={colors.onSurface} />
              <Text style={styles.actText}>PUNTO</Text>
            </Pressable>
            <Pressable testID="del-node" onPress={delNode} style={[styles.actBtn, { borderColor: colors.error }]} disabled={!selected}>
              <Feather name="trash-2" size={16} color={selected ? colors.error : colors.border} />
              <Text style={[styles.actText, { color: selected ? colors.error : colors.border }]}>ELIMINA</Text>
            </Pressable>
          </View>
        </View>
      </View>

      <View style={styles.rotateRow}>
        <Text style={styles.rotLabel}>RUOTA PEZZO</Text>
        <View style={styles.rotBtns}>
          <Pressable testID="rot-90ccw" style={styles.rotBtn} onPress={() => rotatePiece(-90)}>
            <Feather name="rotate-ccw" size={15} color={colors.onSurface} />
            <Text style={styles.rotText}>90°</Text>
          </Pressable>
          <Pressable testID="rot-1ccw" style={styles.rotBtn} onPress={() => rotatePiece(-1)}>
            <Text style={styles.rotText}>−1°</Text>
          </Pressable>
          <Pressable testID="rot-1cw" style={styles.rotBtn} onPress={() => rotatePiece(1)}>
            <Text style={styles.rotText}>+1°</Text>
          </Pressable>
          <Pressable testID="rot-90cw" style={styles.rotBtn} onPress={() => rotatePiece(90)}>
            <Feather name="rotate-cw" size={15} color={colors.onSurface} />
            <Text style={styles.rotText}>90°</Text>
          </Pressable>
        </View>
      </View>

      <View style={styles.offsetRow}>
        <View style={styles.miniField}>
          <Text style={styles.miniLabel}>OFFSET LAMA</Text>
          <View style={styles.miniInputWrap}>
            <TextInput testID="offset-input" value={offset} onChangeText={setOffset} keyboardType="decimal-pad" style={styles.miniInput} />
            <Text style={styles.miniUnit}>mm</Text>
          </View>
        </View>
        <View style={styles.miniField}>
          <Text style={styles.miniLabel}>RACCORDO</Text>
          <View style={styles.miniInputWrap}>
            <TextInput testID="fillet-input" value={fillet} onChangeText={setFillet} keyboardType="decimal-pad" style={styles.miniInput} />
            <Text style={styles.miniUnit}>mm</Text>
          </View>
          <View style={styles.presetRow}>
            {["0", "5", "10", "20"].map((v) => (
              <Pressable key={v} testID={`fillet-${v}`} onPress={() => setFillet(v)} style={[styles.presetChip, fillet === v && styles.presetChipOn]}>
                <Text style={[styles.presetText, fillet === v && styles.presetTextOn]}>{v}</Text>
              </Pressable>
            ))}
          </View>
        </View>
        <Pressable testID="apply-params" onPress={onApply} style={styles.applyBtn}>
          <Feather name="check" size={18} color={colors.onBrand} />
          <Text style={styles.applyText}>APPLICA</Text>
        </Pressable>
      </View>
    </View>
  );
}

function TexturePanel({ elements, selId, step, setStep, onSelect, onDeselect, onMove, onRotate, onScale, onAdd, onFill, onPreset, onDelete }: any) {
  const sel = elements.find((e: ElementT) => e.id === selId);
  if (sel) {
    return (
      <View>
        <View style={styles.selHead}>
          <Text style={styles.selTitle}>SPOSTA · {sel.type.toUpperCase()}</Text>
          <Pressable testID="deselect-element" onPress={onDeselect} hitSlop={10} style={styles.selDone}>
            <Feather name="check" size={16} color={colors.onBrand} />
            <Text style={styles.selDoneText}>FATTO</Text>
          </Pressable>
        </View>
        <View style={styles.padRow}>
          <View style={styles.dpad}>
            <Pressable testID="el-up" style={styles.dbtn} onPress={() => onMove(0, -step)}>
              <Feather name="arrow-up" size={18} color={colors.onSurface} />
            </Pressable>
            <View style={styles.dpadMid}>
              <Pressable testID="el-left" style={styles.dbtn} onPress={() => onMove(-step, 0)}>
                <Feather name="arrow-left" size={18} color={colors.onSurface} />
              </Pressable>
              <View style={[styles.dbtn, { borderColor: colors.brand }]}>
                <Text style={styles.stepText}>{step}mm</Text>
              </View>
              <Pressable testID="el-right" style={styles.dbtn} onPress={() => onMove(step, 0)}>
                <Feather name="arrow-right" size={18} color={colors.onSurface} />
              </Pressable>
            </View>
            <Pressable testID="el-down" style={styles.dbtn} onPress={() => onMove(0, step)}>
              <Feather name="arrow-down" size={18} color={colors.onSurface} />
            </Pressable>
          </View>
          <View style={{ flex: 1, gap: space.sm }}>
            <View style={styles.stepChips}>
              {[1, 5, 10, 25].map((s) => (
                <Pressable key={s} testID={`el-step-${s}`} onPress={() => setStep(s)} style={[styles.stepChip, step === s && { backgroundColor: colors.surfaceInverse }]}>
                  <Text style={[styles.stepChipText, step === s && { color: colors.onSurfaceInverse }]}>{s}</Text>
                </Pressable>
              ))}
            </View>
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Pressable testID="el-rot-l" style={styles.actBtn} onPress={() => onRotate(-15)}>
                <MaterialCommunityIcons name="rotate-left" size={16} color={colors.onSurface} />
                <Text style={styles.actText}>−15°</Text>
              </Pressable>
              <Pressable testID="el-rot-r" style={styles.actBtn} onPress={() => onRotate(15)}>
                <MaterialCommunityIcons name="rotate-right" size={16} color={colors.onSurface} />
                <Text style={styles.actText}>+15°</Text>
              </Pressable>
            </View>
            <View style={{ flexDirection: "row", gap: space.sm }}>
              <Pressable testID="el-scale-down" style={styles.actBtn} onPress={() => onScale(0.9)}>
                <Feather name="minimize-2" size={16} color={colors.onSurface} />
                <Text style={styles.actText}>PICCOLO</Text>
              </Pressable>
              <Pressable testID="el-scale-up" style={styles.actBtn} onPress={() => onScale(1.1)}>
                <Feather name="maximize-2" size={16} color={colors.onSurface} />
                <Text style={styles.actText}>GRANDE</Text>
              </Pressable>
              <Pressable testID="el-delete" style={[styles.actBtn, { borderColor: colors.error }]} onPress={() => onDelete(sel.id)}>
                <Feather name="trash-2" size={16} color={colors.error} />
              </Pressable>
            </View>
          </View>
        </View>
      </View>
    );
  }
  return (
    <View>
      <Text style={styles.presetLabel}>LIBRERIA TEXTURE · UN TOCCO</Text>
      <View style={styles.presetRow}>
        <Pressable testID="preset-doghe" style={styles.presetChip} onPress={() => onPreset("doghe")}>
          <MaterialCommunityIcons name="format-line-spacing" size={18} color={colors.onSurface} />
          <Text style={styles.presetText}>DOGHE 60</Text>
        </Pressable>
        <Pressable testID="preset-diamante" style={styles.presetChip} onPress={() => onPreset("diamante")}>
          <MaterialCommunityIcons name="rhombus-outline" size={18} color={colors.onSurface} />
          <Text style={styles.presetText}>DIAMANTE</Text>
        </Pressable>
        <Pressable testID="preset-incrociato" style={styles.presetChip} onPress={() => onPreset("incrociato")}>
          <MaterialCommunityIcons name="grid" size={18} color={colors.onSurface} />
          <Text style={styles.presetText}>INCROCIATO</Text>
        </Pressable>
      </View>
      <View style={{ height: space.sm }} />
      <View style={{ flexDirection: "row", gap: space.sm }}>
        <Pressable testID="fill-area-btn" onPress={onFill} style={[styles.fillBtn, { flex: 1 }]}>
          <MaterialCommunityIcons name="tune-variant" size={16} color={colors.onSurfaceInverse} />
          <Text style={styles.fillText}>RIEMPI</Text>
        </Pressable>
        <Pressable testID="add-element-btn" onPress={onAdd} style={[styles.fillBtn, { flex: 1, backgroundColor: colors.brand }]}>
          <Feather name="plus" size={16} color={colors.onBrand} />
          <Text style={[styles.fillText, { color: colors.onBrand }]}>SCRITTA / LOGO</Text>
        </Pressable>
      </View>
      <ScrollView style={{ maxHeight: 92, marginTop: space.sm }}>
        {elements.length === 0 ? (
          <Text style={styles.emptyEl}>Tocca un elemento sul disegno per spostarlo, oppure aggiungi scritta/logo.</Text>
        ) : (
          elements.map((el: ElementT) => (
            <Pressable key={el.id} style={styles.elRow} testID={`element-${el.id}`} onPress={() => onSelect(el.id)}>
              <View style={[styles.elDot, { backgroundColor: el.layer === "CUT" ? colors.cut : colors.engrave }]} />
              <Text style={styles.elName}>{el.type.toUpperCase()}</Text>
              <Text style={styles.elLayer}>{el.layer}</Text>
              <Feather name="move" size={15} color={colors.onSurfaceTertiary} />
              <Pressable testID={`del-element-${el.id}`} onPress={() => onDelete(el.id)} hitSlop={8}>
                <Feather name="trash-2" size={16} color={colors.error} />
              </Pressable>
            </Pressable>
          ))
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, gap: space.md },
  loadText: { fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onSurfaceSecondary, letterSpacing: 1 },
  topbar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: space.lg, paddingVertical: space.md,
    borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong,
  },
  title: { flex: 1, textAlign: "center", fontFamily: fonts.display, fontSize: fontSize.lg, color: colors.onSurface, marginHorizontal: space.md },
  measureBar: {
    flexDirection: "row", justifyContent: "space-between",
    paddingHorizontal: space.lg, paddingVertical: space.sm,
    backgroundColor: colors.surfaceInverse,
  },
  measure: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurfaceInverse },
  canvasWrap: { flex: 1, backgroundColor: colors.surfaceSecondary, borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong },
  zoomCol: { position: "absolute", right: space.md, top: space.md, gap: space.sm },
  zoomBtn: {
    width: 40, height: 40, backgroundColor: colors.surface,
    borderWidth: BORDER, borderColor: colors.borderStrong, alignItems: "center", justifyContent: "center",
  },
  gridBadge: { position: "absolute", left: space.md, bottom: space.md, backgroundColor: colors.surfaceInverse, paddingHorizontal: space.sm, paddingVertical: 3 },
  teakToggle: {
    position: "absolute", left: space.md, top: space.md, flexDirection: "row", gap: 6, alignItems: "center",
    backgroundColor: colors.surface, borderWidth: BORDER, borderColor: colors.borderStrong,
    paddingHorizontal: space.sm, paddingVertical: 7,
  },
  teakToggleText: { fontFamily: fonts.monoBold, fontSize: 11, color: colors.onSurface, letterSpacing: 0.3 },
  gridBadgeText: { fontFamily: fonts.mono, fontSize: 10, color: colors.onSurfaceInverse },
  modeWrap: { paddingHorizontal: space.lg, paddingTop: space.sm },
  panel: { paddingHorizontal: space.lg, paddingTop: space.sm, borderTopWidth: 0 },
  padRow: { flexDirection: "row", gap: space.md, alignItems: "center" },
  dpad: { alignItems: "center", gap: 4 },
  dpadMid: { flexDirection: "row", gap: 4, alignItems: "center" },
  dbtn: {
    width: 40, height: 40, borderWidth: BORDER, borderColor: colors.borderStrong,
    alignItems: "center", justifyContent: "center", backgroundColor: colors.surface,
  },
  stepText: { fontFamily: fonts.monoBold, fontSize: 11, color: colors.brand },
  stepChips: { flexDirection: "row", gap: space.sm },
  rotateRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: space.sm, marginBottom: space.xs },
  rotLabel: { fontFamily: fonts.monoMed, fontSize: 11, color: colors.onSurfaceSecondary, textTransform: "uppercase" },
  rotBtns: { flexDirection: "row", gap: space.sm },
  rotBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, minWidth: 52, justifyContent: "center",
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: 8, paddingHorizontal: 8,
    backgroundColor: colors.surface,
  },
  rotText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  stepChip: { flex: 1, borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: 6, alignItems: "center", backgroundColor: colors.surface },
  stepChipText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  actBtn: {
    flex: 1, flexDirection: "row", gap: 6, alignItems: "center", justifyContent: "center",
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: 8, backgroundColor: colors.surface,
  },
  actText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  offsetRow: { flexDirection: "row", gap: space.sm, alignItems: "flex-end", marginTop: space.md },
  miniField: { flex: 1 },
  miniLabel: { fontFamily: fonts.mono, fontSize: 10, color: colors.onSurfaceSecondary, marginBottom: 2 },
  miniInputWrap: { flexDirection: "row", alignItems: "center", borderWidth: BORDER, borderColor: colors.borderStrong },
  miniInput: { flex: 1, fontFamily: fonts.mono, fontSize: fontSize.base, color: colors.onSurface, paddingHorizontal: space.sm, paddingVertical: 8 },
  miniUnit: { fontFamily: fonts.monoBold, fontSize: 11, color: colors.onSurfaceTertiary, paddingHorizontal: 6 },
  presetRow: { flexDirection: "row", gap: 4, marginTop: 4 },
  presetChip: { flex: 1, alignItems: "center", paddingVertical: 4, borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface },
  presetChipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  presetText: { fontFamily: fonts.monoMed, fontSize: 11, color: colors.onSurface },
  presetTextOn: { color: colors.onBrand },
  applyBtn: {
    flexDirection: "row", gap: 6, alignItems: "center", backgroundColor: colors.brand,
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 10,
  },
  applyText: { fontFamily: fonts.display, fontSize: fontSize.base, color: colors.onBrand },
  emptyEl: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, paddingVertical: space.md },
  fillBtn: {
    flexDirection: "row", gap: space.sm, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceInverse, borderWidth: BORDER, borderColor: colors.borderStrong,
    paddingVertical: space.md,
  },
  fillText: { fontFamily: fonts.display, fontSize: fontSize.base, color: colors.onSurfaceInverse, letterSpacing: 0.5 },
  presetLabel: { fontFamily: fonts.mono, fontSize: 10, color: colors.onSurfaceSecondary, letterSpacing: 1, marginBottom: space.xs },
  presetRow: { flexDirection: "row", gap: space.sm },
  presetChip: {
    flex: 1, alignItems: "center", justifyContent: "center", gap: 3, paddingVertical: space.sm,
    borderWidth: BORDER, borderColor: colors.brand, backgroundColor: colors.brandTertiary,
  },
  presetText: { fontFamily: fonts.monoBold, fontSize: 10, color: colors.onSurface, letterSpacing: 0.3 },
  rotRow: { flexDirection: "row", gap: space.sm, alignItems: "center", marginBottom: space.md },
  rotBtn: {
    flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 8,
    borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface,
  },
  rotBtnText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  rotVal: {
    flexDirection: "row", gap: 4, alignItems: "center", justifyContent: "center",
    minWidth: 64, paddingVertical: 8, borderWidth: BORDER, borderColor: colors.brand, backgroundColor: colors.brandTertiary,
  },
  rotValText: { fontFamily: fonts.monoBold, fontSize: fontSize.sm, color: colors.onSurface },
  selHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: space.sm },
  selTitle: { fontFamily: fonts.display, fontSize: fontSize.base, color: colors.onSurface, letterSpacing: 0.5 },
  selDone: { flexDirection: "row", gap: 4, alignItems: "center", backgroundColor: colors.brand, borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 6 },
  selDoneText: { fontFamily: fonts.monoBold, fontSize: fontSize.sm, color: colors.onBrand },
  elRow: {
    flexDirection: "row", alignItems: "center", gap: space.sm, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  elDot: { width: 12, height: 12 },
  elName: { flex: 1, fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onSurface },
  elLayer: { fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceTertiary },
  modalRoot: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalCard: { backgroundColor: colors.surface, borderTopWidth: BORDER, borderColor: colors.borderStrong, maxHeight: "85%" },
  modalHead: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: space.lg, borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong,
  },
  modalTitle: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  modalLabel: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: space.xs, textTransform: "uppercase" },
  modalHint: { fontFamily: fonts.mono, fontSize: 12, color: colors.onSurfaceSecondary, marginBottom: space.md, lineHeight: 17 },
  typeGrid: { flexDirection: "row", flexWrap: "wrap", gap: space.sm, marginBottom: space.lg },
  typeChip: { borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 8, backgroundColor: colors.surface },
  typeChipText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  importBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space.sm, borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surfaceInverse, paddingVertical: 12, marginBottom: space.sm },
  importBtnText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurfaceInverse, textTransform: "uppercase", letterSpacing: 0.5 },
  importFileName: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.brand, marginBottom: space.md },
  modalInput: {
    borderWidth: BORDER, borderColor: colors.borderStrong, fontFamily: fonts.mono,
    fontSize: fontSize.base, color: colors.onSurface, paddingHorizontal: space.md, paddingVertical: space.md,
  },
});
