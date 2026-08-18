import React, { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Line, Path } from "react-native-svg";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import { runOnJS } from "react-native-reanimated";
import { Feather } from "@expo/vector-icons";
import { BORDER, colors, fonts, fontSize, space } from "@/src/theme";

type VB = { x: number; y: number; w: number };
const F = (n: number) => Number.isFinite(n);

/** Zoomable / pannable vector drawing of vectorization polylines (mm, Y-down). */
export function VectorPreview({
  polylines,
  width,
  height,
}: {
  polylines: number[][][];
  width: number;
  height: number;
}) {
  const aspect = height / Math.max(width, 1);

  const bounds = useMemo(() => {
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    polylines.forEach((pl) =>
      pl.forEach(([px, py]) => {
        if (!F(px) || !F(py)) return;
        if (px < minx) minx = px;
        if (py < miny) miny = py;
        if (px > maxx) maxx = px;
        if (py > maxy) maxy = py;
      })
    );
    if (!F(minx)) { minx = 0; miny = 0; maxx = 100; maxy = 100; }
    return { minx, miny, maxx, maxy, w: Math.max(maxx - minx, 1), h: Math.max(maxy - miny, 1) };
  }, [polylines]);

  const fit = useMemo<VB>(() => {
    const pad = Math.max(bounds.w, bounds.h) * 0.1;
    const contentAspect = bounds.h / bounds.w;
    let vw = bounds.w + pad * 2;
    if (contentAspect > aspect) vw = (bounds.h + pad * 2) / Math.max(aspect, 0.001);
    const cx = (bounds.minx + bounds.maxx) / 2;
    const cy = (bounds.miny + bounds.maxy) / 2;
    return { x: cx - vw / 2, y: cy - (vw * aspect) / 2, w: vw };
  }, [bounds, aspect]);

  const [vb, setVb] = useState<VB>(fit);
  useEffect(() => setVb(fit), [fit]);

  const vbStart = useRef(vb);
  const vh = vb.w * aspect;
  const maxW = Math.max(bounds.w, bounds.h) * 12 + 200;
  const minW = Math.max(bounds.w, bounds.h) * 0.02 + 2;

  const pan = Gesture.Pan()
    .minDistance(2)
    .onBegin(() => { vbStart.current = { ...vb }; })
    .onUpdate((e) => {
      const nx = vbStart.current.x - (e.translationX / width) * vbStart.current.w;
      const ny = vbStart.current.y - (e.translationY / height) * (vbStart.current.w * aspect);
      runOnJS(setVb)({ x: nx, y: ny, w: vbStart.current.w });
    });
  const pinch = Gesture.Pinch()
    .onBegin(() => { vbStart.current = { ...vb }; })
    .onUpdate((e) => {
      const cx = vbStart.current.x + vbStart.current.w / 2;
      const cy = vbStart.current.y + (vbStart.current.w * aspect) / 2;
      const nw = Math.min(Math.max(vbStart.current.w / e.scale, minW), maxW);
      runOnJS(setVb)({ x: cx - nw / 2, y: cy - (nw * aspect) / 2, w: nw });
    });
  const composed = Gesture.Simultaneous(pinch, pan);

  const zoom = (f: number) => {
    const cx = vb.x + vb.w / 2, cy = vb.y + vh / 2;
    const nw = Math.min(Math.max(vb.w * f, minW), maxW);
    setVb({ x: cx - nw / 2, y: cy - (nw * aspect) / 2, w: nw });
  };

  // Single evenodd path renders holes (letter counters, emblem cutouts) correctly.
  const pathD = useMemo(() => {
    let d = "";
    polylines.forEach((pl) => {
      const pts = pl.filter(([px, py]) => F(px) && F(py));
      if (pts.length < 2) return;
      d += `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)} `;
      for (let i = 1; i < pts.length; i++) d += `L ${pts[i][0].toFixed(2)} ${pts[i][1].toFixed(2)} `;
      d += "Z ";
    });
    return d.trim();
  }, [polylines]);

  const stroke = Math.max(vb.w * 0.004, 0.2);
  // grid lines every "nice" mm step, aligned to origin
  const gstep = niceStep(vb.w);
  const glines: React.ReactNode[] = [];
  const gx0 = Math.floor(vb.x / gstep) * gstep;
  const gy0 = Math.floor(vb.y / gstep) * gstep;
  for (let gx = gx0; gx <= vb.x + vb.w; gx += gstep) {
    glines.push(
      <Line key={`vx${gx}`} x1={gx} y1={vb.y} x2={gx} y2={vb.y + vh} stroke={colors.border} strokeWidth={stroke * 0.5} />
    );
  }
  for (let gy = gy0; gy <= vb.y + vh; gy += gstep) {
    glines.push(
      <Line key={`vy${gy}`} x1={vb.x} y1={gy} x2={vb.x + vb.w} y2={gy} stroke={colors.border} strokeWidth={stroke * 0.5} />
    );
  }

  return (
    <View style={{ width, height }}>
      <GestureDetector gesture={composed}>
        <Svg width={width} height={height} viewBox={`${vb.x} ${vb.y} ${vb.w} ${vh}`}>
          {glines}
          {pathD ? (
            <Path
              d={pathD}
              fill="rgba(184,74,0,0.10)"
              fillRule="evenodd"
              stroke={colors.brand}
              strokeWidth={stroke}
              strokeLinejoin="round"
            />
          ) : null}
        </Svg>
      </GestureDetector>

      <View style={styles.zoomCol} pointerEvents="box-none">
        <Pressable testID="vp-zoom-in" style={styles.zoomBtn} onPress={() => zoom(0.7)} hitSlop={6}>
          <Feather name="plus" size={18} color={colors.onSurface} />
        </Pressable>
        <Pressable testID="vp-zoom-out" style={styles.zoomBtn} onPress={() => zoom(1.4)} hitSlop={6}>
          <Feather name="minus" size={18} color={colors.onSurface} />
        </Pressable>
        <Pressable testID="vp-zoom-fit" style={styles.zoomBtn} onPress={() => setVb(fit)} hitSlop={6}>
          <Feather name="maximize" size={16} color={colors.onSurface} />
        </Pressable>
      </View>

      <View style={styles.hintWrap} pointerEvents="none">
        <Text style={styles.hint}>PIZZICA / TRASCINA PER ZOOMARE</Text>
      </View>
    </View>
  );
}

function niceStep(range: number): number {
  const target = range / 8;
  const pow = Math.pow(10, Math.floor(Math.log10(target)));
  const base = target / pow;
  const m = base < 1.5 ? 1 : base < 3 ? 2 : base < 7 ? 5 : 10;
  return m * pow;
}

const styles = StyleSheet.create({
  zoomCol: { position: "absolute", right: space.sm, top: space.sm, gap: space.xs },
  zoomBtn: {
    width: 36, height: 36, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface, borderWidth: BORDER, borderColor: colors.borderStrong,
  },
  hintWrap: { position: "absolute", left: space.sm, bottom: space.sm, backgroundColor: "rgba(255,255,255,0.85)", paddingHorizontal: space.sm, paddingVertical: 3 },
  hint: { fontFamily: fonts.monoMed, fontSize: 10, color: colors.onSurfaceSecondary, letterSpacing: 1 },
});
