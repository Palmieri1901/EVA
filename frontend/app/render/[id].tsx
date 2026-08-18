import React, { useCallback, useRef, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  PanResponder,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import Svg, { ClipPath, Defs, Polygon, Polyline, Text as SvgText } from "react-native-svg";

import { api, BoatT, ProjectT } from "@/src/api";
import { Btn } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

const EVA: Record<string, string> = { marrone: "#6B4A2B", grigio: "#8A8A8A", nero: "#232323", beige: "#C9B48F" };
const GRV: Record<string, string> = { bianco: "#FFFFFF", nero: "#111111", grigio: "#9A9A9A", marrone: "#5A3A1E", rosso: "#C0392B", blu: "#2C5AA0", giallo: "#E1B000", verde: "#2E7D32" };
const EVA_LIST: [string, string][] = [["marrone", "Marrone"], ["grigio", "Grigio"], ["nero", "Nero"], ["beige", "Beige"]];
const GROOVE_LIST: [string, string][] = [["bianco", "Bianco"], ["nero", "Nero"], ["grigio", "Grigio"], ["marrone", "Marrone"], ["rosso", "Rosso"], ["blu", "Blu"], ["giallo", "Giallo"], ["verde", "Verde"]];

type P = ProjectT & { _lx: number; _ly: number; _rot: number; _eva: string; _grv: string };

function centroid(c: number[][]) {
  let x = 0, y = 0;
  for (const p of c) { x += p[0]; y += p[1]; }
  return [x / c.length, y / c.length];
}
function transformed(p: P): number[][] {
  return txPts(p, p.contour_mm);
}
// Transform arbitrary points of a piece (contour OR texture elements) around the
// contour centroid, then apply the layout offset — so textures move/rotate with
// the piece.
function txPts(p: P, pts: number[][]): number[][] {
  const [cx, cy] = centroid(p.contour_mm);
  const r = (p._rot * Math.PI) / 180, cos = Math.cos(r), sin = Math.sin(r);
  return pts.map(([x, y]) => {
    const dx = x - cx, dy = y - cy;
    return [cx + dx * cos - dy * sin + p._lx, cy + dx * sin + dy * cos + p._ly];
  });
}
function pointInPoly(px: number, py: number, poly: number[][]) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
    if (((yi > py) !== (yj > py)) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function segInter(a: number[], b: number[], c: number[], d: number[]) {
  const d1 = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  const d2 = (b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0]);
  const d3 = (d[0] - c[0]) * (a[1] - c[1]) - (d[1] - c[1]) * (a[0] - c[0]);
  const d4 = (d[0] - c[0]) * (b[1] - c[1]) - (d[1] - c[1]) * (b[0] - c[0]);
  return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
}
function polysOverlap(a: number[][], b: number[][]) {
  // vertex containment (covers one piece fully inside another)
  for (const p of a) if (pointInPoly(p[0], p[1], b)) return true;
  for (const p of b) if (pointInPoly(p[0], p[1], a)) return true;
  // edge crossings
  for (let i = 0; i < a.length; i++) {
    const a1 = a[i], a2 = a[(i + 1) % a.length];
    for (let j = 0; j < b.length; j++) {
      const b1 = b[j], b2 = b[(j + 1) % b.length];
      if (segInter(a1, a2, b1, b2)) return true;
    }
  }
  return false;
}

export default function BoatRender() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();

  const [boat, setBoat] = useState<BoatT | null>(null);
  const [pieces, setPieces] = useState<P[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [cw, setCw] = useState(0);
  const CH = 420;
  const PAN_STEP = 40; // px per arrow tap

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const b = await api.getBoat(id);
      setBoat(b);
      const ps = (b.pieces || [])
        .filter((p) => p.contour_mm && p.contour_mm.length >= 3)
        .map((p, i) => ({
          ...p,
          _lx: p.layout_x ?? (i % 3) * 300,
          _ly: p.layout_y ?? Math.floor(i / 3) * 300,
          _rot: p.layout_rot ?? 0,
          _eva: p.eva_color || "marrone",
          _grv: p.groove_color || "bianco",
        }));
      setPieces(ps as P[]);
      setFit(null); // recompute the fit for the freshly loaded layout
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [id, toast]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // world bbox + fit — computed ONCE per load (stable), NOT on every drag,
  // otherwise moving a piece would re-fit/re-center the whole view and the
  // pieces would appear to snap back to their initial position.
  const computeFit = useCallback((ps: P[], width: number) => {
    if (ps.length === 0 || !width) return null;
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    for (const p of ps) {
      for (const [x, y] of transformed(p)) {
        minx = Math.min(minx, x); miny = Math.min(miny, y);
        maxx = Math.max(maxx, x); maxy = Math.max(maxy, y);
      }
    }
    const pad = Math.max(40, 0.05 * Math.max(maxx - minx, maxy - miny));
    minx -= pad; miny -= pad; maxx += pad; maxy += pad;
    const s = Math.min(width / (maxx - minx), CH / (maxy - miny));
    const ox = (width - (maxx - minx) * s) / 2;
    const oy = (CH - (maxy - miny) * s) / 2;
    return { minx, miny, s, ox, oy };
  }, []);

  const [fit, setFit] = useState<{ minx: number; miny: number; s: number; ox: number; oy: number } | null>(null);
  // (re)fit only when a fresh dataset is loaded (fit reset to null) or the
  // canvas width becomes known — never while the user is dragging pieces.
  React.useEffect(() => {
    if (fit || !cw || pieces.length === 0) return;
    setFit(computeFit(pieces, cw));
  }, [fit, cw, pieces, computeFit]);

  const toScreen = (pt: number[]) => fit ? [(pt[0] - fit.minx) * fit.s + fit.ox, (pt[1] - fit.miny) * fit.s + fit.oy] : pt;

  const piecesRef = useRef(pieces); piecesRef.current = pieces;
  const fitRef = useRef(fit); fitRef.current = fit;
  const dragRef = useRef<{ id: string; sx: number; sy: number } | null>(null);
  const rotRef = useRef<{ id: string; startRot: number; startAngle: number } | null>(null);
  const canvasRef = useRef<View>(null);
  const canvasPage = useRef({ x: 0, y: 0 });
  const measureCanvas = () => canvasRef.current?.measureInWindow((x, y) => { canvasPage.current = { x, y }; });
  const touchAngle = (t: any[]) =>
    (Math.atan2(t[1].pageY - t[0].pageY, t[1].pageX - t[0].pageX) * 180) / Math.PI;

  const pan = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onStartShouldSetPanResponderCapture: () => true,
      onMoveShouldSetPanResponderCapture: () => true,
      // keep the drag alive: don't let a parent (ScrollView/gesture) steal it
      onPanResponderTerminationRequest: () => false,
      onShouldBlockNativeResponder: () => true,
      onPanResponderGrant: (_e, gs) => {
        const f = fitRef.current; if (!f) return;
        // Use page coords minus the canvas offset — reliable on touch devices
        // where nativeEvent.locationX is relative to the touched child (Svg),
        // not the canvas View that holds the PanResponder.
        const lx = gs.x0 - canvasPage.current.x;
        const ly = gs.y0 - canvasPage.current.y;
        // hit-test topmost piece
        const ps = piecesRef.current;
        let hit: string | null = null;
        for (let i = ps.length - 1; i >= 0; i--) {
          const scr = transformed(ps[i]).map((pt) => [(pt[0] - f.minx) * f.s + f.ox, (pt[1] - f.miny) * f.s + f.oy]);
          if (pointInPoly(lx, ly, scr)) { hit = ps[i].id; break; }
        }
        setSel(hit);
        rotRef.current = null;
        if (hit) {
          const p = ps.find((x) => x.id === hit)!;
          dragRef.current = { id: hit, sx: p._lx, sy: p._ly };
        } else dragRef.current = null;
      },
      onPanResponderMove: (e, gs) => {
        const f = fitRef.current; if (!f) return;
        const touches = (e.nativeEvent.touches || []) as any[];
        // TWO-FINGER ROTATION of the grabbed/selected piece around its centroid
        if (touches.length >= 2) {
          const id = dragRef.current?.id;
          if (!id) return;
          const ang = touchAngle(touches);
          if (!rotRef.current || rotRef.current.id !== id) {
            const p = piecesRef.current.find((x) => x.id === id);
            rotRef.current = { id, startRot: p?._rot ?? 0, startAngle: ang };
            return;
          }
          const delta = ang - rotRef.current.startAngle;
          const nrot = Math.round((rotRef.current.startRot + delta) % 360);
          setPieces((prev) => prev.map((p) => (p.id === id ? { ...p, _rot: nrot } : p)));
          return;
        }
        // SINGLE-FINGER DRAG
        rotRef.current = null;
        const d = dragRef.current;
        if (!d) return;
        setPieces((prev) => prev.map((p) => p.id === d.id
          ? { ...p, _lx: d.sx + gs.dx / f.s, _ly: d.sy + gs.dy / f.s } : p));
      },
      onPanResponderRelease: () => { dragRef.current = null; rotRef.current = null; Haptics.selectionAsync().catch(() => {}); },
    })
  ).current;

  const selP = pieces.find((p) => p.id === sel) || null;
  const setSelField = (patch: Partial<P>) =>
    setPieces((prev) => prev.map((p) => (p.id === sel ? { ...p, ...patch } : p)));
  const rotateSel = (deg: number) => selP && setSelField({ _rot: (selP._rot + deg) % 360 });

  // overlap detection (world coords) — few pieces so O(n²) is fine
  const overlapIds = new Set<string>();
  {
    const polys = pieces.map((p) => ({ id: p.id, poly: transformed(p) }));
    for (let i = 0; i < polys.length; i++) {
      for (let j = i + 1; j < polys.length; j++) {
        if (polysOverlap(polys[i].poly, polys[j].poly)) {
          overlapIds.add(polys[i].id);
          overlapIds.add(polys[j].id);
        }
      }
    }
  }
  const hasOverlap = overlapIds.size > 0;

  const fitView = () => {
    if (cw) { setFit(computeFit(pieces, cw)); Haptics.selectionAsync().catch(() => {}); }
  };
  const zoomView = (factor: number) => {
    if (!fit || !cw) return;
    const s2 = Math.max(fit.s * factor, 0.0001);
    const wx = (cw / 2 - fit.ox) / fit.s + fit.minx;
    const wy = (CH / 2 - fit.oy) / fit.s + fit.miny;
    setFit({ ...fit, s: s2, ox: cw / 2 - (wx - fit.minx) * s2, oy: CH / 2 - (wy - fit.miny) * s2 });
    Haptics.selectionAsync().catch(() => {});
  };
  const panView = (dx: number, dy: number) => {
    if (!fit) return;
    setFit({ ...fit, ox: fit.ox + dx, oy: fit.oy + dy });
    Haptics.selectionAsync().catch(() => {});
  };

  const doSave = async () => {
    setSaving(true);
    try {
      await Promise.all(pieces.map((p) =>
        api.updateProject(p.id, {
          layout_x: p._lx, layout_y: p._ly, layout_rot: p._rot,
          eva_color: p._eva, groove_color: p._grv,
        })));
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast("Composizione salvata", "success");
    } catch (e: any) {
      toast(e.message || "Salvataggio fallito", "error");
    } finally {
      setSaving(false);
    }
  };

  const doExport = async (fmt: "png" | "pdf") => {
    await doSave();
    Linking.openURL(api.boatRenderUrl(id, fmt)).catch(() => toast("Impossibile aprire il file", "error"));
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={12}>
          <Feather name="arrow-left" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>RENDERING BARCA</Text>
        <View style={{ width: 22 }} />
      </View>

      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.brand} /></View>
      ) : pieces.length === 0 ? (
        <View style={styles.center}>
          <Feather name="grid" size={48} color={colors.onSurfaceTertiary} />
          <Text style={styles.empty}>Nessun pezzo con contorno da comporre. Rileva prima i pezzi della barca.</Text>
        </View>
      ) : (
        <>
          <View
            ref={canvasRef}
            style={styles.canvas}
            onLayout={(e) => { setCw(e.nativeEvent.layout.width); measureCanvas(); }}
            {...pan.panHandlers}
          >
            {fit && (
              <Svg width={cw} height={CH} pointerEvents="none">
                {pieces.map((p) => {
                  const scr = transformed(p).map(toScreen);
                  const pts = scr.map((s) => `${s[0]},${s[1]}`).join(" ");
                  const [ccx, ccy] = centroid(scr);
                  const over = overlapIds.has(p.id);
                  const stroke = over ? "#D22B2B" : p.id === sel ? colors.brand : "#111";
                  const swdt = over ? 3 : p.id === sel ? 3 : 1.5;
                  const grv = GRV[p._grv] || "#fff";
                  const clipId = `clip-${p.id}`;
                  // texture element polylines (teak/diamond fills, lettering, logos)
                  const texture: string[] = [];
                  (p.elements || []).forEach((el) => {
                    (el.polylines || []).forEach((pl) => {
                      const s = txPts(p, pl).map(toScreen);
                      const str = s.filter((q) => Number.isFinite(q[0]) && Number.isFinite(q[1]))
                        .map((q) => `${q[0]},${q[1]}`).join(" ");
                      if (str) texture.push(str);
                    });
                  });
                  return (
                    <React.Fragment key={p.id}>
                      <Defs>
                        <ClipPath id={clipId}><Polygon points={pts} /></ClipPath>
                      </Defs>
                      <Polygon points={pts} fill={EVA[p._eva]} fillOpacity={over ? 0.75 : 1} stroke={stroke} strokeWidth={swdt} strokeDasharray={over ? "8,5" : undefined} />
                      {texture.map((str, i) => (
                        <Polyline key={`${p.id}-t${i}`} points={str} fill="none" stroke={grv} strokeWidth={0.9} strokeOpacity={0.95} clipPath={`url(#${clipId})`} />
                      ))}
                      <SvgText x={ccx} y={ccy} fill="#fff" fontSize="12" fontWeight="bold" textAnchor="middle">{p.piece_name || p.name}</SvgText>
                    </React.Fragment>
                  );
                })}
              </Svg>
            )}
            <View style={styles.zoomCol} pointerEvents="box-none">
              <Pressable testID="zoom-in" onPress={() => zoomView(1.25)} style={styles.ctrlBtn} hitSlop={6}>
                <Feather name="plus" size={18} color={colors.onSurface} />
              </Pressable>
              <Pressable testID="zoom-out" onPress={() => zoomView(0.8)} style={styles.ctrlBtn} hitSlop={6}>
                <Feather name="minus" size={18} color={colors.onSurface} />
              </Pressable>
              <Pressable testID="fit-view" onPress={fitView} style={styles.ctrlBtn} hitSlop={6}>
                <Feather name="maximize" size={16} color={colors.onSurface} />
              </Pressable>
            </View>
            <View style={styles.dpad} pointerEvents="box-none">
              <Pressable testID="pan-up" onPress={() => panView(0, -PAN_STEP)} style={[styles.ctrlBtn, styles.dUp]} hitSlop={4}>
                <Feather name="chevron-up" size={18} color={colors.onSurface} />
              </Pressable>
              <Pressable testID="pan-left" onPress={() => panView(-PAN_STEP, 0)} style={[styles.ctrlBtn, styles.dLeft]} hitSlop={4}>
                <Feather name="chevron-left" size={18} color={colors.onSurface} />
              </Pressable>
              <Pressable testID="pan-right" onPress={() => panView(PAN_STEP, 0)} style={[styles.ctrlBtn, styles.dRight]} hitSlop={4}>
                <Feather name="chevron-right" size={18} color={colors.onSurface} />
              </Pressable>
              <Pressable testID="pan-down" onPress={() => panView(0, PAN_STEP)} style={[styles.ctrlBtn, styles.dDown]} hitSlop={4}>
                <Feather name="chevron-down" size={18} color={colors.onSurface} />
              </Pressable>
            </View>
            {hasOverlap && (
              <View style={styles.warnBanner} pointerEvents="none">
                <Feather name="alert-triangle" size={14} color="#fff" />
                <Text style={styles.warnTxt}>PEZZI SOVRAPPOSTI</Text>
              </View>
            )}
            <Text style={styles.canvasHint}>Trascina per spostare · Due dita per ruotare · Tocca per i colori</Text>
          </View>

          <ScrollView style={styles.panel} contentContainerStyle={{ padding: space.lg, paddingBottom: insets.bottom + 20 }}>
            {selP ? (
              <>
                <Text style={styles.selName}>{selP.piece_name || selP.name}</Text>
                <Text style={styles.lbl}>COLORE EVA</Text>
                <View style={styles.chips}>
                  {EVA_LIST.map(([v, l]) => (
                    <Pressable key={v} onPress={() => setSelField({ _eva: v })} style={[styles.chip, selP._eva === v && styles.chipOn]}>
                      <View style={[styles.sw, { backgroundColor: EVA[v] }]} />
                      <Text style={[styles.chipTxt, selP._eva === v && styles.chipTxtOn]}>{l}</Text>
                    </Pressable>
                  ))}
                </View>
                <Text style={styles.lbl}>RIGA / SCANALATURA</Text>
                <View style={styles.chips}>
                  {GROOVE_LIST.map(([v, l]) => (
                    <Pressable key={v} onPress={() => setSelField({ _grv: v })} style={[styles.chip, selP._grv === v && styles.chipOn]}>
                      <View style={[styles.sw, { backgroundColor: GRV[v] || "#111", borderWidth: 1, borderColor: "#999" }]} />
                      <Text style={[styles.chipTxt, selP._grv === v && styles.chipTxtOn]}>{l}</Text>
                    </Pressable>
                  ))}
                </View>
                <Pressable
                  testID="grv-apply-all"
                  onPress={() => {
                    setPieces((prev) => prev.map((p) => ({ ...p, _grv: selP._grv })));
                    Haptics.selectionAsync().catch(() => {});
                    toast("Colore riga applicato a tutti i pezzi", "success");
                  }}
                  style={styles.applyAll}
                >
                  <Feather name="layers" size={15} color={colors.brand} />
                  <Text style={styles.applyAllTxt}>APPLICA QUESTO COLORE A TUTTI I PEZZI</Text>
                </Pressable>
                <Text style={styles.lbl}>RUOTA</Text>
                <View style={styles.chips}>
                  {[-90, -15, 15, 90].map((d) => (
                    <Pressable key={d} onPress={() => rotateSel(d)} style={styles.rot}>
                      <Text style={styles.chipTxt}>{d > 0 ? `+${d}°` : `${d}°`}</Text>
                    </Pressable>
                  ))}
                </View>
              </>
            ) : (
              <Text style={styles.tip}>Tocca un pezzo nella tela per cambiarne colore EVA, riga e rotazione.</Text>
            )}

            <View style={{ height: space.lg }} />
            <View style={styles.exportRow}>
              <Pressable style={styles.expBtn} onPress={() => doExport("png")}>
                <Feather name="image" size={16} color={colors.onSurface} />
                <Text style={styles.expTxt}>PNG</Text>
              </Pressable>
              <Pressable style={styles.expBtn} onPress={() => doExport("pdf")}>
                <Feather name="file-text" size={16} color={colors.onSurface} />
                <Text style={styles.expTxt}>PDF</Text>
              </Pressable>
            </View>
            <View style={{ height: space.sm }} />
            <Btn label="SALVA COMPOSIZIONE" loading={saving} onPress={doSave} icon={<Feather name="save" size={18} color={colors.onBrand} />} />
          </ScrollView>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: space.lg, paddingVertical: space.md, borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong },
  title: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md, padding: space.xl },
  empty: { fontFamily: fonts.mono, fontSize: fontSize.base, color: colors.onSurfaceSecondary, textAlign: "center" },
  canvas: { height: 420, backgroundColor: colors.surfaceSecondary, borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong },
  canvasHint: { position: "absolute", bottom: 6, left: 0, right: 0, textAlign: "center", fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceTertiary },
  ctrlBtn: { width: 38, height: 38, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, borderWidth: BORDER, borderColor: colors.borderStrong },
  applyAll: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: space.sm, paddingVertical: 10, borderWidth: BORDER, borderColor: colors.brand, backgroundColor: colors.surface },
  applyAllTxt: { fontFamily: fonts.monoMed, fontSize: 12, color: colors.brand, letterSpacing: 0.5 },
  zoomCol: { position: "absolute", top: space.sm, right: space.sm, gap: space.xs },
  dpad: { position: "absolute", right: space.sm, bottom: space.lg, width: 118, height: 118 },
  dUp: { position: "absolute", top: 0, left: 40 },
  dDown: { position: "absolute", bottom: 0, left: 40 },
  dLeft: { position: "absolute", left: 0, top: 40 },
  dRight: { position: "absolute", right: 0, top: 40 },
  warnBanner: { position: "absolute", top: space.sm, left: space.sm, flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#D22B2B", paddingHorizontal: space.sm, paddingVertical: 6 },
  warnTxt: { fontFamily: fonts.monoMed, fontSize: 11, color: "#fff", letterSpacing: 1 },
  panel: { flex: 1 },
  selName: { fontFamily: fonts.displayBold || fonts.display, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: space.md },
  lbl: { fontFamily: fonts.monoMed, fontSize: 11, color: colors.onSurfaceSecondary, textTransform: "uppercase", marginBottom: space.xs, marginTop: space.sm },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: { flexDirection: "row", alignItems: "center", gap: 6, borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: 8, paddingHorizontal: 10, backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.onSurface },
  chipTxt: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  chipTxtOn: { color: colors.onSurfaceInverse },
  sw: { width: 16, height: 16, borderRadius: 3 },
  rot: { minWidth: 56, alignItems: "center", borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: 10, backgroundColor: colors.surface },
  tip: { fontFamily: fonts.mono, fontSize: fontSize.base, color: colors.onSurfaceSecondary },
  exportRow: { flexDirection: "row", gap: space.md },
  expBtn: { flex: 1, flexDirection: "row", gap: space.sm, alignItems: "center", justifyContent: "center", borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: space.md, backgroundColor: colors.surface },
  expTxt: { fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onSurface },
});
