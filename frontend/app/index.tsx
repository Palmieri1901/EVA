import React, { useCallback, useState } from "react";
import {
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Image } from "expo-image";
import { useFocusEffect, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { api, absUrl, BoatT } from "@/src/api";
import { Btn } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { useMachine } from "@/src/machine";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

export default function Boats() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { machine, setMachine } = useMachine();
  const [boats, setBoats] = useState<BoatT[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [boatName, setBoatName] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.listBoats();
      setBoats(data);
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
      await api.deleteBoat(id);
      setBoats((b) => b.filter((x) => x.id !== id));
      toast("Progetto eliminato", "info");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const createBoat = async () => {
    setCreating(true);
    try {
      const boat = await api.createBoat({ name: boatName.trim() || "Nuova imbarcazione" });
      setCreateOpen(false);
      setBoatName("");
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      router.push(`/boat/${boat.id}` as any);
    } catch (e: any) {
      toast(e.message || "Errore creazione progetto", "error");
    } finally {
      setCreating(false);
    }
  };

  const renderItem = ({ item }: { item: BoatT }) => {
    const thumb = absUrl(item.thumb_url);
    return (
      <Pressable
        testID={`boat-card-${item.id}`}
        style={styles.card}
        onPress={() => {
          Haptics.selectionAsync().catch(() => {});
          router.push(`/boat/${item.id}` as any);
        }}
      >
        <View style={styles.thumb}>
          {thumb ? (
            <Image source={{ uri: thumb }} style={{ width: "100%", height: "100%" }} contentFit="cover" />
          ) : (
            <MaterialCommunityIcons name="sail-boat" size={30} color={colors.onSurfaceTertiary} />
          )}
        </View>
        <View style={styles.cardBody}>
          <Text style={styles.cardTitle} numberOfLines={1}>
            {item.name}
          </Text>
          <Text style={styles.cardMeta}>
            {item.piece_count || 0} {item.piece_count === 1 ? "pezzo" : "pezzi"}
          </Text>
        </View>
        <Feather name="chevron-right" size={20} color={colors.onSurfaceTertiary} style={{ alignSelf: "center", marginRight: 4 }} />
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
          <Text style={styles.h1}>PROGETTI</Text>
        </View>
        <Pressable testID="open-tools" hitSlop={10} onPress={() => { Haptics.selectionAsync().catch(() => {}); router.push("/tools" as any); }}>
          <MaterialCommunityIcons name="tools" size={30} color={colors.brand} />
        </Pressable>
      </View>

      <View style={styles.machineRow}>
        <Pressable
          testID="machine-cnc"
          style={[styles.machineBtn, machine === "cnc" && styles.machineBtnOn]}
          onPress={() => { Haptics.selectionAsync().catch(() => {}); setMachine("cnc"); }}
        >
          <MaterialCommunityIcons name="router" size={20} color={machine === "cnc" ? colors.onSurfaceInverse : colors.onSurface} />
          <Text style={[styles.machineText, machine === "cnc" && styles.machineTextOn]}>FRESA CNC</Text>
          <Text style={[styles.machineSub, machine === "cnc" && styles.machineTextOn]}>Tappeti EVA · teak</Text>
        </Pressable>
        <Pressable
          testID="machine-laser"
          style={[styles.machineBtn, machine === "laser" && styles.machineBtnOn]}
          onPress={() => { Haptics.selectionAsync().catch(() => {}); setMachine("laser"); }}
        >
          <MaterialCommunityIcons name="laser-pointer" size={20} color={machine === "laser" ? colors.onSurfaceInverse : colors.onSurface} />
          <Text style={[styles.machineText, machine === "laser" && styles.machineTextOn]}>LASER</Text>
          <Text style={[styles.machineSub, machine === "laser" && styles.machineTextOn]}>Taglio gomma · DXF</Text>
        </Pressable>
      </View>

      <Pressable
        testID="vectorize-btn"
        style={styles.vecBtn}
        onPress={() => { Haptics.selectionAsync().catch(() => {}); router.push("/vectorize" as any); }}
      >
        <Feather name="camera" size={16} color={colors.onSurface} />
        <Text style={styles.vecText}>VETTORIZZA LOGO / SCRITTA DA FOTO → DXF</Text>
        <Feather name="chevron-right" size={18} color={colors.onSurfaceTertiary} />
      </Pressable>

      <FlatList
        data={boats}
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
              <MaterialCommunityIcons name="sail-boat" size={64} color={colors.onSurfaceTertiary} />
              <Text style={styles.emptyTitle}>0 PROGETTI</Text>
              <Text style={styles.emptyText}>
                Crea un progetto (imbarcazione) e aggiungi i suoi tappeti/pezzi.
              </Text>
            </View>
          ) : null
        }
      />

      <View style={[styles.footer, { paddingBottom: insets.bottom + space.md }]}>
        <Btn
          testID="new-boat-btn"
          label="NUOVO PROGETTO"
          icon={<Feather name="plus" size={20} color={colors.onBrand} />}
          onPress={() => {
            setBoatName("");
            setCreateOpen(true);
          }}
        />
      </View>

      <Modal visible={createOpen} transparent animationType="slide" onRequestClose={() => setCreateOpen(false)}>
        <View style={styles.modalRoot}>
          <View style={styles.modalCard}>
            <View style={styles.modalHead}>
              <Text style={styles.modalTitle}>NUOVO PROGETTO</Text>
              <Pressable testID="create-close" onPress={() => setCreateOpen(false)} hitSlop={10}>
                <Feather name="x" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            <View style={{ padding: space.lg }}>
              <Text style={styles.modalLabel}>Nome imbarcazione</Text>
              <TextInput
                testID="boat-name-input"
                value={boatName}
                onChangeText={setBoatName}
                placeholder="Es. Azimut 55 · Rossi"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.modalInput}
                autoFocus
              />
              <View style={{ height: space.lg }} />
              <Btn testID="boat-create-confirm" label="CREA PROGETTO" loading={creating} onPress={createBoat} />
            </View>
          </View>
        </View>
      </Modal>
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
  machineRow: { flexDirection: "row", gap: space.md, paddingHorizontal: space.lg, paddingTop: space.md },
  machineBtn: {
    flex: 1, borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface,
    padding: space.md, gap: 2, alignItems: "flex-start",
  },
  machineBtnOn: { backgroundColor: colors.surfaceInverse },
  machineText: { fontFamily: fonts.display, fontSize: fontSize.lg, color: colors.onSurface, letterSpacing: 0.5, marginTop: 4 },
  machineSub: { fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceSecondary },
  machineTextOn: { color: colors.onSurfaceInverse },
  vecBtn: {
    flexDirection: "row", alignItems: "center", gap: space.sm,
    marginHorizontal: space.lg, marginTop: space.md, paddingHorizontal: space.md, paddingVertical: 12,
    borderWidth: BORDER, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  vecText: { flex: 1, fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface, letterSpacing: 0.3 },
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
  cardBody: { flex: 1, padding: space.md, gap: 4, justifyContent: "center" },
  cardTitle: { fontFamily: fonts.display, fontSize: fontSize.lg, color: colors.onSurface },
  cardMeta: { fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
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
  modalRoot: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(0,0,0,0.45)" },
  modalCard: { backgroundColor: colors.surface, borderTopWidth: BORDER, borderColor: colors.borderStrong },
  modalHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    padding: space.lg, borderBottomWidth: BORDER, borderBottomColor: colors.borderStrong,
  },
  modalTitle: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  modalLabel: {
    fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurfaceSecondary,
    marginBottom: space.xs, textTransform: "uppercase",
  },
  modalInput: {
    borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface,
    paddingHorizontal: space.md, paddingVertical: 12, fontFamily: fonts.mono,
    fontSize: fontSize.base, color: colors.onSurface,
  },
});
