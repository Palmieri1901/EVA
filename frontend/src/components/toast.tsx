import React, { createContext, useCallback, useContext, useRef, useState } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";

import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

type ToastType = "info" | "success" | "error";
const ToastCtx = createContext<(msg: string, type?: ToastType) => void>(() => {});

export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [msg, setMsg] = useState<string | null>(null);
  const [type, setType] = useState<ToastType>("info");
  const opacity = useRef(new Animated.Value(0)).current;
  const timer = useRef<any>(null);

  const show = useCallback(
    (m: string, t: ToastType = "info") => {
      setMsg(m);
      setType(t);
      if (timer.current) clearTimeout(timer.current);
      Animated.timing(opacity, { toValue: 1, duration: 180, useNativeDriver: true }).start();
      timer.current = setTimeout(() => {
        Animated.timing(opacity, { toValue: 0, duration: 220, useNativeDriver: true }).start(() =>
          setMsg(null)
        );
      }, 2600);
    },
    [opacity]
  );

  const bg =
    type === "success" ? colors.success : type === "error" ? colors.error : colors.surfaceInverse;

  return (
    <ToastCtx.Provider value={show}>
      {children}
      {msg && (
        <Animated.View
          testID="toast"
          style={[styles.toast, { opacity, backgroundColor: bg, pointerEvents: "none" }]}
        >
          <Text style={styles.toastText}>{msg}</Text>
        </Animated.View>
      )}
    </ToastCtx.Provider>
  );
}

const styles = StyleSheet.create({
  toast: {
    position: "absolute",
    bottom: 48,
    left: space.lg,
    right: space.lg,
    borderWidth: BORDER,
    borderColor: colors.borderStrong,
    paddingVertical: space.md,
    paddingHorizontal: space.lg,
    zIndex: 9999,
  },
  toastText: { color: "#FFF", fontFamily: fonts.monoMed, fontSize: fontSize.base },
});
