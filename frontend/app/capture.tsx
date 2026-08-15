import React, { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as ImagePicker from "expo-image-picker";
import { Accelerometer } from "expo-sensors";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

import { api } from "@/src/api";
import { Btn } from "@/src/components/ui";
import { useToast } from "@/src/components/toast";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

export default function Capture() {
  const { id, shot } = useLocalSearchParams<{ id: string; shot?: string }>();
  const shotMode = shot === "1";
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const cameraRef = useRef<CameraView>(null);

  const [permission, requestPermission] = useCameraPermissions();
  const [tiltDeg, setTiltDeg] = useState(90);
  const [busy, setBusy] = useState(false);
  const [busyMsg, setBusyMsg] = useState("");

  useEffect(() => {
    let sub: any;
    try {
      Accelerometer.setUpdateInterval(200);
      sub = Accelerometer.addListener(({ x, y, z }) => {
        const norm = Math.sqrt(x * x + y * y + z * z) || 1;
        const t = Math.acos(Math.min(1, Math.abs(z) / norm)) * (180 / Math.PI);
        setTiltDeg(t);
      });
    } catch {}
    return () => sub && sub.remove();
  }, []);

  const level = tiltDeg < 6;

  const handleImage = async (uri: string) => {
    if (!id) return;
    setBusy(true);
    try {
      if (shotMode) {
        setBusyMsg("Caricamento scatto & rilevamento marker...");
        const s = await api.addShot(id, uri);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
        toast(`Scatto aggiunto · ${s.n_markers} bollini`, "success");
        router.back();
        return;
      }
      setBusyMsg("Caricamento foto...");
      await api.uploadPhoto(id, uri);
      setBusyMsg("Rilevamento marker & bordo nastro...");
      const proj = await api.processProject(id);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
      if (proj.quality?.valid) {
        toast(`${proj.quality.markers_found} marker · bordo rilevato`, "success");
      } else {
        toast(proj.quality?.messages?.[0] || "Correggi il contorno nell'editor", "info");
      }
      router.replace(`/editor/${id}` as any);
    } catch (e: any) {
      toast(e.message || "Errore elaborazione", "error");
      setBusy(false);
    }
  };

  const shoot = async () => {
    if (!cameraRef.current) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    try {
      const photo = await cameraRef.current.takePictureAsync({ quality: 0.85 });
      if (photo?.uri) handleImage(photo.uri);
    } catch (e: any) {
      toast("Scatto fallito", "error");
    }
  };

  const pickGallery = async () => {
    const res = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      quality: 0.85,
    });
    if (!res.canceled && res.assets?.[0]?.uri) handleImage(res.assets[0].uri);
  };

  // Permission gates
  if (!permission) {
    return (
      <View style={styles.center}>
        <ActivityIndicator color={colors.brand} />
      </View>
    );
  }

  if (!permission.granted) {
    return (
      <View style={[styles.center, { padding: space.xl }]}>
        <Feather name="camera-off" size={48} color={colors.onSurface} />
        <Text style={styles.permTitle}>ACCESSO CAMERA</Text>
        <Text style={styles.permText}>
          Serve la camera per inquadrare la dima delimitata dal nastro con i 5 bollini di
          riferimento.
        </Text>
        <View style={{ height: space.lg }} />
        {permission.canAskAgain ? (
          <Btn testID="grant-camera" label="CONSENTI CAMERA" onPress={requestPermission} />
        ) : (
          <Btn
            testID="open-settings"
            label="APRI IMPOSTAZIONI"
            variant="dark"
            onPress={() => Linking.openSettings()}
          />
        )}
        <View style={{ height: space.md }} />
        <Btn testID="use-gallery" label="USA GALLERIA" variant="outline" onPress={pickGallery} />
        <View style={{ height: space.md }} />
        <Pressable onPress={() => router.back()} testID="cancel-capture">
          <Text style={styles.link}>ANNULLA</Text>
        </Pressable>
      </View>
    );
  }

  const Target = ({ style }: { style: any }) => (
    <View style={[styles.target, { borderColor: level ? colors.success : "#FFFFFF" }, style]} />
  );

  return (
    <View style={styles.container}>
      <CameraView ref={cameraRef} style={StyleSheet.absoluteFill} facing="back" />

      {/* HUD overlay */}
      <View style={[StyleSheet.absoluteFill, { pointerEvents: "box-none" }]}>
        <Target style={{ top: insets.top + 70, left: 24, borderTopWidth: 4, borderLeftWidth: 4 }} />
        <Target style={{ top: insets.top + 70, right: 24, borderTopWidth: 4, borderRightWidth: 4 }} />
        <Target style={{ bottom: 180, left: 24, borderBottomWidth: 4, borderLeftWidth: 4 }} />
        <Target style={{ bottom: 180, right: 24, borderBottomWidth: 4, borderRightWidth: 4 }} />
        <View style={styles.crossWrap}>
          <View style={[styles.crossDot, { borderColor: level ? colors.success : "#FFF" }]} />
        </View>

        {/* Top telemetry */}
        <View style={[styles.telemetry, { top: insets.top + 8 }]}>
          <Text style={styles.teleText}>INCLINAZIONE {tiltDeg.toFixed(0)}°</Text>
          <View style={[styles.levelPill, { backgroundColor: level ? colors.success : colors.error }]}>
            <Text style={styles.levelText}>{level ? "PIANO ✓" : "RADDRIZZA"}</Text>
          </View>
        </View>

        <Pressable
          testID="capture-back"
          onPress={() => router.back()}
          style={[styles.backChip, { top: insets.top + 8 }]}
          hitSlop={10}
        >
          <Feather name="x" size={22} color="#FFF" />
        </Pressable>
      </View>

      {/* Bottom bar */}
      <View style={[styles.bottomBar, { paddingBottom: insets.bottom + space.md }]}>
        <Pressable testID="gallery-btn" onPress={pickGallery} style={styles.smallBtn}>
          <Feather name="image" size={22} color="#FFF" />
          <Text style={styles.smallBtnText}>GALLERIA</Text>
        </Pressable>
        <Pressable testID="shutter-btn" onPress={shoot} style={styles.shutter}>
          <View style={[styles.shutterInner, { backgroundColor: level ? colors.success : colors.brand }]} />
        </Pressable>
        <View style={styles.smallBtn}>
          <Text style={styles.hint}>4 ANGOLI{"\n"}+1 CENTRO</Text>
        </View>
      </View>

      {busy && (
        <View style={styles.busyOverlay} testID="processing-overlay">
          <ActivityIndicator color={colors.brand} size="large" />
          <Text style={styles.busyText}>{busyMsg}</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#000" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  permTitle: {
    fontFamily: fonts.display,
    fontSize: fontSize.xl,
    color: colors.onSurface,
    marginTop: space.md,
    letterSpacing: 1,
  },
  permText: {
    fontFamily: fonts.mono,
    fontSize: fontSize.base,
    color: colors.onSurfaceSecondary,
    textAlign: "center",
    marginTop: space.sm,
  },
  link: { fontFamily: fonts.monoBold, fontSize: fontSize.base, color: colors.onSurfaceTertiary },
  target: { position: "absolute", width: 64, height: 64 },
  crossWrap: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center", pointerEvents: "none" },
  crossDot: { width: 40, height: 40, borderWidth: 2, borderRadius: 20 },
  telemetry: {
    position: "absolute",
    alignSelf: "center",
    flexDirection: "row",
    alignItems: "center",
    gap: space.sm,
    backgroundColor: "rgba(0,0,0,0.55)",
    paddingHorizontal: space.md,
    paddingVertical: 6,
    pointerEvents: "none",
  },
  teleText: { fontFamily: fonts.monoMed, fontSize: fontSize.sm, color: "#FFF", letterSpacing: 1 },
  levelPill: { paddingHorizontal: space.sm, paddingVertical: 2 },
  levelText: { fontFamily: fonts.monoBold, fontSize: 11, color: "#000" },
  backChip: {
    position: "absolute",
    left: space.md,
    backgroundColor: "rgba(0,0,0,0.55)",
    width: 40,
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  bottomBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingTop: space.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-around",
    backgroundColor: "rgba(10,10,10,0.9)",
    borderTopWidth: BORDER,
    borderTopColor: colors.brand,
  },
  smallBtn: { alignItems: "center", justifyContent: "center", width: 72, gap: 4 },
  smallBtnText: { fontFamily: fonts.monoMed, fontSize: 11, color: "#FFF" },
  hint: { fontFamily: fonts.mono, fontSize: 10, color: "#BBB", textAlign: "center" },
  shutter: {
    width: 76,
    height: 76,
    borderRadius: 38,
    borderWidth: 4,
    borderColor: "#FFF",
    alignItems: "center",
    justifyContent: "center",
  },
  shutterInner: { width: 56, height: 56, borderRadius: 28 },
  busyOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(10,10,10,0.85)",
    alignItems: "center",
    justifyContent: "center",
    gap: space.md,
  },
  busyText: { fontFamily: fonts.monoMed, fontSize: fontSize.base, color: "#FFF" },
});
