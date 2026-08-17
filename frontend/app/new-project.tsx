import React, { useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { KeyboardAwareScrollView, KeyboardStickyView } from "react-native-keyboard-controller";
import { Feather } from "@expo/vector-icons";

import { api, BackgroundMode, CaptureMode, CutSide, TapeColor } from "@/src/api";
import { Btn, Field, Segmented } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

export default function NewProject() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const { boat_id, n } = useLocalSearchParams<{ boat_id?: string; n?: string }>();

  const [name, setName] = useState(n ? `Pezzo ${n}` : "Pezzo 1");
  const [bg, setBg] = useState<BackgroundMode>("blue_on_white");
  const [tapeColor, setTapeColor] = useState<TapeColor>("auto");
  const [diameter, setDiameter] = useState("20");
  const [refW, setRefW] = useState("900");
  const [refH, setRefH] = useState("700");
  const [cutSide, setCutSide] = useState<CutSide>("inner");
  const [offset, setOffset] = useState("0");
  const [captureMode, setCaptureMode] = useState<CaptureMode>("single");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    const w = parseFloat(refW);
    const h = parseFloat(refH);
    const d = parseFloat(diameter);
    if (!w || !h || w < 50 || h < 50) {
      toast("Interasse marker non valido (min 50mm)", "error");
      return;
    }
    if (!d || d < 3) {
      toast("Diametro bollino non valido", "error");
      return;
    }
    setSaving(true);
    try {
      const pieceName = name.trim() || (n ? `Pezzo ${n}` : "Pezzo 1");
      const proj = await api.createProject({
        name: pieceName,
        piece_name: pieceName,
        boat_id: boat_id || null,
        background_mode: bg,
        marker_diameter_mm: d,
        ref_width_mm: w,
        ref_height_mm: h,
        cut_side: cutSide,
        blade_offset_mm: parseFloat(offset) || 0,
        capture_mode: captureMode,
        tape_color: tapeColor,
      });
      const dest =
        captureMode === "multi" ? `/shots/${proj.id}`
        : captureMode === "photogram" ? `/photogram/${proj.id}`
        : `/capture?id=${proj.id}`;
      router.replace(dest as any);
    } catch (e: any) {
      toast(e.message || "Errore creazione pezzo", "error");
      setSaving(false);
    }
  };

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <Pressable testID="back-btn" onPress={() => router.back()} hitSlop={12}>
          <Feather name="arrow-left" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>NUOVO PEZZO</Text>
        <View style={{ width: 24 }} />
      </View>

      <KeyboardAwareScrollView
        contentContainerStyle={{ padding: space.lg, paddingBottom: 120 }}
        bottomOffset={90}
        keyboardShouldPersistTaps="handled"
      >
        <Field
          label="Nome pezzo"
          testID="input-name"
          value={name}
          onChangeText={setName}
          placeholder="Es. Plancetta, Pozzetto, Prua"
        />

        <Text style={styles.sectionLabel}>Modalità cattura</Text>
        <Segmented<CaptureMode>
          testID="capture-mode"
          value={captureMode}
          onChange={setCaptureMode}
          options={[
            { label: "SCATTO SINGOLO", value: "single" },
            { label: "MULTI-SCATTO", value: "multi" },
            { label: "FOTO + RIFERIMENTO", value: "photogram" },
          ]}
        />
        {captureMode === "multi" && (
          <View style={[styles.infoBox, { marginTop: space.md, marginBottom: 0 }]}>
            <Feather name="layers" size={14} color={colors.brand} />
            <Text style={styles.infoText}>
              Per aree fino a 2×3 m: scatta più foto sovrapposte, ognuna condividendo almeno 4
              bollini con la precedente. L'interasse qui sotto è quello dei 4 bollini del primo scatto.
            </Text>
          </View>
        )}
        {captureMode === "photogram" && (
          <View style={[styles.infoBox, { marginTop: space.md, marginBottom: 0 }]}>
            <Feather name="aperture" size={14} color={colors.brand} />
            <Text style={styles.infoText}>
              Consigliato per tappeti delimitati dal NASTRO. Scatta una foto dall'alto del pezzo,
              poi tocca i 4 punti d'angolo di riferimento (i puntini/angoli con interasse noto) e
              inserisci le misure reali: raddrizzo la prospettiva e ricavo il contorno seguendo il
              nastro. Per pezzi molto grandi puoi anche usare più foto con marker ArUco.
            </Text>
          </View>
        )}
        <View style={{ height: space.xl }} />

        <Text style={styles.sectionLabel}>Modalità sfondo / nastro</Text>
        <Segmented<BackgroundMode>
          testID="bg-mode"
          value={bg}
          onChange={setBg}
          options={[
            { label: "BLU SU BIANCO", value: "blue_on_white" },
            { label: "BIANCO SU SCURO", value: "white_on_dark" },
          ]}
        />
        <View style={{ height: space.lg }} />

        <Text style={styles.sectionLabel}>Colore nastro</Text>
        <View style={styles.chipsWrap}>
          {([
            ["auto", "AUTO"],
            ["blu", "AZZURRO"],
            ["giallo", "GIALLO"],
            ["verde", "VERDE"],
            ["rosso", "ROSSO"],
            ["bianco", "BIANCO"],
          ] as const).map(([v, l]) => (
            <Pressable
              key={v}
              testID={`tape-${v}`}
              onPress={() => setTapeColor(v)}
              style={[styles.chip, tapeColor === v && styles.chipOn]}
            >
              <Text style={[styles.chipText, tapeColor === v && styles.chipTextOn]}>{l}</Text>
            </Pressable>
          ))}
        </View>
        <View style={styles.infoBox}>
          <Feather name="droplet" size={14} color={colors.brand} />
          <Text style={styles.infoText}>
            AUTO rileva da solo il colore del nastro che delimita il tappeto. Scegli un colore
            specifico se la foto ha altri oggetti dello stesso colore che confondono il rilevamento.
          </Text>
        </View>
        <View style={{ height: space.md }} />

        <Field
          label="Diametro bollini"
          testID="input-diameter"
          value={diameter}
          onChangeText={setDiameter}
          keyboardType="decimal-pad"
          unit="mm"
        />

        <View style={styles.infoBox}>
          <Feather name="info" size={14} color={colors.brand} />
          <Text style={styles.infoText}>
            Interasse noto tra i bollini d'angolo = scala precisa. Misura la distanza reale
            centro-centro tra gli angoli.
          </Text>
        </View>

        <View style={styles.row}>
          <View style={{ flex: 1 }}>
            <Field
              label="Interasse largh."
              testID="input-ref-w"
              value={refW}
              onChangeText={setRefW}
              keyboardType="decimal-pad"
              unit="mm"
            />
          </View>
          <View style={{ width: space.md }} />
          <View style={{ flex: 1 }}>
            <Field
              label="Interasse alt."
              testID="input-ref-h"
              value={refH}
              onChangeText={setRefH}
              keyboardType="decimal-pad"
              unit="mm"
            />
          </View>
        </View>

        <Text style={styles.sectionLabel}>Taglio sul bordo nastro</Text>
        <Segmented<CutSide>
          testID="cut-side"
          value={cutSide}
          onChange={setCutSide}
          options={[
            { label: "BORDO INTERNO", value: "inner" },
            { label: "BORDO ESTERNO", value: "outer" },
          ]}
        />
        <View style={{ height: space.xl }} />

        <Field
          label="Offset lama (gioco)"
          testID="input-offset"
          value={offset}
          onChangeText={setOffset}
          keyboardType="decimal-pad"
          unit="mm"
        />
      </KeyboardAwareScrollView>

      <KeyboardStickyView>
        <View style={[styles.footer, { paddingBottom: insets.bottom + space.md }]}>
          <Btn
            testID="start-camera-btn"
            label={captureMode === "multi" ? "GESTISCI SCATTI" : "AVVIA CAMERA"}
            loading={saving}
            icon={<Feather name={captureMode === "multi" ? "layers" : "camera"} size={20} color={colors.onBrand} />}
            onPress={submit}
          />
        </View>
      </KeyboardStickyView>
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
    paddingVertical: space.md,
    borderBottomWidth: BORDER,
    borderBottomColor: colors.borderStrong,
  },
  title: { fontFamily: fonts.display, fontSize: fontSize.xl, color: colors.onSurface, letterSpacing: 1 },
  sectionLabel: {
    fontFamily: fonts.monoMed,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
    marginBottom: space.xs,
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  row: { flexDirection: "row" },
  chipsWrap: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: {
    borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface,
    paddingHorizontal: space.md, paddingVertical: 8,
  },
  chipOn: { backgroundColor: colors.surfaceInverse },
  chipText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface, letterSpacing: 0.5 },
  chipTextOn: { color: colors.onSurfaceInverse },
  infoBox: {
    flexDirection: "row",
    gap: space.sm,
    backgroundColor: colors.brandTertiary,
    borderWidth: BORDER,
    borderColor: colors.brand,
    padding: space.md,
    marginBottom: space.lg,
  },
  infoText: { flex: 1, fontFamily: fonts.mono, fontSize: fontSize.sm, color: colors.onSurface },
  footer: {
    padding: space.lg,
    borderTopWidth: BORDER,
    borderTopColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
});
