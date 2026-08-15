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

import { absUrl, api, ElementT, Layer, ProjectT } from "@/src/api";
import { Btn, Segmented } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

type Pt = number[];
const uid = () => `${Date.now()}_${Math.floor(Math.random() * 1e5)}`;

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
const ptsStr = (arr: Pt[]) => arr.map((p) => `${p[0]},${p[1]}`).join(" ");

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
  const [mode, setMode] = useState<"points" | "texture">("points");
  const [step, setStep] = useState(1);
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
  const [elType, setElType] = useState<"text" | "track" | "rect" | "circle" | "line" | "svg">("text");
  const [elLayer, setElLayer] = useState<Layer>("ENGRAVE");
  const [textVal, setTextVal] = useState("EVA");
  const [sizeVal, setSizeVal] = useState("40");
  const [spacingVal, setSpacingVal] = useState("15");
  const [angleVal, setAngleVal] = useState("45");
  const [svgVal, setSvgVal] = useState(
    '<svg viewBox="0 0 100 100"><path d="M50 5 L61 39 L97 39 L68 61 L79 95 L50 74 L21 95 L32 61 L3 39 L39 39 Z"/></svg>'
  );
  const [addBusy, setAddBusy] = useState(false);

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

  const save = useCallback(
    async (extra: any = {}) => {
      if (!id) return;
      const body = {
        contour_mm: contour,
        elements,
        blade_offset_mm: parseFloat(offset) || 0,
        fillet_radius_mm: parseFloat(fillet) || 0,
        status: "edited",
        ...extra,
      };
      await api.updateProject(id, body);
    },
    [id, contour, elements, offset, fillet]
  );

  const onBack = async () => {
    try { await save(); } catch {}
    router.replace("/");
  };
  const goExport = async () => {
    setSaving(true);
    try {
      await save();
      router.push(`/export/${id}` as any);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
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
      }
      if (!polylines.length) throw new Error("Nessuna geometria generata");
      const el: ElementT = { id: uid(), type: elType, layer: elLayer, polylines, params: {} };
      const next = [...elements, el];
      setElements(next);
      await save({ elements: next });
      setAddOpen(false);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast("Elemento aggiunto", "success");
    } catch (e: any) {
      toast(e.message || "Errore aggiunta elemento", "error");
    } finally {
      setAddBusy(false);
    }
  };

  const delElement = async (eid: string) => {
    const next = elements.filter((e) => e.id !== eid);
    setElements(next);
    await save({ elements: next });
  };

  const bb = useMemo(() => bboxOf(contour), [contour]);
  const perim = useMemo(() => perimeter(contour), [contour]);
  const rectUrl = absUrl(project?.rectified_url);

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
            {rectUrl && project ? (
              <SvgImage
                href={{ uri: rectUrl }}
                x={0}
                y={0}
                width={project.ref_width_mm}
                height={project.ref_height_mm}
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
              el.polylines.map((pl, j) => (
                <Polyline
                  key={`${el.id}_${j}`}
                  points={ptsStr(pl)}
                  fill="none"
                  stroke={el.layer === "CUT" ? colors.cut : colors.engrave}
                  strokeWidth={sw}
                />
              ))
            )}
            {/* main contour */}
            {contour.length >= 3 && (
              <Polygon points={ptsStr(contour)} fill="rgba(255,69,0,0.10)" stroke={colors.brand} strokeWidth={sw * 1.4} />
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
          </Svg>
        </GestureDetector>

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
        <View style={styles.gridBadge} pointerEvents="none">
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
            offset={offset}
            setOffset={setOffset}
            fillet={fillet}
            setFillet={setFillet}
            onApply={async () => {
              try { await save(); toast("Parametri salvati", "success"); } catch (e: any) { toast(e.message, "error"); }
            }}
          />
        ) : (
          <TexturePanel elements={elements} onAdd={() => setAddOpen(true)} onDelete={delElement} />
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
                {(["text", "svg", "track", "rect", "circle", "line"] as const).map((t) => (
                  <Pressable
                    key={t}
                    testID={`type-${t}`}
                    onPress={() => setElType(t)}
                    style={[styles.typeChip, elType === t && { backgroundColor: colors.surfaceInverse }]}
                  >
                    <Text style={[styles.typeChipText, elType === t && { color: colors.onSurfaceInverse }]}>
                      {t.toUpperCase()}
                    </Text>
                  </Pressable>
                ))}
              </View>

              {elType === "text" && (
                <ModalField label="Testo" testID="modal-text" value={textVal} onChangeText={setTextVal} />
              )}
              {elType === "svg" && (
                <ModalField label="SVG (path)" testID="modal-svg" value={svgVal} onChangeText={setSvgVal} multiline />
              )}
              {(elType === "text" || elType === "svg" || elType === "rect" || elType === "circle" || elType === "line") && (
                <ModalField
                  label={elType === "text" ? "Altezza (mm)" : elType === "circle" ? "Diametro (mm)" : "Dimensione (mm)"}
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
              <View style={{ height: space.lg }} />
              <Btn testID="modal-confirm" label="AGGIUNGI" loading={addBusy} onPress={confirmAdd} />
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
  const { step, setStep, selected, nudge, addNode, delNode, offset, setOffset, fillet, setFillet, onApply } = props;
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
        </View>
        <Pressable testID="apply-params" onPress={onApply} style={styles.applyBtn}>
          <Feather name="check" size={18} color={colors.onBrand} />
          <Text style={styles.applyText}>APPLICA</Text>
        </Pressable>
      </View>
    </View>
  );
}

function TexturePanel({ elements, onAdd, onDelete }: any) {
  return (
    <View>
      <Btn testID="add-element-btn" label="AGGIUNGI TEXTURE / SCRITTA / FORMA" icon={<Feather name="plus" size={18} color={colors.onBrand} />} onPress={onAdd} />
      <ScrollView style={{ maxHeight: 140, marginTop: space.sm }}>
        {elements.length === 0 ? (
          <Text style={styles.emptyEl}>Nessun elemento. Aggiungi incisioni o tagli.</Text>
        ) : (
          elements.map((el: ElementT) => (
            <View key={el.id} style={styles.elRow} testID={`element-${el.id}`}>
              <View style={[styles.elDot, { backgroundColor: el.layer === "CUT" ? colors.cut : colors.engrave }]} />
              <Text style={styles.elName}>{el.type.toUpperCase()}</Text>
              <Text style={styles.elLayer}>{el.layer}</Text>
              <Pressable testID={`del-element-${el.id}`} onPress={() => onDelete(el.id)} hitSlop={8}>
                <Feather name="trash-2" size={16} color={colors.error} />
              </Pressable>
            </View>
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
  applyBtn: {
    flexDirection: "row", gap: 6, alignItems: "center", backgroundColor: colors.brand,
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 10,
  },
  applyText: { fontFamily: fonts.display, fontSize: fontSize.base, color: colors.onBrand },
  emptyEl: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, paddingVertical: space.md },
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
  typeGrid: { flexDirection: "row", flexWrap: "wrap", gap: space.sm, marginBottom: space.lg },
  typeChip: { borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 8, backgroundColor: colors.surface },
  typeChipText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  modalInput: {
    borderWidth: BORDER, borderColor: colors.borderStrong, fontFamily: fonts.mono,
    fontSize: fontSize.base, color: colors.onSurface, paddingHorizontal: space.md, paddingVertical: space.md,
  },
});
