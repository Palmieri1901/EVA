import React, { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Modal, Platform, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import Svg, { Polygon, Polyline } from "react-native-svg";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import * as Sharing from "expo-sharing";
import * as FileSystem from "expo-file-system/legacy";

import { absUrl, api } from "@/src/api";
import { Btn, Tag } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

type Poly = number[][];

export default function ExportPreview() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();

  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [sheetBusy, setSheetBusy] = useState(false);
  const [shClient, setShClient] = useState("");
  const [shModel, setShModel] = useState("");
  const [shColor, setShColor] = useState("");

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const d = await api.preview(id);
      setData(d);
    } catch (e: any) {
      toast(e.message || "Errore anteprima", "error");
    } finally {
      setLoading(false);
    }
  }, [id, toast]);

  useEffect(() => {
    load();
  }, [load]);

  const allPolys: Poly[] = useMemo(() => {
    if (!data) return [];
    return [...(data.cut || []), ...(data.engrave || [])];
  }, [data]);

  const view = useMemo(() => {
    const pts = allPolys.flat();
    if (!pts.length) return { x: 0, y: 0, w: 100, h: 100 };
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const minX = Math.min(...xs), minY = Math.min(...ys);
    const w = Math.max(...xs) - minX, h = Math.max(...ys) - minY;
    const pad = Math.max(w, h) * 0.08 + 5;
    return { x: minX - pad, y: minY - pad, w: w + pad * 2, h: h + pad * 2 };
  }, [allPolys]);

  const ptsStr = (arr: Poly) => arr.map((p) => `${p[0]},${p[1]}`).join(" ");

  const doExport = async () => {
    if (!id) return;
    setExporting(true);
    try {
      const res = await api.exportDxf(id);
      const url = absUrl(res.dxf_url)!;
      if (Platform.OS === "web") {
        window.open(url, "_blank");
        toast("DXF generato", "success");
      } else {
        const fileUri = FileSystem.documentDirectory + `dima_${id}.dxf`;
        const dl = await FileSystem.downloadAsync(url, fileUri);
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(dl.uri, { mimeType: "application/dxf", dialogTitle: "Esporta DXF" });
        } else {
          toast("DXF salvato: " + dl.uri, "success");
        }
      }
    } catch (e: any) {
      toast(e.message || "Export fallito", "error");
    } finally {
      setExporting(false);
    }
  };

  const doSheet = async () => {
    if (!id) return;
    setSheetBusy(true);
    try {
      const res = await api.techsheet(id, { client: shClient, model: shModel, color: shColor });
      const url = absUrl(res.sheet_url)!;
      if (Platform.OS === "web") {
        window.open(url, "_blank");
        toast(`Scheda tecnica · ${res.area_m2.toFixed(2)} mq`, "success");
      } else {
        const fileUri = FileSystem.documentDirectory + `scheda_${id}.pdf`;
        const dl = await FileSystem.downloadAsync(url, fileUri);
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(dl.uri, { mimeType: "application/pdf", dialogTitle: "Scheda tecnica" });
        } else {
          toast("Scheda salvata: " + dl.uri, "success");
        }
      }
      setSheetOpen(false);
    } catch (e: any) {
      toast(e.message || "Scheda fallita", "error");
    } finally {
      setSheetBusy(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brand} size="large" />
        <Text style={styles.loadText}>COMPILAZIONE DXF...</Text>
      </View>
    );
  }

  const strokeW = Math.max(view.w, view.h) * 0.004;

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.topbar}>
        <Pressable testID="export-back" onPress={() => router.back()} hitSlop={12}>
          <Feather name="arrow-left" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>ANTEPRIMA DXF</Text>
        <View style={{ width: 22 }} />
      </View>

      <View style={styles.previewBox}>
        <Svg width="100%" height="100%" viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}>
          {(data?.engrave || []).map((pl: Poly, i: number) => (
            <Polyline key={`e${i}`} points={ptsStr(pl)} fill="none" stroke={colors.engrave} strokeWidth={strokeW} />
          ))}
          {(data?.cut || []).map((pl: Poly, i: number) =>
            i === 0 ? (
              <Polygon key={`c${i}`} points={ptsStr(pl)} fill="none" stroke={colors.cut} strokeWidth={strokeW * 1.4} />
            ) : (
              <Polyline key={`c${i}`} points={ptsStr(pl)} fill="none" stroke={colors.cut} strokeWidth={strokeW * 1.4} />
            )
          )}
        </Svg>
        <View style={[styles.legend, { pointerEvents: "none" }]}>
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: colors.cut }]} />
            <Text style={styles.legendText}>CUT</Text>
          </View>
          <View style={styles.legendItem}>
            <View style={[styles.legendDot, { backgroundColor: colors.engrave }]} />
            <Text style={styles.legendText}>ENGRAVE</Text>
          </View>
        </View>
      </View>

      <View style={styles.summary}>
        <View style={styles.sumRow}>
          <Text style={styles.sumLabel}>DIMENSIONI</Text>
          <Text style={styles.sumVal}>
            {data?.bbox?.w?.toFixed(1)} × {data?.bbox?.h?.toFixed(1)} mm
          </Text>
        </View>
        <View style={styles.sumRow}>
          <Text style={styles.sumLabel}>PERIMETRO TAGLIO</Text>
          <Text style={styles.sumVal}>{data?.perimeter_mm?.toFixed(0)} mm</Text>
        </View>
        <View style={styles.sumRow}>
          <Text style={styles.sumLabel}>POLILINEE</Text>
          <View style={{ flexDirection: "row", gap: space.sm }}>
            <Tag text={`CUT ${data?.cut_count ?? 0}`} color={colors.cut} />
            <Tag text={`ENGRAVE ${data?.engrave_count ?? 0}`} color={colors.engrave} />
          </View>
        </View>
        <View style={styles.sumRow}>
          <Text style={styles.sumLabel}>UNITÀ</Text>
          <Text style={styles.sumVal}>MILLIMETRI (mm)</Text>
        </View>
      </View>

      <View style={[styles.footer, { paddingBottom: insets.bottom + space.md }]}>
        <Pressable testID="techsheet-btn" style={styles.sheetBtn} onPress={() => setSheetOpen(true)}>
          <Feather name="file-text" size={18} color={colors.onSurface} />
          <Text style={styles.sheetBtnText}>SCHEDA TECNICA (PDF)</Text>
        </Pressable>
        <View style={{ height: space.md }} />
        <Btn
          testID="export-dxf-btn"
          label="ESPORTA DXF"
          loading={exporting}
          icon={<Feather name="share" size={20} color={colors.onBrand} />}
          onPress={doExport}
        />
      </View>

      <Modal visible={sheetOpen} transparent animationType="slide" onRequestClose={() => setSheetOpen(false)}>
        <View style={styles.modalRoot}>
          <View style={styles.modalCard}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>SCHEDA TECNICA</Text>
              <Pressable testID="sheet-close" onPress={() => setSheetOpen(false)} hitSlop={10}>
                <Feather name="x" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <View style={{ padding: space.lg }}>
              <Text style={styles.fLabel}>CLIENTE</Text>
              <TextInput testID="sheet-client" value={shClient} onChangeText={setShClient} placeholder="Es. Mattia Yacht" placeholderTextColor={colors.onSurfaceTertiary} style={styles.fInput} />
              <Text style={styles.fLabel}>MODELLO</Text>
              <TextInput testID="sheet-model" value={shModel} onChangeText={setShModel} placeholder="Es. GEB 800" placeholderTextColor={colors.onSurfaceTertiary} style={styles.fInput} />
              <Text style={styles.fLabel}>COLORE</Text>
              <TextInput testID="sheet-color" value={shColor} onChangeText={setShColor} placeholder="Es. Grigio / Teak" placeholderTextColor={colors.onSurfaceTertiary} style={styles.fInput} />
              <View style={{ height: space.md }} />
              <Btn testID="sheet-generate" label="GENERA PDF" loading={sheetBusy} icon={<Feather name="download" size={18} color={colors.onBrand} />} onPress={doSheet} />
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: space.md, backgroundColor: colors.surface },
  loadText: { fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onSurfaceSecondary },
  topbar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: space.lg, paddingVertical: space.md,
    borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong,
  },
  title: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  previewBox: { flex: 1, backgroundColor: colors.surfaceSecondary, borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong },
  legend: { position: "absolute", top: space.md, left: space.md, gap: 6 },
  legendItem: { flexDirection: "row", alignItems: "center", gap: 6 },
  legendDot: { width: 14, height: 4 },
  legendText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  summary: { padding: space.lg, gap: space.md },
  sumRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  sumLabel: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, letterSpacing: 0.5 },
  sumVal: { fontFamily: fonts.monoBold, fontSize: fontSize.lg, color: colors.onSurface },
  footer: { padding: space.lg, borderTopWidth: BORDER, borderTopColor: colors.borderStrong },
  sheetBtn: {
    flexDirection: "row", gap: space.sm, alignItems: "center", justifyContent: "center",
    borderWidth: BORDER, borderColor: colors.borderStrong, paddingVertical: space.md, backgroundColor: colors.surface,
  },
  sheetBtnText: { fontFamily: fonts.display, fontSize: fontSize.base, color: colors.onSurface, letterSpacing: 0.5 },
  modalRoot: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalCard: { backgroundColor: colors.surface, borderTopWidth: BORDER, borderColor: colors.borderStrong },
  modalHead: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: space.lg, borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong,
  },
  modalTitle: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  fLabel: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: space.xs, marginTop: space.sm, textTransform: "uppercase" },
  fInput: {
    borderWidth: BORDER, borderColor: colors.borderStrong, fontFamily: fonts.mono,
    fontSize: fontSize.base, color: colors.onSurface, paddingHorizontal: space.md, paddingVertical: space.md,
  },
});
