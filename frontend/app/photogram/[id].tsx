import React, { useCallback, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  PanResponder,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import Svg, { Circle, Line as SvgLine, Polygon } from "react-native-svg";

import { absUrl, api, PgPhotoT } from "@/src/api";
import { Btn } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

type Pt = { x: number; y: number };

export default function Photogram() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();

  const [photos, setPhotos] = useState<PgPhotoT[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [stitching, setStitching] = useState(false);
  const [extracting, setExtracting] = useState(false);

  const [phase, setPhase] = useState<"capture" | "reference">("capture");
  const [mosaic, setMosaic] = useState<{ url: string; w: number; h: number } | null>(null);
  const [refType, setRefType] = useState<"rect" | "line" | "dots">("rect");
  const [points, setPoints] = useState<Pt[]>([]);
  const [dots, setDots] = useState<Pt[]>([]);
  const [scaleMode, setScaleMode] = useState(false);
  const [detectingDots, setDetectingDots] = useState(false);
  const [dispW, setDispW] = useState(0);
  const [widthMm, setWidthMm] = useState("");
  const [heightMm, setHeightMm] = useState("");
  const [lengthMm, setLengthMm] = useState("");
  const [markerMm, setMarkerMm] = useState("40");
  const [arucoing, setArucoing] = useState(false);

  const need = refType === "rect" ? 4 : 2;
  const load = useCallback(async () => {
    if (!id) return;
    try {
      const data = await api.listPgPhotos(id);
      setPhotos(data);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setLoading(false);
    }
  }, [id, toast]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const ensureCamera = async () => {
    const cur = await ImagePicker.getCameraPermissionsAsync();
    if (cur.granted) return true;
    const req = await ImagePicker.requestCameraPermissionsAsync();
    if (req.granted) return true;
    toast("Permesso fotocamera negato. Abilitalo dalle impostazioni.", "error");
    if (!req.canAskAgain) Linking.openSettings().catch(() => {});
    return false;
  };

  const addFromCamera = async () => {
    if (!id) return;
    if (!(await ensureCamera())) return;
    const res = await ImagePicker.launchCameraAsync({ quality: 0.85 });
    if (res.canceled || !res.assets?.[0]?.uri) return;
    setBusy(true);
    try {
      await api.addPgPhoto(id, res.assets[0].uri);
      Haptics.selectionAsync().catch(() => {});
      await load();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const addFromGallery = async () => {
    if (!id) return;
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      allowsMultipleSelection: true,
      selectionLimit: 12,
      quality: 0.85,
    });
    if (res.canceled || !res.assets?.length) return;
    setBusy(true);
    try {
      for (const a of res.assets) {
        if (a.uri) await api.addPgPhoto(id, a.uri);
      }
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast(`${res.assets.length} foto aggiunte`, "success");
      await load();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (pid: string) => {
    try {
      await api.deletePgPhoto(id, pid);
      setPhotos((p) => p.filter((x) => x.id !== pid));
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const doStitch = async () => {
    if (!id || photos.length === 0) return;
    setStitching(true);
    try {
      const r = await api.pgStitch(id);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      if (r.warning) toast(r.warning, "info");
      setMosaic({ url: r.mosaic_url, w: r.w, h: r.h });
      setPoints([]);
      setPhase("reference");
    } catch (e: any) {
      toast(e.message || "Unione fallita", "error");
    } finally {
      setStitching(false);
    }
  };

  const doAruco = async () => {
    if (!id || photos.length === 0) return;
    const mm = parseFloat(markerMm);
    if (!mm || mm <= 0) {
      toast("Inserisci il lato reale del marker (mm)", "error");
      return;
    }
    setArucoing(true);
    try {
      const proj = await api.pgAruco(id, mm);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast(
        `${proj.photos_used || 0} foto unite, ${proj.markers_found || 0} marker. ` +
          (proj.detected ? "Contorno rilevato!" : "Contorno provvisorio: rifinisci nell'editor."),
        proj.detected ? "success" : "info"
      );
      router.replace(`/editor/${id}` as any);
    } catch (e: any) {
      toast(e.message || "Elaborazione marker fallita", "error");
    } finally {
      setArucoing(false);
    }
  };

  const downloadSheet = () => {
    const mm = parseFloat(markerMm) || 40;
    Linking.openURL(api.arucoSheetUrl(mm)).catch(() => toast("Impossibile aprire il PDF", "error"));
  };

  const dispH = mosaic && dispW ? (dispW * mosaic.h) / mosaic.w : 0;

  const onImgPress = (e: any) => {
    if (!mosaic || !dispW) return;
    const ne = e.nativeEvent || {};
    // RN native provides locationX/Y; React-Native-Web leaves them undefined,
    // so fall back to the DOM offsetX/Y (relative to the tapped element).
    let lx = ne.locationX;
    let ly = ne.locationY;
    if (lx == null || !isFinite(lx)) { lx = ne.offsetX; ly = ne.offsetY; }
    if (lx == null || ly == null || !isFinite(lx) || !isFinite(ly)) return;
    const mx = (lx / dispW) * mosaic.w;
    const my = (ly / dispH) * mosaic.h;
    if (!isFinite(mx) || !isFinite(my)) return;
    if (refType === "dots" && !scaleMode) {
      // outline-dot editing: tap near a dot removes it, else add a new one
      const thresh = mosaic.w * 0.03;
      setDots((prev) => {
        const idx = prev.findIndex((d) => Math.hypot(d.x - mx, d.y - my) < thresh);
        if (idx >= 0) return prev.filter((_, i) => i !== idx);
        return [...prev, { x: mx, y: my }];
      });
      Haptics.selectionAsync().catch(() => {});
      return;
    }
    setPoints((prev) => {
      const next = prev.length >= need ? [] : [...prev];
      next.push({ x: mx, y: my });
      return next;
    });
    Haptics.selectionAsync().catch(() => {});
  };

  const toDisp = (p: Pt) => ({ x: (p.x / (mosaic?.w || 1)) * dispW, y: (p.y / (mosaic?.h || 1)) * dispH });

  // Live geometry/points refs so the memoised drag handlers read current values
  const geomRef = useRef({ dispW, dispH, mw: mosaic?.w || 1, mh: mosaic?.h || 1 });
  geomRef.current = { dispW, dispH, mw: mosaic?.w || 1, mh: mosaic?.h || 1 };
  const pointsRef = useRef(points);
  pointsRef.current = points;
  const dragStart = useRef<Record<number, { x: number; y: number }>>({});

  const dotResponders = useMemo(
    () =>
      [0, 1, 2, 3].map((i) =>
        PanResponder.create({
          onStartShouldSetPanResponder: () => true,
          onMoveShouldSetPanResponder: () => true,
          onPanResponderGrant: () => {
            const g = geomRef.current;
            const p = pointsRef.current[i];
            if (p) dragStart.current[i] = { x: (p.x / g.mw) * g.dispW, y: (p.y / g.mh) * g.dispH };
          },
          onPanResponderMove: (_e, gs) => {
            const g = geomRef.current;
            const s = dragStart.current[i];
            if (!s || !g.dispW || !g.dispH) return;
            const nx = Math.max(0, Math.min(g.dispW, s.x + gs.dx));
            const ny = Math.max(0, Math.min(g.dispH, s.y + gs.dy));
            setPoints((prev) => {
              if (!prev[i]) return prev;
              const c = [...prev];
              c[i] = { x: (nx / g.dispW) * g.mw, y: (ny / g.dispH) * g.mh };
              return c;
            });
          },
          onPanResponderRelease: () => Haptics.selectionAsync().catch(() => {}),
        })
      ),
    []
  );

  const doDetectDots = async () => {
    if (!id) return;
    setDetectingDots(true);
    try {
      const r = await api.pgDetectDots(id);
      const found = (r.dots || []).map((p) => ({ x: p[0], y: p[1] }));
      setDots(found);
      toast(
        found.length
          ? `${found.length} punti rilevati. Aggiungi/rimuovi toccando, poi imposta la scala.`
          : "Nessun punto rilevato: toccali tu sulla foto.",
        found.length ? "success" : "info"
      );
    } catch (e: any) {
      toast(e.message || "Rilevamento punti fallito", "error");
    } finally {
      setDetectingDots(false);
    }
  };

  const doExtract = async () => {
    if (!id) return;
    let reference: any;
    if (refType === "dots") {
      if (dots.length < 3) {
        toast("Servono almeno 3 punti dell'outline (tocca la foto o usa RILEVA)", "error");
        return;
      }
      if (points.length !== 2) {
        toast("Attiva SCALA e tocca 2 punti a distanza nota", "error");
        return;
      }
      const l = parseFloat(lengthMm);
      if (!l || l <= 0) {
        toast("Inserisci la distanza reale tra i 2 punti di scala (mm)", "error");
        return;
      }
      reference = {
        type: "dots",
        points: points.map((p) => [p.x, p.y]),
        length_mm: l,
        dots: dots.map((p) => [p.x, p.y]),
      };
    } else if (points.length !== need) {
      toast(`Tocca ${need} punti sul riferimento`, "error");
      return;
    } else if (refType === "rect") {
      const w = parseFloat(widthMm);
      const h = parseFloat(heightMm);
      if (!w || !h || w <= 0 || h <= 0) {
        toast("Inserisci larghezza e altezza reali (mm)", "error");
        return;
      }
      reference = { type: "rect", points: points.map((p) => [p.x, p.y]), width_mm: w, height_mm: h };
    } else {
      const l = parseFloat(lengthMm);
      if (!l || l <= 0) {
        toast("Inserisci la lunghezza reale (mm)", "error");
        return;
      }
      reference = { type: "line", points: points.map((p) => [p.x, p.y]), length_mm: l };
    }
    setExtracting(true);
    try {
      const proj = await api.pgExtract(id, reference);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast(
        proj.detected ? "Contorno rilevato! Rifinisci nell'editor." : "Contorno provvisorio: disegnalo nell'editor.",
        proj.detected ? "success" : "info"
      );
      router.replace(`/editor/${id}` as any);
    } catch (e: any) {
      toast(e.message || "Estrazione fallita", "error");
    } finally {
      setExtracting(false);
    }
  };

  // ---------------- CAPTURE PHASE ----------------
  if (phase === "capture") {
    return (
      <View style={[styles.container, { paddingTop: insets.top }]}>
        <View style={styles.header}>
          <Pressable testID="pg-back" onPress={() => router.replace("/")} hitSlop={12}>
            <Feather name="arrow-left" size={22} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.title}>FOTO + RIFERIMENTO</Text>
          <View style={{ width: 22 }} />
        </View>

        <ScrollView contentContainerStyle={{ padding: space.lg, paddingBottom: 200 }}>
          <View style={styles.infoBox}>
            <Feather name="aperture" size={14} color={colors.brand} />
            <Text style={styles.infoText}>
              Tappeti delimitati dal NASTRO: scatta UNA foto dall'alto in cui si vedano bene il
              nastro e i 4 punti d'angolo di riferimento. Poi premi USA FOTO + RIFERIMENTO: tocchi
              i 4 angoli, inserisci le misure reali e ricavo il contorno seguendo il nastro.
              Solo per pezzi molto grandi: usa più foto con marker ArUco.
            </Text>
          </View>

          <View style={styles.grid}>
            {photos.map((p, index) => {
              const thumb = absUrl(p.photo_url);
              return (
                <View key={p.id} style={styles.tile} testID={`pg-photo-${index}`}>
                  {thumb ? (
                    <Image source={{ uri: thumb }} style={{ width: "100%", height: "100%" }} contentFit="cover" />
                  ) : (
                    <MaterialCommunityIcons name="image" size={26} color={colors.onSurfaceTertiary} />
                  )}
                  <Pressable testID={`pg-del-${index}`} hitSlop={8} style={styles.tileDel} onPress={() => onDelete(p.id)}>
                    <Feather name="x" size={16} color={colors.onBrand} />
                  </Pressable>
                  <View style={styles.tileNum}>
                    <Text style={styles.tileNumTxt}>{index + 1}</Text>
                  </View>
                </View>
              );
            })}
          </View>

          {!loading && photos.length === 0 && (
            <View style={styles.empty}>
              <MaterialCommunityIcons name="camera-burst" size={56} color={colors.onSurfaceTertiary} />
              <Text style={styles.emptyText}>Nessuna foto. Scatta una foto dall'alto o scegline una dalla galleria.</Text>
            </View>
          )}
        </ScrollView>

        <View style={[styles.footer, { paddingBottom: insets.bottom + space.md }]}>
          <View style={styles.addRow}>
            <Pressable testID="pg-camera" style={styles.addBtn} onPress={addFromCamera}>
              {busy ? <ActivityIndicator color={colors.onSurface} /> : <Feather name="camera" size={18} color={colors.onSurface} />}
              <Text style={styles.addText}>SCATTA</Text>
            </Pressable>
            <Pressable testID="pg-gallery" style={styles.addBtn} onPress={addFromGallery}>
              <Feather name="image" size={18} color={colors.onSurface} />
              <Text style={styles.addText}>GALLERIA</Text>
            </Pressable>
          </View>

          <Btn
            testID="pg-stitch-btn"
            label={photos.length > 1 ? `USA FOTO + RIFERIMENTO (${photos.length} foto)` : "USA FOTO + RIFERIMENTO"}
            disabled={photos.length === 0}
            loading={stitching}
            icon={<MaterialCommunityIcons name="vector-square" size={20} color={colors.onBrand} />}
            onPress={doStitch}
          />

          <View style={styles.markerRow}>
            <View style={{ width: 130 }}>
              <Text style={styles.smallLabel}>LATO MARKER (mm)</Text>
              <TextInput testID="pg-marker-mm" value={markerMm} onChangeText={setMarkerMm} keyboardType="decimal-pad" style={styles.inputSm} />
            </View>
            <Pressable testID="pg-sheet" style={styles.sheetBtn} onPress={downloadSheet}>
              <Feather name="download" size={16} color={colors.onSurface} />
              <Text style={styles.sheetText}>FOGLIO MARKER (PDF)</Text>
            </Pressable>
          </View>

          <Pressable testID="pg-aruco" onPress={doAruco} disabled={photos.length === 0} style={{ alignItems: "center", paddingVertical: 6 }}>
            {arucoing ? (
              <ActivityIndicator color={colors.onSurface} />
            ) : (
              <Text style={styles.linkText}>Pezzo molto grande con marker ArUco? Unisci con marker →</Text>
            )}
          </Pressable>
        </View>
      </View>
    );
  }

  // ---------------- REFERENCE PHASE ----------------
  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Pressable testID="pg-ref-back" onPress={() => setPhase("capture")} hitSlop={12}>
          <Feather name="arrow-left" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>RIFERIMENTO</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={{ padding: space.lg, paddingBottom: 200 }}>
        <View style={styles.infoBox}>
          <Feather name="info" size={14} color={colors.brand} />
          <Text style={styles.infoText}>
            {refType === "rect"
              ? "Tocca i 4 PUNTI D'ANGOLO di riferimento (i puntini/angoli), poi TRASCINALI per posizionarli con precisione. Inserisci larghezza e altezza reali (interasse) in mm: raddrizzo la prospettiva e il contorno seguirà il NASTRO."
              : refType === "line"
              ? "Tocca i 2 estremi di una distanza nota (es. tacche del righello), poi TRASCINALI per regolarli. Inserisci la lunghezza reale in mm. Il contorno seguirà il NASTRO."
              : "PUNTI NERI (forme irregolari): premi RILEVA PUNTI (o tocca la foto per aggiungerli / tocca un punto per rimuoverlo). Poi premi IMPOSTA SCALA e tocca 2 punti a distanza nota inserendo i mm. Collego i punti in automatico."}
          </Text>
        </View>

        <View style={styles.segRow}>
          {(["rect", "line", "dots"] as const).map((t) => (
            <Pressable
              key={t}
              testID={`pg-reftype-${t}`}
              style={[styles.segBtn, refType === t && styles.segOn]}
              onPress={() => { setRefType(t); setPoints([]); setScaleMode(false); }}
            >
              <Text style={[styles.segText, refType === t && styles.segTextOn]}>
                {t === "rect" ? "RETTANGOLO" : t === "line" ? "LINEA" : "PUNTI NERI"}
              </Text>
            </Pressable>
          ))}
        </View>

        {refType === "dots" && (
          <View style={styles.dotsBar}>
            <Btn
              testID="pg-detect-dots"
              label={detectingDots ? "RILEVO..." : "RILEVA PUNTI"}
              variant="outline"
              loading={detectingDots}
              icon={<Feather name="target" size={16} color={colors.onSurface} />}
              onPress={doDetectDots}
            />
            <Pressable
              testID="pg-scale-toggle"
              onPress={() => setScaleMode((s) => !s)}
              style={[styles.scaleBtn, scaleMode && styles.scaleBtnOn]}
            >
              <Feather name="maximize-2" size={14} color={scaleMode ? colors.onBrand : colors.onSurface} />
              <Text style={[styles.scaleText, scaleMode && styles.scaleTextOn]}>
                {scaleMode ? "SCALA: tocca 2 punti" : "IMPOSTA SCALA"}
              </Text>
            </Pressable>
          </View>
        )}

        <View
          style={styles.canvas}
          onLayout={(e) => setDispW(e.nativeEvent.layout.width)}
        >
          {mosaic && dispW > 0 && (
            <View>
              <Pressable testID="pg-canvas" onPress={onImgPress}>
                <Image
                  source={{ uri: absUrl(mosaic.url) }}
                  style={{ width: dispW, height: dispH }}
                  contentFit="fill"
                />
                <Svg style={StyleSheet.absoluteFill} width={dispW} height={dispH} pointerEvents="none">
                  {refType === "rect" && points.length === 4 && (
                    <Polygon
                      points={points.map((p) => { const d = toDisp(p); return `${d.x},${d.y}`; }).join(" ")}
                      fill="rgba(255,69,0,0.12)"
                      stroke={colors.brand}
                      strokeWidth={2}
                    />
                  )}
                  {refType === "line" && points.length === 2 && (
                    <SvgLine
                      x1={toDisp(points[0]).x} y1={toDisp(points[0]).y}
                      x2={toDisp(points[1]).x} y2={toDisp(points[1]).y}
                      stroke={colors.brand} strokeWidth={3}
                    />
                  )}
                  {refType === "dots" && dots.map((p, i) => {
                    const d = toDisp(p);
                    return <Circle key={`o${i}`} cx={d.x} cy={d.y} r={7} fill="rgba(255,69,0,0.35)" stroke={colors.brand} strokeWidth={2} />;
                  })}
                  {refType === "dots" && points.length === 2 && (
                    <SvgLine
                      x1={toDisp(points[0]).x} y1={toDisp(points[0]).y}
                      x2={toDisp(points[1]).x} y2={toDisp(points[1]).y}
                      stroke="#0A84FF" strokeWidth={3} strokeDasharray="8,6"
                    />
                  )}
                </Svg>
              </Pressable>
              {(refType !== "dots" || scaleMode) && points.map((p, i) => {
                const d = toDisp(p);
                return (
                  <View
                    key={i}
                    testID={`pg-dot-${i}`}
                    {...dotResponders[i].panHandlers}
                    style={[styles.dotHit, { left: d.x - 18, top: d.y - 18 }]}
                  >
                    <View style={styles.dot}>
                      <Text style={styles.dotLabel}>{i + 1}</Text>
                    </View>
                  </View>
                );
              })}
            </View>
          )}
        </View>

        <View style={styles.ptRow}>
          <Text style={styles.ptText}>
            {refType === "dots"
              ? `Outline: ${dots.length} punti · Scala: ${points.length}/2`
              : `Punti: ${points.length}/${need}`}
          </Text>
          <Pressable testID="pg-reset-pts" onPress={() => { setPoints([]); if (refType === "dots") setDots([]); }} hitSlop={8} style={styles.resetBtn}>
            <Feather name="refresh-ccw" size={14} color={colors.onSurface} />
            <Text style={styles.resetText}>AZZERA PUNTI</Text>
          </Pressable>
        </View>

        {refType === "rect" ? (
          <View style={styles.dimRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Larghezza (mm)</Text>
              <TextInput testID="pg-width" value={widthMm} onChangeText={setWidthMm} keyboardType="decimal-pad" placeholder="es. 210" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} />
            </View>
            <View style={{ width: space.md }} />
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Altezza (mm)</Text>
              <TextInput testID="pg-height" value={heightMm} onChangeText={setHeightMm} keyboardType="decimal-pad" placeholder="es. 297" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} />
            </View>
          </View>
        ) : (
          <View>
            <Text style={styles.label}>{refType === "dots" ? "Distanza tra i 2 punti scala (mm)" : "Lunghezza (mm)"}</Text>
            <TextInput testID="pg-length" value={lengthMm} onChangeText={setLengthMm} keyboardType="decimal-pad" placeholder="es. 300" placeholderTextColor={colors.onSurfaceTertiary} style={styles.input} />
          </View>
        )}

        <View style={{ height: space.lg }} />
        <Btn
          testID="pg-extract"
          label="ESTRAI CONTORNO"
          loading={extracting}
          icon={<MaterialCommunityIcons name="vector-square" size={20} color={colors.onBrand} />}
          onPress={doExtract}
        />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: space.lg, paddingVertical: space.md,
    borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong,
  },
  title: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  infoBox: {
    flexDirection: "row", gap: space.sm, alignItems: "flex-start",
    backgroundColor: colors.brandTertiary, borderWidth: BORDER, borderColor: colors.brand,
    padding: space.md, marginBottom: space.lg,
  },
  infoText: { flex: 1, fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurface },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: space.md },
  tile: {
    width: "30%", aspectRatio: 1, borderWidth: BORDER, borderColor: colors.borderStrong,
    backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center",
  },
  tileDel: {
    position: "absolute", top: 2, right: 2, width: 24, height: 24, backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
  },
  tileNum: {
    position: "absolute", bottom: 0, left: 0, paddingHorizontal: 6, paddingVertical: 2,
    backgroundColor: "rgba(0,0,0,0.6)",
  },
  tileNumTxt: { color: "#fff", fontFamily: fonts.monoMed, fontSize: fontSize.sm },
  empty: { alignItems: "center", paddingTop: 40, gap: space.md, paddingHorizontal: space.xl },
  emptyText: { fontFamily: fonts.mono, fontSize: fontSize.base, color: colors.onSurfaceSecondary, textAlign: "center" },
  footer: {
    position: "absolute", left: 0, right: 0, bottom: 0, padding: space.lg, gap: space.md,
    borderTopWidth: BORDER, borderTopColor: colors.borderStrong, backgroundColor: colors.surface,
  },
  addRow: { flexDirection: "row", gap: space.md },
  addBtn: {
    flex: 1, flexDirection: "row", gap: space.sm, alignItems: "center", justifyContent: "center",
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: space.md, backgroundColor: colors.surface,
  },
  addText: { fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onSurface },
  markerRow: { flexDirection: "row", gap: space.md, alignItems: "flex-end" },
  smallLabel: { fontFamily: fonts.monoMed, fontSize: 10, color: colors.onSurfaceSecondary, marginBottom: 4, textTransform: "uppercase" },
  inputSm: {
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 8,
    fontFamily: fonts.mono, fontSize: fontSize.base, color: colors.onSurface, backgroundColor: colors.surface,
  },
  sheetBtn: {
    flex: 1, flexDirection: "row", gap: space.sm, alignItems: "center", justifyContent: "center",
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: 10, backgroundColor: colors.surface,
  },
  sheetText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  linkText: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.brand, textDecorationLine: "underline" },
  segRow: { flexDirection: "row", gap: space.sm, marginBottom: space.md },
  dotsBar: { gap: space.sm, marginBottom: space.md },
  scaleBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface,
    paddingVertical: 10,
  },
  scaleBtnOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  scaleText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface, letterSpacing: 0.5 },
  scaleTextOn: { color: colors.onBrand },  segBtn: {
    flex: 1, alignItems: "center", borderWidth: BORDER, borderColor: colors.borderStrong,
    paddingVertical: 10, backgroundColor: colors.surface,
  },
  segOn: { backgroundColor: colors.onSurface },
  segText: { fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onSurface },
  segTextOn: { color: colors.onSurfaceInverse },
  canvas: {
    width: "100%", borderWidth: BORDER, borderColor: colors.borderStrong,
    backgroundColor: colors.surfaceTertiary, overflow: "hidden",
  },
  dotHit: {
    position: "absolute", width: 36, height: 36, alignItems: "center", justifyContent: "center",
  },
  dot: {
    width: 20, height: 20, borderRadius: 10, backgroundColor: colors.brand,
    borderWidth: 2, borderColor: "#fff", alignItems: "center", justifyContent: "center",
  },
  dotLabel: { color: "#fff", fontFamily: fonts.monoMed, fontSize: 10 },
  ptRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginVertical: space.md },
  ptText: { fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onSurface },
  resetBtn: { flexDirection: "row", gap: 6, alignItems: "center", borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 6 },
  resetText: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurface },
  dimRow: { flexDirection: "row" },
  label: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: space.xs, textTransform: "uppercase" },
  input: {
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 10,
    fontFamily: fonts.mono, fontSize: fontSize.base, color: colors.onSurface, backgroundColor: colors.surface,
  },
});
