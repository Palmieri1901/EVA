import React, { useCallback, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Modal,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Image } from "expo-image";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import * as Sharing from "expo-sharing";
import * as FileSystem from "expo-file-system/legacy";

import { absUrl, api, BoatT, ProjectT } from "@/src/api";
import { Btn, Tag } from "@/src/components/ui";
import { ExportFormatBar, ExportFmt } from "@/src/components/export-formats";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

const STATUS_LABEL: Record<string, string> = {
  draft: "BOZZA",
  captured: "FOTO OK",
  processed: "ELABORATO",
  edited: "MODIFICATO",
  exported: "ESPORTATO",
};

async function shareFile(url: string, name: string, mime: string, toast: any, successMsg: string) {
  if (Platform.OS === "web") {
    window.open(url, "_blank");
    toast(successMsg, "success");
    return;
  }
  const fileUri = FileSystem.documentDirectory + name;
  const dl = await FileSystem.downloadAsync(url, fileUri);
  if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(dl.uri, { mimeType: mime, dialogTitle: successMsg });
  } else {
    toast(name + " salvato", "success");
  }
}

export default function BoatDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();

  const [boat, setBoat] = useState<BoatT | null>(null);
  const [pieces, setPieces] = useState<ProjectT[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const b = await api.getBoat(id);
      setBoat(b);
      setPieces(b.pieces || []);
    } catch (e: any) {
      toast(e.message || "Errore di caricamento", "error");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [id, toast]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const pieceRoute = (p: ProjectT) => {
    if (p.capture_mode === "multi" && ["draft", "captured"].includes(p.status)) return `/shots/${p.id}`;
    if (p.status === "draft") return `/capture?id=${p.id}`;
    return `/editor/${p.id}`;
  };

  const onDeletePiece = async (pid: string) => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
    try {
      await api.deleteProject(pid);
      setPieces((p) => p.filter((x) => x.id !== pid));
      toast("Pezzo eliminato", "info");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const doAssembly = async () => {
    if (!id) return;
    setPdfBusy(true);
    try {
      const res = await api.boatAssembly(id);
      await shareFile(absUrl(res.sheet_url)!, `assemblato_${id}.pdf`, "application/pdf", toast,
        `PDF assemblato · ${res.count} pezzi · ${res.total_area_m2.toFixed(2)} mq`);
      if (res.overflow) toast("⚠ I pezzi superano un foglio EVA (90×240)", "info");
    } catch (e: any) {
      toast(e.message || "PDF assemblato fallito", "error");
    } finally {
      setPdfBusy(false);
    }
  };

  const doNestedExport = async (fmt: ExportFmt, body: any) => {
    if (!id) return;
    setExportBusy(true);
    try {
      const res = await api.exportBoatFormat(id, fmt, body);
      const mime =
        fmt === "svg" ? "image/svg+xml" : fmt === "png" ? "image/png"
        : fmt === "pdf" ? "application/pdf" : fmt === "gcode" ? "text/plain" : "application/dxf";
      await shareFile(absUrl(res.url)!, `foglio_${id}.${res.ext}`, mime, toast,
        `Foglio ${fmt.toUpperCase()} · ${res.count} pezzi`);
      if (res.overflow) toast("⚠ I pezzi superano un foglio EVA (90×240)", "info");
      setExportOpen(false);
    } catch (e: any) {
      toast(e.message || "Export foglio fallito", "error");
    } finally {
      setExportBusy(false);
    }
  };

  const renderItem = ({ item, index }: { item: ProjectT; index: number }) => {
    const thumb = absUrl(item.rectified_url || item.photo_url);
    return (
      <Pressable
        testID={`piece-card-${item.id}`}
        style={styles.card}
        onPress={() => {
          Haptics.selectionAsync().catch(() => {});
          router.push(pieceRoute(item) as any);
        }}
      >
        <View style={styles.thumb}>
          {thumb ? (
            <Image source={{ uri: thumb }} style={{ width: "100%", height: "100%" }} contentFit="cover" />
          ) : (
            <MaterialCommunityIcons name="image-off-outline" size={26} color={colors.onSurfaceTertiary} />
          )}
        </View>
        <View style={styles.cardBody}>
          <Text style={styles.cardTitle} numberOfLines={1}>
            {item.piece_name || `Pezzo ${index + 1}`}
          </Text>
          <Text style={styles.cardMeta}>
            {Math.round(item.ref_width_mm)} × {Math.round(item.ref_height_mm)} mm
          </Text>
          <View style={styles.cardTags}>
            <Tag text={STATUS_LABEL[item.status] || item.status} color={colors.brand} />
            {item.elements?.length ? <Tag text={`${item.elements.length} EL.`} /> : null}
          </View>
        </View>
        <Pressable
          testID={`delete-piece-${item.id}`}
          hitSlop={10}
          style={styles.deleteBtn}
          onPress={() => onDeletePiece(item.id)}
        >
          <Feather name="trash-2" size={18} color={colors.error} />
        </Pressable>
      </Pressable>
    );
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brand} size="large" />
      </View>
    );
  }

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Pressable testID="back-btn" onPress={() => router.back()} hitSlop={12}>
          <Feather name="arrow-left" size={24} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1, marginLeft: space.md }}>
          <Text style={styles.kicker}>PROGETTO</Text>
          <Text style={styles.title} numberOfLines={1}>{boat?.name}</Text>
        </View>
      </View>

      <FlatList
        data={pieces}
        keyExtractor={(i) => i.id}
        renderItem={renderItem}
        contentContainerStyle={{ padding: space.lg, paddingBottom: 220 }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.brand} />
        }
        ListHeaderComponent={
          <Text style={styles.sectionLabel}>TAPPETI / PEZZI ({pieces.length})</Text>
        }
        ListEmptyComponent={
          <View style={styles.empty} testID="empty-pieces">
            <MaterialCommunityIcons name="vector-square" size={56} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyText}>Nessun pezzo. Aggiungi il primo tappeto di questo progetto.</Text>
          </View>
        }
      />

      <View style={[styles.footer, { paddingBottom: insets.bottom + space.md }]}>
        {pieces.length > 0 && (
          <View style={styles.exportRow}>
            <Pressable testID="assembly-pdf-btn" style={styles.secBtn} onPress={doAssembly} disabled={pdfBusy}>
              {pdfBusy ? <ActivityIndicator size="small" color={colors.onSurface} /> : (
                <>
                  <Feather name="grid" size={16} color={colors.onSurface} />
                  <Text style={styles.secBtnText}>PDF ASSEMBLATO</Text>
                </>
              )}
            </Pressable>
            <View style={{ width: space.md }} />
            <Pressable testID="export-sheet-btn" style={styles.secBtn} onPress={() => setExportOpen(true)}>
              <MaterialCommunityIcons name="content-cut" size={16} color={colors.onSurface} />
              <Text style={styles.secBtnText}>ESPORTA FOGLIO</Text>
            </Pressable>
          </View>
        )}
        <Btn
          testID="add-piece-btn"
          label="AGGIUNGI PEZZO"
          icon={<Feather name="plus" size={20} color={colors.onBrand} />}
          onPress={() => router.push(`/new-project?boat_id=${id}&n=${pieces.length + 1}` as any)}
        />
      </View>

      <Modal visible={exportOpen} transparent animationType="slide" onRequestClose={() => setExportOpen(false)}>
        <View style={styles.modalRoot}>
          <View style={styles.modalCard}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>ESPORTA FOGLIO UNICO</Text>
              <Pressable testID="export-close" onPress={() => setExportOpen(false)} hitSlop={10}>
                <Feather name="x" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ padding: space.lg, paddingBottom: insets.bottom + space.lg }} style={{ maxHeight: 560 }}>
              <Text style={styles.hint}>Tutti i pezzi annidati sul foglio EVA 90×240 cm</Text>
              <ExportFormatBar busy={exportBusy} onExport={doNestedExport} />
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: space.lg, paddingVertical: space.md,
    borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong,
  },
  kicker: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.brand, letterSpacing: 2 },
  title: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 0.5 },
  sectionLabel: {
    fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurfaceSecondary,
    marginBottom: space.md, letterSpacing: 0.5, textTransform: "uppercase",
  },
  card: {
    flexDirection: "row", borderWidth: BORDER, borderColor: colors.borderStrong,
    backgroundColor: colors.surface, marginBottom: space.md,
  },
  thumb: {
    width: 88, height: 88, borderRightWidth: BORDER, borderRightColor: colors.borderStrong,
    backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center",
  },
  cardBody: { flex: 1, padding: space.md, gap: 2, justifyContent: "center" },
  cardTitle: { fontFamily: fonts.display, fontSize: fontSize.lg, color: colors.onSurface },
  cardMeta: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  cardTags: { flexDirection: "row", gap: space.sm, marginTop: space.xs },
  deleteBtn: {
    width: 44, alignItems: "center", justifyContent: "center",
    borderLeftWidth: BORDER, borderLeftColor: colors.border,
  },
  empty: { alignItems: "center", paddingTop: 60, gap: space.md },
  emptyText: {
    fontFamily: fonts.mono, fontSize: fontSize.base, color: colors.onSurfaceSecondary,
    textAlign: "center", paddingHorizontal: space.xl,
  },
  footer: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    padding: space.lg, borderTopWidth: BORDER, borderTopColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  exportRow: { flexDirection: "row", marginBottom: space.md },
  secBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space.sm,
    borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface,
    paddingVertical: 12,
  },
  secBtnText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface, letterSpacing: 0.3 },
  modalRoot: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  modalCard: { backgroundColor: colors.surface, borderTopWidth: BORDER, borderColor: colors.borderStrong },
  modalHead: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: space.lg, borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong,
  },
  modalTitle: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  hint: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: space.md },
});
