import React, { useCallback, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { absUrl, api, ShotT } from "@/src/api";
import { Btn, Tag } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

export default function Shots() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();

  const [shots, setShots] = useState<ShotT[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [stitching, setStitching] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const data = await api.listShots(id);
      setShots(data);
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

  const addFromGallery = async () => {
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.85 });
    if (res.canceled || !res.assets?.[0]?.uri || !id) return;
    setBusy(true);
    try {
      const s = await api.addShot(id, res.assets[0].uri);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast(`Scatto aggiunto · ${s.n_markers} bollini`, "success");
      load();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (shotId: string) => {
    try {
      await api.deleteShot(id, shotId);
      setShots((p) => p.filter((s) => s.id !== shotId));
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const doStitch = async () => {
    if (!id || shots.length === 0) return;
    setStitching(true);
    try {
      const r = await api.stitch(id);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      if (r.unanchored.length > 0) {
        toast(
          `${r.anchored.length}/${shots.length} scatti uniti. ${r.unanchored.length} non agganciati: aumenta la sovrapposizione.`,
          "info"
        );
      } else {
        toast(`Uniti ${r.anchored.length} scatti · piano ${Math.round(r.plane_w_mm)}×${Math.round(r.plane_h_mm)}mm`, "success");
      }
      router.replace(`/editor/${id}` as any);
    } catch (e: any) {
      toast(e.message || "Unione fallita", "error");
    } finally {
      setStitching(false);
    }
  };

  const renderItem = ({ item, index }: { item: ShotT; index: number }) => {
    const thumb = absUrl(item.photo_url);
    return (
      <View style={styles.card} testID={`shot-card-${index}`}>
        <View style={styles.thumb}>
          {thumb ? (
            <Image source={{ uri: thumb }} style={{ width: "100%", height: "100%" }} contentFit="cover" />
          ) : (
            <MaterialCommunityIcons name="image" size={26} color={colors.onSurfaceTertiary} />
          )}
        </View>
        <View style={styles.cardBody}>
          <Text style={styles.cardTitle}>SCATTO {index + 1}</Text>
          <Text style={styles.cardMeta}>{item.n_markers} bollini rilevati</Text>
          <View style={{ flexDirection: "row", gap: space.sm, marginTop: 4 }}>
            {item.n_markers >= 4 ? (
              <Tag text="OK MARKER" color={colors.success} />
            ) : (
              <Tag text="POCHI MARKER" color={colors.error} />
            )}
            {item.anchored ? <Tag text="AGGANCIATO" color={colors.brand} /> : null}
          </View>
        </View>
        <Pressable testID={`delete-shot-${index}`} hitSlop={10} style={styles.del} onPress={() => onDelete(item.id)}>
          <Feather name="trash-2" size={18} color={colors.error} />
        </Pressable>
      </View>
    );
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Pressable testID="shots-back" onPress={() => router.replace("/")} hitSlop={12}>
          <Feather name="arrow-left" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>MULTI-SCATTO</Text>
        <View style={{ width: 22 }} />
      </View>

      <View style={styles.infoBox}>
        <Feather name="info" size={14} color={colors.brand} />
        <Text style={styles.infoText}>
          Scatta dall'alto, tenendo il telefono parallelo al piano. Ogni nuovo scatto deve
          condividere almeno 4 bollini con l'area già ripresa (zona di sovrapposizione).
        </Text>
      </View>

      <FlatList
        data={shots}
        keyExtractor={(i) => i.id}
        renderItem={renderItem}
        contentContainerStyle={{ padding: space.lg, paddingBottom: 220 }}
        ListEmptyComponent={
          !loading ? (
            <View style={styles.empty}>
              <MaterialCommunityIcons name="camera-burst" size={56} color={colors.onSurfaceTertiary} />
              <Text style={styles.emptyText}>Nessuno scatto. Aggiungi il primo (deve contenere i 4 bollini d'angolo del riquadro di riferimento).</Text>
            </View>
          ) : null
        }
      />

      <View style={[styles.footer, { paddingBottom: insets.bottom + space.md }]}>
        <View style={styles.addRow}>
          <Pressable testID="add-shot-camera" style={styles.addBtn} onPress={() => router.push(`/capture?id=${id}&shot=1` as any)}>
            <Feather name="camera" size={18} color={colors.onSurface} />
            <Text style={styles.addText}>SCATTA</Text>
          </Pressable>
          <Pressable testID="add-shot-gallery" style={styles.addBtn} onPress={addFromGallery}>
            {busy ? <ActivityIndicator color={colors.onSurface} /> : <Feather name="image" size={18} color={colors.onSurface} />}
            <Text style={styles.addText}>GALLERIA</Text>
          </Pressable>
        </View>
        <Btn
          testID="stitch-btn"
          label={`UNISCI E VETTORIALIZZA (${shots.length})`}
          disabled={shots.length === 0}
          loading={stitching}
          icon={<MaterialCommunityIcons name="vector-union" size={20} color={colors.onBrand} />}
          onPress={doStitch}
        />
      </View>
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
    padding: space.md, margin: space.lg, marginBottom: 0,
  },
  infoText: { flex: 1, fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurface },
  card: {
    flexDirection: "row", borderWidth: BORDER, borderColor: colors.borderStrong,
    marginBottom: space.md, backgroundColor: colors.surface,
  },
  thumb: {
    width: 88, height: 88, borderRightWidth: BORDER, borderRightColor: colors.borderStrong,
    backgroundColor: colors.surfaceTertiary, alignItems: "center", justifyContent: "center",
  },
  cardBody: { flex: 1, padding: space.md },
  cardTitle: { fontFamily: fonts.display, fontSize: fontSize.lg, color: colors.onSurface },
  cardMeta: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: 2 },
  del: { width: 44, alignItems: "center", justifyContent: "center", borderLeftWidth: BORDER, borderLeftColor: colors.border },
  empty: { alignItems: "center", paddingTop: 60, gap: space.md, paddingHorizontal: space.xl },
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
});
