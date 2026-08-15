import React, { useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { Feather } from "@expo/vector-icons";

import { useMachine } from "@/src/machine";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

export type ExportFmt = "dxf" | "svg" | "pdf" | "png" | "gcode";

const FORMATS_CNC: { fmt: ExportFmt; label: string }[] = [
  { fmt: "dxf", label: "DXF" },
  { fmt: "svg", label: "SVG" },
  { fmt: "pdf", label: "PDF" },
  { fmt: "png", label: "PNG" },
  { fmt: "gcode", label: "G-CODE" },
];
const FORMATS_LASER: { fmt: ExportFmt; label: string }[] = [
  { fmt: "dxf", label: "DXF" },
  { fmt: "svg", label: "SVG" },
];

const DEF = {
  flavor: "grbl" as "grbl" | "mach3",
  tool_diameter_mm: "3",
  cut_depth_mm: "3",
  step_down_mm: "1.5",
  feed_xy: "1000",
  feed_z: "300",
  safe_z_mm: "5",
  spindle_speed: "12000",
  include_engrave: true,
  engrave_depth_mm: "1",
};

function NumField({ label, value, onChange }: any) {
  return (
    <View style={styles.numField}>
      <Text style={styles.numLabel}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChange}
        keyboardType="decimal-pad"
        style={styles.numInput}
        placeholderTextColor={colors.onSurfaceTertiary}
      />
    </View>
  );
}

/**
 * Format picker + G-code params. Calls onExport(fmt, body) where body carries
 * { gcode: {...} } when the G-code format is selected.
 */
