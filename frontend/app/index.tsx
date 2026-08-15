import React, { useCallback, useState } from "react";
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Image } from "expo-image";
import { useFocusEffect, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { api, absUrl, ProjectT } from "@/src/api";
import { Btn, Tag } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

const STATUS_LABEL: Record<string, string> = {
  draft: "BOZZA",
  captured: "FOTO OK",
  processed: "ELABORATO",
  edited: "MODIFICATO",
  exported: "ESPORTATO",
};

export default function Projects() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [projects, setProjects] = useState<ProjectT[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.listProjects();
      setProjects(data);
    } catch (e: any) {
      toast(e.message || "Errore di caricamento", "error");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [toast]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const onDelete = async (id: string) => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
    try {
      await api.deleteProject(id);
      setProjects((p) => p.filter((x) => x.id !== id));
      toast("Progetto eliminato", "info");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const renderItem = ({ item }: { item: ProjectT }) => {
    const thumb = absUrl(item.rectified_url || item.photo_url);
    return (
      <Pressable
        testID={`project-card-${item.id}`}
        style={styles.card}
        onPress={() => {
          Haptics.selectionAsync().catch(() => {});
          let route: string;
          if (item.capture_mode === "multi" && ["draft", "captured"].includes(item.status)) {
            route = `/shots/${item.id}`;
          } else if (item.status === "draft") {
            route = `/capture?id=${item.id}`;
          } else {
            route = `/editor/${item.id}`;
          }
          router.push(route as any);
        }}
      >
        <View style={styles.thumb}>
          {thumb ? (
            <Image source={{ uri: thumb }} style={{ width: "100%", height: "100%" }} contentFit="cover" />
          ) : (
            <MaterialCommunityIcons name="image-off-outline" size={28} color={colors.onSurfaceTertiary} />
          )}
        </View>
        <View style={styles.cardBody}>
          <Text style={styles.cardTitle} numberOfLines={1}>
            {item.name}
          </Text>
          <Text style={styles.cardMeta}>
            {Math.round(item.ref_width_mm)} × {Math.round(item.ref_height_mm)} mm
          </Text>
          <Text style={styles.cardMeta}>
            {item.background_mode === "blue_on_white" ? "NASTRO BLU" : "NASTRO BIANCO"} · Ø
            {item.marker_diameter_mm}mm
          </Text>
          <View style={styles.cardTags}>
            <Tag text={STATUS_LABEL[item.status] || item.status} color={colors.brand} />
            {item.elements?.length ? <Tag text={`${item.elements.length} EL.`} /> : null}
          </View>
        </View>
        <Pressable
          testID={`delete-${item.id}`}
          hitSlop={10}
          style={styles.deleteBtn}
          onPress={() => onDelete(item.id)}
        >
          <Feather name="trash-2" size={18} color={colors.error} />
        </Pressable>
      </Pressable>
    );
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <View>
          <Text style={styles.kicker}>EVA · BOAT MAT</Text>
          <Text style={styles.h1}>DIGITIZER</Text>
        </View>
        <MaterialCommunityIcons name="ruler-square-compass" size={32} color={colors.brand} />
      </View>

      <FlatList
        data={projects}
        keyExtractor={(i) => i.id}
        renderItem={renderItem}
        contentContainerStyle={{ padding: space.lg, paddingBottom: 140 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              load();
            }}
            tintColor={colors.brand}
          />
        }
        ListEmptyComponent={
          !loading ? (
            <View style={styles.empty} testID="empty-state">
              <MaterialCommunityIcons name="vector-square" size={64} color={colors.onSurfaceTertiary} />
              <Text style={styles.emptyTitle}>0 PROGETTI TROVATI</Text>
              <Text style={styles.emptyText}>
                Avvia una nuova digitalizzazione per estrarre la dima dalla foto.
              </Text>
            </View>
          ) : null
        }
      />

      <View style={[styles.footer, { paddingBottom: insets.bottom + space.md }]}>
        <Btn
          testID="new-project-btn"
          label="NUOVA DIGITALIZZAZIONE"
          icon={<Feather name="plus" size={20} color={colors.onBrand} />}
          onPress={() => router.push("/new-project")}
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: space.lg,
    paddingVertical: space.lg,
    borderBottomWidth: BORDER,
    borderBottomColor: colors.borderStrong,
  },
  kicker: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.brand, letterSpacing: 2 },
  h1: { fontFamily: fonts.display, fontSize: fontSize["3xl"], color: colors.onSurface, letterSpacing: 1 },
  card: {
    flexDirection: "row",
    borderWidth: BORDER,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
    marginBottom: space.md,
  },
  thumb: {
    width: 96,
    height: 96,
    borderRightWidth: BORDER,
    borderRightColor: colors.borderStrong,
    backgroundColor: colors.surfaceTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  cardBody: { flex: 1, padding: space.md, gap: 2 },
  cardTitle: { fontFamily: fonts.display, fontSize: fontSize.lg, color: colors.onSurface },
  cardMeta: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  cardTags: { flexDirection: "row", gap: space.sm, marginTop: space.xs },
  deleteBtn: {
    width: 44,
    alignItems: "center",
    justifyContent: "center",
    borderLeftWidth: BORDER,
    borderLeftColor: colors.border,
  },
  empty: { alignItems: "center", paddingTop: 80, gap: space.md },
  emptyTitle: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  emptyText: {
    fontFamily: fonts.mono,
    fontSize: fontSize.base,
    color: colors.onSurfaceSecondary,
    textAlign: "center",
    paddingHorizontal: space.xl,
  },
  footer: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    padding: space.lg,
    borderTopWidth: BORDER,
    borderTopColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
});
