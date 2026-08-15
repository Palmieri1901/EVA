import React, { useCallback, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Linking,
  Modal,
  PanResponder,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import Slider from "@react-native-community/slider";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import * as Sharing from "expo-sharing";
import * as FileSystem from "expo-file-system/legacy";
import * as Haptics from "expo-haptics";

import { absUrl, api, BoatT, ProjectT } from "@/src/api";
import { Btn } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { useMachine } from "@/src/machine";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

type VecResult = {
  polylines: number[][][];
  width_mm: number;
  height_mm: number;
  count: number;
  preview_url: string | null;
  dxf_url: string;
};

export default function Vectorize() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { machine } = useMachine();

  const [imageUri, setImageUri] = useState<string | null>(null);
  const [subject, setSubject] = useState<"scritta" | "logo" | "oggetto" | "cerchio">("logo");
  const [internals, setInternals] = useState(false);
  const [invert, setInvert] = useState(true);
  const [widthMm, setWidthMm] = useState("200");
  const [autoThr, setAutoThr] = useState(true);
  const [thr, setThr] = useState(128);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<VecResult | null>(null);

  // ROI selection (in display px) + image aspect
  const [aspect, setAspect] = useState(1);
  const [layout, setLayout] = useState({ w: 1, h: 1 });
  const [roiRect, setRoiRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const startRef = useRef<{ x: number; y: number } | null>(null);
  const layoutRef = useRef({ w: 1, h: 1 });

  const pan = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: (e) => {
        startRef.current = { x: e.nativeEvent.locationX, y: e.nativeEvent.locationY };
        setRoiRect({ x: startRef.current.x, y: startRef.current.y, w: 0, h: 0 });
      },
      onPanResponderMove: (e) => {
        const s = startRef.current;
        if (!s) return;
        const { w: LW, h: LH } = layoutRef.current;
        const cx = Math.max(0, Math.min(LW, e.nativeEvent.locationX));
        const cy = Math.max(0, Math.min(LH, e.nativeEvent.locationY));
        setRoiRect({ x: Math.min(s.x, cx), y: Math.min(s.y, cy), w: Math.abs(cx - s.x), h: Math.abs(cy - s.y) });
      },
    })
  ).current;

  // insert flow
  const [pickerOpen, setPickerOpen] = useState(false);
  const [boats, setBoats] = useState<BoatT[]>([]);
  const [pieces, setPieces] = useState<ProjectT[]>([]);
  const [selBoat, setSelBoat] = useState<BoatT | null>(null);
  const [insertLayer, setInsertLayer] = useState<"CUT" | "ENGRAVE">(machine === "laser" ? "CUT" : "ENGRAVE");
  const [inserting, setInserting] = useState(false);

  const pickImage = async (fromCamera: boolean) => {
    const perm = fromCamera
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      if (!perm.canAskAgain) {
        toast("Permesso negato. Aprilo nelle Impostazioni.", "error");
        Linking.openSettings();
      } else {
        toast("Permesso necessario per la foto", "error");
      }
      return;
    }
    const res = fromCamera
      ? await ImagePicker.launchCameraAsync({ quality: 0.9 })
      : await ImagePicker.launchImageLibraryAsync({ quality: 0.9, mediaTypes: ["images"] });
    if (!res.canceled && res.assets?.length) {
      const a = res.assets[0];
      setImageUri(a.uri);
      setResult(null);
      setRoiRect(null);
      if (a.width && a.height) setAspect(a.height / a.width);
      else Image.getSize(a.uri, (w, h) => setAspect(h / w), () => setAspect(1));
    }
  };

  const analyze = async () => {
    if (!imageUri) {
      toast("Scegli prima una foto", "error");
      return;
    }
    setBusy(true);
    try {
      let roi: { x: number; y: number; w: number; h: number } | null = null;
      if (roiRect && roiRect.w > 8 && roiRect.h > 8) {
        roi = {
          x: roiRect.x / layout.w,
          y: roiRect.y / layout.h,
          w: roiRect.w / layout.w,
          h: roiRect.h / layout.h,
        };
      }
      const r = await api.vectorize(imageUri, {
        invert,
        subject,
        internals,
        roi,
        target_width_mm: parseFloat(widthMm) || 200,
        threshold: autoThr ? -1 : thr,
      });
      setResult(r);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast(`${r.count} forme · ${r.width_mm}×${r.height_mm} mm`, "success");
    } catch (e: any) {
      toast(e.message || "Vettorizzazione fallita", "error");
    } finally {
      setBusy(false);
    }
  };

  const downloadDxf = async () => {
    if (!result) return;
    const url = absUrl(result.dxf_url)!;
    if (Platform.OS === "web") {
      window.open(url, "_blank");
      toast("DXF generato", "success");
      return;
    }
    const fileUri = FileSystem.documentDirectory + `logo_${Date.now()}.dxf`;
    const dl = await FileSystem.downloadAsync(url, fileUri);
    if (await Sharing.isAvailableAsync()) {
      await Sharing.shareAsync(dl.uri, { mimeType: "application/dxf", dialogTitle: "Esporta DXF" });
    } else {
      toast("DXF salvato", "success");
    }
  };

  const openPicker = async () => {
    try {
      const b = await api.listBoats();
      setBoats(b);
      setSelBoat(null);
      setPieces([]);
      setPickerOpen(true);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const openBoat = async (boat: BoatT) => {
    try {
      const full = await api.getBoat(boat.id);
      setSelBoat(boat);
      setPieces(full.pieces || []);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const insertInto = async (piece: ProjectT) => {
    if (!result) return;
    setInserting(true);
    try {
      await api.addElement(piece.id, {
        type: "polyline",
        layer: insertLayer,
        polylines: result.polylines,
        params: { source: "photo", width_mm: result.width_mm, height_mm: result.height_mm },
      });
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      setPickerOpen(false);
      toast(`Inserito in "${piece.piece_name || "pezzo"}"`, "success");
      router.push(`/editor/${piece.id}` as any);
    } catch (e: any) {
      toast(e.message || "Inserimento fallito", "error");
    } finally {
      setInserting(false);
    }
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Pressable testID="back-btn" onPress={() => router.back()} hitSlop={12}>
          <Feather name="arrow-left" size={24} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1, marginLeft: space.md }}>
          <Text style={styles.kicker}>DA FOTO → DXF</Text>
          <Text style={styles.title}>VETTORIZZA LOGO</Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: space.lg, paddingBottom: insets.bottom + 40 }} keyboardShouldPersistTaps="handled">
        <View
          style={styles.preview}
          onLayout={(e) => {
            const w = e.nativeEvent.layout.width;
            const h = Math.min(Math.max(w * aspect, 160), 420);
            const l = { w, h };
            setLayout(l);
            layoutRef.current = l;
          }}
        >
          {result?.preview_url ? (
            <Image source={{ uri: absUrl(result.preview_url) }} style={{ width: layout.w, height: layout.h }} resizeMode="contain" />
          ) : imageUri ? (
            <View style={{ width: layout.w, height: layout.h }}>
              <Image source={{ uri: imageUri }} style={{ width: layout.w, height: layout.h }} resizeMode="contain" />
              <View style={StyleSheet.absoluteFill} {...pan.panHandlers}>
                {roiRect && roiRect.w > 2 && roiRect.h > 2 && (
                  <View
                    testID="roi-rect"
                    style={[styles.roi, { left: roiRect.x, top: roiRect.y, width: roiRect.w, height: roiRect.h }]}
                  />
                )}
              </View>
            </View>
          ) : (
            <View style={styles.previewEmpty}>
              <MaterialCommunityIcons name="image-search-outline" size={48} color={colors.onSurfaceTertiary} />
              <Text style={styles.previewHint}>Scatta o scegli una foto,{"\n"}poi trascina per selezionare l'area del logo</Text>
            </View>
          )}
        </View>

        {imageUri && !result && (
          <View style={styles.roiBar}>
            <Text style={styles.roiHint}>
              {roiRect && roiRect.w > 8 ? "Area selezionata ✓" : "Trascina sull'immagine per selezionare l'area"}
            </Text>
            {roiRect ? (
              <Pressable testID="roi-clear" onPress={() => setRoiRect(null)} hitSlop={8} style={styles.roiClear}>
                <Feather name="x" size={14} color={colors.onSurface} />
                <Text style={styles.roiClearText}>AREA</Text>
              </Pressable>
            ) : null}
          </View>
        )}

        <View style={styles.pickRow}>
          <Pressable testID="pick-camera" style={styles.pickBtn} onPress={() => pickImage(true)}>
            <Feather name="camera" size={16} color={colors.onSurface} />
            <Text style={styles.pickText}>FOTOCAMERA</Text>
          </Pressable>
          <View style={{ width: space.md }} />
          <Pressable testID="pick-library" style={styles.pickBtn} onPress={() => pickImage(false)}>
            <Feather name="image" size={16} color={colors.onSurface} />
            <Text style={styles.pickText}>GALLERIA</Text>
          </Pressable>
        </View>

        <Text style={styles.label}>Cosa rilevare</Text>
        <View style={styles.segRow}>
          {([["scritta", "SCRITTA"], ["logo", "LOGO"], ["oggetto", "OGGETTO"], ["cerchio", "CERCHIO"]] as const).map(([v, l]) => (
            <Pressable
              key={v}
              testID={`subject-${v}`}
              style={[styles.segBtn, subject === v && styles.toggleOn]}
              onPress={() => { Haptics.selectionAsync().catch(() => {}); setSubject(v); setResult(null); }}
            >
              <Text style={[styles.toggleText, { fontSize: fontSize.sm }, subject === v && styles.toggleTextOn]}>{l}</Text>
            </Pressable>
          ))}
        </View>

        <Text style={styles.label}>Larghezza reale del logo (mm)</Text>
        <TextInput testID="vec-width" value={widthMm} onChangeText={setWidthMm} keyboardType="decimal-pad" style={styles.input} />

        {subject !== "cerchio" && (
          <View style={styles.toggleRow}>
            <Pressable testID="vec-internals" style={[styles.toggle, internals && styles.toggleOn]} onPress={() => { setInternals(!internals); setResult(null); }}>
              <Feather name={internals ? "check-square" : "square"} size={16} color={internals ? colors.onSurfaceInverse : colors.onSurface} />
              <Text style={[styles.toggleText, internals && styles.toggleTextOn]}>Dettagli interni (fori, linee)</Text>
            </Pressable>
          </View>
        )}

        <View style={styles.toggleRow}>
          <Pressable testID="vec-invert" style={[styles.toggle, invert && styles.toggleOn]} onPress={() => setInvert(!invert)}>
            <Feather name={invert ? "check-square" : "square"} size={16} color={invert ? colors.onSurfaceInverse : colors.onSurface} />
            <Text style={[styles.toggleText, invert && styles.toggleTextOn]}>Soggetto scuro su chiaro</Text>
          </Pressable>
        </View>

        <View style={styles.thrHeader}>
          <Text style={styles.label}>Soglia {autoThr ? "(auto)" : `· ${thr}`}</Text>
          <Pressable testID="vec-auto" style={[styles.autoChip, autoThr && styles.toggleOn]} onPress={() => setAutoThr(!autoThr)}>
            <Text style={[styles.toggleText, { fontSize: 11 }, autoThr && styles.toggleTextOn]}>AUTO</Text>
          </Pressable>
        </View>
        <Slider
          testID="vec-thr-slider"
          style={{ width: "100%", height: 36, opacity: autoThr ? 0.4 : 1 }}
          minimumValue={0}
          maximumValue={255}
          step={1}
          value={thr}
          disabled={autoThr}
          onValueChange={(v) => setThr(Math.round(v))}
          minimumTrackTintColor={colors.brand}
          maximumTrackTintColor={colors.border}
          thumbTintColor={colors.onSurface}
        />

        <View style={{ height: space.md }} />
        <Btn testID="vec-analyze" label={result ? "RIANALIZZA" : "ANALIZZA"} loading={busy} icon={<Feather name="cpu" size={18} color={colors.onBrand} />} onPress={analyze} />

        {result && (
          <View style={styles.resultBox}>
            <Text style={styles.resultText}>
              {result.count} forme · {result.width_mm} × {result.height_mm} mm
            </Text>
            <View style={{ height: space.md }} />
            <Pressable testID="vec-download" style={styles.actionBtn} onPress={downloadDxf}>
              <Feather name="download" size={18} color={colors.onBrand} />
              <Text style={styles.actionText}>SCARICA DXF</Text>
            </Pressable>
            <View style={{ height: space.sm }} />
            <Pressable testID="vec-insert" style={[styles.actionBtn, styles.actionBtnAlt]} onPress={openPicker}>
              <Feather name="plus-square" size={18} color={colors.onSurface} />
              <Text style={[styles.actionText, { color: colors.onSurface }]}>INSERISCI IN UN TAPPETO</Text>
            </Pressable>
          </View>
        )}
      </ScrollView>

      <Modal visible={pickerOpen} transparent animationType="slide" onRequestClose={() => setPickerOpen(false)}>
        <View style={styles.modalRoot}>
          <View style={styles.modalCard}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>{selBoat ? selBoat.name : "SCEGLI PROGETTO"}</Text>
              <Pressable testID="picker-close" onPress={() => (selBoat ? setSelBoat(null) : setPickerOpen(false))} hitSlop={10}>
                <Feather name={selBoat ? "arrow-left" : "x"} size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <View style={styles.layerRow}>
              <Text style={styles.label}>Layer:</Text>
              {(["CUT", "ENGRAVE"] as const).map((l) => (
                <Pressable key={l} testID={`layer-${l}`} style={[styles.layerChip, insertLayer === l && styles.toggleOn]} onPress={() => setInsertLayer(l)}>
                  <Text style={[styles.toggleText, insertLayer === l && styles.toggleTextOn]}>{l === "CUT" ? "TAGLIO" : "INCISIONE"}</Text>
                </Pressable>
              ))}
            </View>
            <ScrollView style={{ maxHeight: 340 }} contentContainerStyle={{ padding: space.lg, paddingTop: 0 }}>
              {!selBoat
                ? boats.map((b) => (
                    <Pressable key={b.id} testID={`pick-boat-${b.id}`} style={styles.row} onPress={() => openBoat(b)}>
                      <MaterialCommunityIcons name="sail-boat" size={18} color={colors.brand} />
                      <Text style={styles.rowText}>{b.name}</Text>
                      <Text style={styles.rowMeta}>{b.piece_count || 0} pezzi</Text>
                      <Feather name="chevron-right" size={18} color={colors.onSurfaceTertiary} />
                    </Pressable>
                  ))
                : pieces.length === 0
                ? <Text style={styles.previewHint}>Nessun pezzo in questo progetto</Text>
                : pieces.map((p) => (
                    <Pressable key={p.id} testID={`pick-piece-${p.id}`} style={styles.row} disabled={inserting} onPress={() => insertInto(p)}>
                      <MaterialCommunityIcons name="vector-square" size={18} color={colors.onSurface} />
                      <Text style={styles.rowText}>{p.piece_name || "Pezzo"}</Text>
                      {inserting ? <ActivityIndicator size="small" color={colors.brand} /> : <Feather name="plus" size={18} color={colors.brand} />}
                    </Pressable>
                  ))}
              {!selBoat && boats.length === 0 ? (
                <Text style={styles.previewHint}>Nessun progetto. Creane uno dalla home.</Text>
              ) : null}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: space.lg, paddingVertical: space.md,
    borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong,
  },
  kicker: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.brand, letterSpacing: 2 },
  title: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 0.5 },
  preview: {
    minHeight: 200, borderWidth: BORDER, borderColor: colors.borderStrong,
    backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center", marginBottom: space.md,
    overflow: "hidden",
  },
  previewEmpty: { alignItems: "center", gap: space.sm, padding: space.lg },
  roi: { position: "absolute", borderWidth: 2, borderColor: colors.brand, backgroundColor: "rgba(184,74,0,0.12)" },
  roiBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: space.sm, marginBottom: space.md },
  roiHint: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, flex: 1 },
  roiClear: { flexDirection: "row", alignItems: "center", gap: 4, borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.sm, paddingVertical: 6 },
  roiClearText: { fontFamily: fonts.monoMed, fontSize: 11, color: colors.onSurface },
  thrHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: space.sm },
  autoChip: { borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 6, backgroundColor: colors.surface },
  previewHint: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, textAlign: "center" },
  pickRow: { flexDirection: "row", marginBottom: space.md },
  pickBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space.sm,
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: 12, backgroundColor: colors.surface,
  },
  pickText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  label: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: space.xs, textTransform: "uppercase" },
  segRow: { flexDirection: "row", gap: space.sm, marginBottom: space.md },
  segBtn: { flex: 1, alignItems: "center", borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: 10, backgroundColor: colors.surface },
  input: {
    borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface,
    paddingHorizontal: space.md, paddingVertical: 12, fontFamily: fonts.mono, fontSize: fontSize.base, color: colors.onSurface,
    marginBottom: space.md,
  },
  toggleRow: { flexDirection: "row", alignItems: "center", marginBottom: space.sm },
  toggle: { flexDirection: "row", alignItems: "center", gap: space.sm, borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 10, backgroundColor: colors.surface },
  toggleOn: { backgroundColor: colors.surfaceInverse },
  toggleText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  toggleTextOn: { color: colors.onSurfaceInverse },
  resultBox: { marginTop: space.lg, borderTopWidth: BORDER, borderTopColor: colors.border, paddingTop: space.lg },
  resultText: { fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onSurface },
  actionBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space.sm, backgroundColor: colors.brand, paddingVertical: 14 },
  actionBtnAlt: { backgroundColor: colors.surface, borderWidth: BORDER, borderColor: colors.borderStrong },
  actionText: { fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onBrand, letterSpacing: 0.5, textTransform: "uppercase" },
  modalRoot: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalCard: { backgroundColor: colors.surface, borderTopWidth: BORDER, borderColor: colors.borderStrong },
  modalHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: space.lg, borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong },
  modalTitle: { fontFamily: fonts.display, fontSize: fontSize.lg, color: colors.onSurface, letterSpacing: 0.5 },
  layerRow: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingHorizontal: space.lg, paddingVertical: space.md },
  layerChip: { borderWidth: BORDER, borderColor: colors.borderStrong, paddingHorizontal: space.md, paddingVertical: 8, backgroundColor: colors.surface },
  row: { flexDirection: "row", alignItems: "center", gap: space.md, borderWidth: BORDER, borderColor: colors.border, paddingHorizontal: space.md, paddingVertical: 14, marginTop: space.sm },
  rowText: { flex: 1, fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onSurface },
  rowMeta: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
});
