import React, { useCallback, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useFocusEffect, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { api, ToolT } from "@/src/api";
import { useToast } from "@/src/components/toast";
import { colors, fonts, fontSize, space } from "@/src/theme";

// AutoCAD Color Index -> hex, for the color picker
const ACI: { aci: number; hex: string }[] = [
  { aci: 1, hex: "#DC2626" }, // red
  { aci: 2, hex: "#EAB308" }, // yellow
  { aci: 3, hex: "#16A34A" }, // green
  { aci: 4, hex: "#06B6D4" }, // cyan
  { aci: 5, hex: "#2563EB" }, // blue
  { aci: 6, hex: "#DB2777" }, // magenta
  { aci: 30, hex: "#EA580C" }, // orange
  { aci: 7, hex: "#111111" }, // black/white
];

const NUM_FIELDS: { key: keyof ToolT; label: string; unit: string; kb: "decimal-pad" | "number-pad" }[] = [
  { key: "depth_mm", label: "Profondità", unit: "mm", kb: "decimal-pad" },
  { key: "feed_mm_min", label: "Avanzamento (feed)", unit: "mm/min", kb: "decimal-pad" },
  { key: "spindle_rpm", label: "Mandrino", unit: "rpm", kb: "decimal-pad" },
  { key: "bit_diameter_mm", label: "Ø punta", unit: "mm", kb: "decimal-pad" },
  { key: "passes", label: "Passate", unit: "n", kb: "number-pad" },
];

export default function ToolsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const [tools, setTools] = useState<ToolT[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const { tools } = await api.getTools();
      setTools(tools);
    } catch (e: any) {
      toast(e.message || "Errore di caricamento utensili", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useFocusEffect(
    useCallback(() => {
      load();
    }, [load])
  );

  const patch = (id: string, key: keyof ToolT, value: any) =>
    setTools((ts) => ts.map((t) => (t.id === id ? { ...t, [key]: value } : t)));

  const setColor = (id: string, aci: number, hex: string) => {
    Haptics.selectionAsync().catch(() => {});
    setTools((ts) => ts.map((t) => (t.id === id ? { ...t, color_aci: aci, color_hex: hex } : t)));
  };

  const onSave = async () => {
    setSaving(true);
    try {
      const payload = tools.map((t) => ({
        ...t,
        depth_mm: parseFloat(String(t.depth_mm)) || 0,
        feed_mm_min: parseFloat(String(t.feed_mm_min)) || 0,
        spindle_rpm: parseFloat(String(t.spindle_rpm)) || 0,
        bit_diameter_mm: parseFloat(String(t.bit_diameter_mm)) || 0,
        passes: parseInt(String(t.passes)) || 1,
      }));
      const { tools: saved } = await api.saveTools(payload as ToolT[]);
      setTools(saved);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      toast("Impostazioni utensili salvate", "success");
    } catch (e: any) {
      toast(e.message || "Salvataggio non riuscito", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Pressable testID="tools-back" hitSlop={12} onPress={() => router.back()}>
          <Feather name="chevron-left" size={26} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={styles.kicker}>CNC · UTENSILI</Text>
          <Text style={styles.h1}>UTENSILI MACCHINA</Text>
        </View>
      </View>

      {loading ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.brand} />
        </View>
      ) : (
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          keyboardVerticalOffset={insets.top + 60}
        >
          <ScrollView
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={{ padding: space.lg, paddingBottom: 160 }}
          >
            <Text style={styles.intro}>
              Ogni tipo di lavorazione è identificato da un colore (layer DXF) e dalle impostazioni
              macchina qui sotto. FUGA e CONTORNO incidono, TAGLIO e SVASO tagliano.
            </Text>
            {tools.map((t) => (
              <View key={t.id} style={styles.card}>
                <View style={styles.cardHead}>
                  <View style={[styles.swatch, { backgroundColor: t.color_hex }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.toolId}>{t.id}</Text>
                    <TextInput
                      testID={`tool-name-${t.id}`}
                      value={t.name}
                      onChangeText={(v) => patch(t.id, "name", v)}
                      style={styles.nameInput}
                      placeholder="Nome utensile"
                      placeholderTextColor={colors.onSurfaceTertiary}
                    />
                  </View>
                </View>

                <Text style={styles.rowLabel}>Colore layer DXF</Text>
                <View style={styles.palette}>
                  {ACI.map((c) => (
                    <Pressable
                      key={c.aci}
                      testID={`tool-color-${t.id}-${c.aci}`}
                      onPress={() => setColor(t.id, c.aci, c.hex)}
                      style={[
                        styles.colorDot,
                        { backgroundColor: c.hex },
                        t.color_aci === c.aci && styles.colorDotOn,
                      ]}
                    >
                      {t.color_aci === c.aci ? (
                        <Feather name="check" size={14} color="#FFFFFF" />
                      ) : null}
                    </Pressable>
                  ))}
                </View>

                <View style={styles.grid}>
                  <View style={styles.gridItem}>
                    <Text style={styles.rowLabel}>N° utensile</Text>
                    <View style={styles.inputWrap}>
                      <TextInput
                        testID={`tool-no-${t.id}`}
                        value={String(t.tool_no)}
                        onChangeText={(v) => patch(t.id, "tool_no", v)}
                        style={styles.input}
                        placeholder="T1"
                        placeholderTextColor={colors.onSurfaceTertiary}
                      />
                    </View>
                  </View>
                  {NUM_FIELDS.map((f) => (
                    <View key={String(f.key)} style={styles.gridItem}>
                      <Text style={styles.rowLabel}>{f.label}</Text>
                      <View style={styles.inputWrap}>
                        <TextInput
                          testID={`tool-${String(f.key)}-${t.id}`}
                          value={String((t as any)[f.key])}
                          onChangeText={(v) => patch(t.id, f.key, v)}
                          keyboardType={f.kb}
                          style={styles.input}
                          placeholderTextColor={colors.onSurfaceTertiary}
                        />
                        <Text style={styles.unit}>{f.unit}</Text>
                      </View>
                    </View>
                  ))}
                </View>
              </View>
            ))}
          </ScrollView>
        </KeyboardAvoidingView>
      )}

      <View style={[styles.footer, { paddingBottom: insets.bottom + space.md }]}>
        <Pressable testID="tools-save" style={styles.saveBtn} onPress={onSave} disabled={saving}>
          {saving ? (
            <ActivityIndicator size="small" color={colors.onSurfaceInverse} />
          ) : (
            <>
              <Feather name="save" size={16} color={colors.onSurfaceInverse} />
              <Text style={styles.saveText}>SALVA IMPOSTAZIONI</Text>
            </>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingHorizontal: space.lg, paddingVertical: space.md },
  kicker: { fontFamily: fonts.mono, fontSize: 11, letterSpacing: 2, color: colors.brand },
  h1: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  intro: { fontFamily: fonts.displayReg, fontSize: 13, color: colors.onSurfaceSecondary, marginBottom: space.lg, lineHeight: 18 },
  card: { borderWidth: 1.5, borderColor: colors.onSurface, padding: space.md, marginBottom: space.lg },
  cardHead: { flexDirection: "row", alignItems: "center", gap: space.sm, marginBottom: space.md },
  swatch: { width: 34, height: 34, borderWidth: 1.5, borderColor: colors.onSurface },
  toolId: { fontFamily: fonts.mono, fontSize: 11, letterSpacing: 1.5, color: colors.brand },
  nameInput: { fontFamily: fonts.display, fontSize: 16, color: colors.onSurface, paddingVertical: 2 },
  rowLabel: { fontFamily: fonts.mono, fontSize: 10, letterSpacing: 1, color: colors.onSurfaceSecondary, marginBottom: 4 },
  palette: { flexDirection: "row", flexWrap: "wrap", gap: space.sm, marginBottom: space.md },
  colorDot: { width: 30, height: 30, borderRadius: 15, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: "transparent" },
  colorDotOn: { borderColor: colors.onSurface },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  gridItem: { width: "47%" },
  inputWrap: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderColor: colors.divider, paddingHorizontal: space.sm, marginBottom: space.sm },
  input: { flex: 1, minWidth: 0, fontFamily: fonts.mono, fontSize: 15, color: colors.onSurface, paddingVertical: 10 },
  unit: { fontFamily: fonts.mono, fontSize: 10, color: colors.onSurfaceTertiary },
  footer: { position: "absolute", left: 0, right: 0, bottom: 0, paddingHorizontal: space.lg, paddingTop: space.md, backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.divider },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space.sm, backgroundColor: colors.onSurface, paddingVertical: 16 },
  saveText: { fontFamily: fonts.display, fontSize: 14, color: colors.onSurfaceInverse, letterSpacing: 1 },
});