export function ExportFormatBar({
  title,
  busy,
  onExport,
}: {
  title?: string;
  busy?: boolean;
  onExport: (fmt: ExportFmt, body: any) => void;
}) {
  const [fmt, setFmt] = useState<ExportFmt>("dxf");
  const [g, setG] = useState(DEF);
  const { machine } = useMachine();
  const laser = machine === "laser";
  const FORMATS = laser ? FORMATS_LASER : FORMATS_CNC;

  useEffect(() => {
    if (!FORMATS.some((f) => f.fmt === fmt)) setFmt("dxf");
  }, [laser]);

  const set = (k: keyof typeof DEF) => (v: any) => setG((s) => ({ ...s, [k]: v }));

  const doExport = () => {
    const body: any =
      fmt === "gcode"
        ? {
            gcode: {
              flavor: g.flavor,
              tool_diameter_mm: parseFloat(g.tool_diameter_mm) || 3,
              cut_depth_mm: parseFloat(g.cut_depth_mm) || 3,
              step_down_mm: parseFloat(g.step_down_mm) || 1.5,
              feed_xy: parseFloat(g.feed_xy) || 1000,
              feed_z: parseFloat(g.feed_z) || 300,
              safe_z_mm: parseFloat(g.safe_z_mm) || 5,
              spindle_speed: parseInt(g.spindle_speed) || 12000,
              include_engrave: g.include_engrave,
              engrave_depth_mm: parseFloat(g.engrave_depth_mm) || 1,
            },
          }
        : {};
    if (laser) body.cut_only = true; // laser cuts outlines only
    onExport(fmt, body);
  };

  return (
    <View>
      {title ? <Text style={styles.sectionLabel}>{title}</Text> : null}
      <View style={styles.chipRow}>
        {FORMATS.map((f) => (
          <Pressable
            key={f.fmt}
            testID={`fmt-${f.fmt}`}
            onPress={() => setFmt(f.fmt)}
            style={[styles.chip, fmt === f.fmt && styles.chipOn]}
          >
            <Text style={[styles.chipText, fmt === f.fmt && styles.chipTextOn]}>{f.label}</Text>
          </Pressable>
        ))}
      </View>

      {fmt === "gcode" && (
        <View style={styles.gBox}>
          <View style={styles.chipRow}>
            {(["grbl", "mach3"] as const).map((fl) => (
              <Pressable
                key={fl}
                testID={`flavor-${fl}`}
                onPress={() => set("flavor")(fl)}
                style={[styles.chip, g.flavor === fl && styles.chipOn]}
              >
                <Text style={[styles.chipText, g.flavor === fl && styles.chipTextOn]}>
                  {fl.toUpperCase()}
                </Text>
              </Pressable>
            ))}
            <Pressable
              testID="gcode-engrave-toggle"
              onPress={() => set("include_engrave")(!g.include_engrave)}
              style={[styles.chip, g.include_engrave && styles.chipOn]}
            >
              <Feather
                name={g.include_engrave ? "check" : "x"}
                size={13}
                color={g.include_engrave ? colors.onSurfaceInverse : colors.onSurface}
              />
              <Text style={[styles.chipText, g.include_engrave && styles.chipTextOn, { marginLeft: 4 }]}>
                INCISIONE
              </Text>
            </Pressable>
          </View>
          <View style={styles.grid}>
            <NumField label="Fresa Ø (mm)" value={g.tool_diameter_mm} onChange={set("tool_diameter_mm")} />
            <NumField label="Prof. taglio (mm)" value={g.cut_depth_mm} onChange={set("cut_depth_mm")} />
            <NumField label="Passata (mm)" value={g.step_down_mm} onChange={set("step_down_mm")} />
            <NumField label="Vel. XY (mm/min)" value={g.feed_xy} onChange={set("feed_xy")} />
            <NumField label="Vel. Z (mm/min)" value={g.feed_z} onChange={set("feed_z")} />
            <NumField label="Z sicurezza (mm)" value={g.safe_z_mm} onChange={set("safe_z_mm")} />
            <NumField label="Giri mandrino" value={g.spindle_speed} onChange={set("spindle_speed")} />
            {g.include_engrave ? (
              <NumField label="Prof. incisione (mm)" value={g.engrave_depth_mm} onChange={set("engrave_depth_mm")} />
            ) : null}
          </View>
        </View>
      )}

      <Pressable testID="export-run" style={styles.exportBtn} onPress={doExport} disabled={busy}>
        {busy ? (
          <ActivityIndicator size="small" color={colors.onBrand} />
        ) : (
          <>
            <Feather name="download" size={18} color={colors.onBrand} />
            <Text style={styles.exportBtnText}>ESPORTA {fmt.toUpperCase()}</Text>
          </>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  sectionLabel: {
    fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurfaceSecondary,
    marginBottom: space.sm, letterSpacing: 0.5, textTransform: "uppercase",
  },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: space.sm, marginBottom: space.sm },
  chip: {
    flexDirection: "row", alignItems: "center",
    borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface,
    paddingHorizontal: space.md, paddingVertical: 8,
  },
  chipOn: { backgroundColor: colors.surfaceInverse },
  chipText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: colors.onSurface },
  chipTextOn: { color: colors.onSurfaceInverse },
  gBox: {
    borderWidth: BORDER, borderColor: colors.border, padding: space.md, marginBottom: space.sm,
    backgroundColor: colors.surfaceSecondary,
  },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  numField: { width: "48%" },
  numLabel: { fontFamily: fonts.mono, fontSize: 11, color: colors.onSurfaceSecondary, marginBottom: 2 },
  numInput: {
    borderWidth: BORDER, borderColor: colors.borderStrong, backgroundColor: colors.surface,
    paddingHorizontal: space.sm, paddingVertical: 8, fontFamily: fonts.mono,
    fontSize: fontSize.sm, color: colors.onSurface,
  },
  exportBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: space.sm,
    backgroundColor: colors.brand, paddingVertical: 14, marginTop: space.xs,
  },
  exportBtnText: {
    fontFamily: fonts.monoMed, fontSize: fontSize.base, color: colors.onBrand,
    letterSpacing: 0.5, textTransform: "uppercase",
  },
});
