import React from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewStyle,
} from "react-native";
import * as Haptics from "expo-haptics";

import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

export function Btn({
  label,
  onPress,
  variant = "primary",
  disabled,
  loading,
  testID,
  icon,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: "primary" | "dark" | "outline";
  disabled?: boolean;
  loading?: boolean;
  testID?: string;
  icon?: React.ReactNode;
  style?: ViewStyle;
}) {
  const bg =
    variant === "primary" ? colors.brand : variant === "dark" ? colors.surfaceInverse : colors.surface;
  const fg =
    variant === "primary" ? colors.onBrand : variant === "dark" ? colors.onSurfaceInverse : colors.onSurface;
  return (
    <Pressable
      testID={testID}
      disabled={disabled || loading}
      onPress={() => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
        onPress();
      }}
      style={({ pressed }) => [
        styles.btn,
        { backgroundColor: bg, opacity: disabled ? 0.4 : pressed ? 0.85 : 1 },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <View style={styles.btnRow}>
          {icon}
          <Text style={[styles.btnLabel, { color: fg }]}>{label}</Text>
        </View>
      )}
    </Pressable>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  testID,
}: {
  options: { label: string; value: T }[];
  value: T;
  onChange: (v: T) => void;
  testID?: string;
}) {
  return (
    <View style={styles.segment} testID={testID}>
      {options.map((o, i) => {
        const active = o.value === value;
        return (
          <Pressable
            key={o.value}
            testID={`${testID}-${o.value}`}
            onPress={() => {
              Haptics.selectionAsync().catch(() => {});
              onChange(o.value);
            }}
            style={[
              styles.segItem,
              i > 0 && { borderLeftWidth: BORDER, borderLeftColor: colors.borderStrong },
              active && { backgroundColor: colors.surfaceInverse },
            ]}
          >
            <Text
              style={[
                styles.segLabel,
                { color: active ? colors.onSurfaceInverse : colors.onSurface },
              ]}
            >
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Field({
  label,
  unit,
  testID,
  ...props
}: TextInputProps & { label: string; unit?: string; testID?: string }) {
  return (
    <View style={{ marginBottom: space.lg }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.fieldWrap}>
        <TextInput
          testID={testID}
          placeholderTextColor={colors.onSurfaceTertiary}
          {...props}
          style={styles.fieldInput}
        />
        {unit ? <Text style={styles.fieldUnit}>{unit}</Text> : null}
      </View>
    </View>
  );
}

export function Tag({ text, color = colors.surfaceInverse }: { text: string; color?: string }) {
  return (
    <View style={[styles.tag, { borderColor: color }]}>
      <Text style={[styles.tagText, { color }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  btn: {
    borderWidth: BORDER,
    borderColor: colors.borderStrong,
    paddingVertical: space.md,
    paddingHorizontal: space.lg,
    alignItems: "center",
    justifyContent: "center",
  },
  btnRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  btnLabel: { fontFamily: fonts.display, fontSize: fontSize.lg, letterSpacing: 0.5 },
  segment: {
    flexDirection: "row",
    borderWidth: BORDER,
    borderColor: colors.borderStrong,
  },
  segItem: { flex: 1, paddingVertical: space.md, alignItems: "center", backgroundColor: colors.surface },
  segLabel: { fontFamily: fonts.monoMed, fontSize: fontSize.base },
  fieldLabel: {
    fontFamily: fonts.monoMed,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
    marginBottom: space.xs,
    letterSpacing: 0.5,
    textTransform: "uppercase",
  },
  fieldWrap: {
    flexDirection: "row",
    alignItems: "center",
    borderWidth: BORDER,
    borderColor: colors.borderStrong,
    backgroundColor: colors.surface,
  },
  fieldInput: {
    flex: 1,
    fontFamily: fonts.mono,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
  },
  fieldUnit: {
    fontFamily: fonts.monoBold,
    fontSize: fontSize.base,
    color: colors.onSurfaceTertiary,
    paddingHorizontal: space.md,
  },
  tag: { borderWidth: BORDER, paddingHorizontal: space.sm, paddingVertical: 2 },
  tagText: { fontFamily: fonts.monoBold, fontSize: 10, letterSpacing: 0.5 },
});
