import { Platform } from "react-native";

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL as string;
const API = `${BACKEND}/api`;

export const absUrl = (u?: string | null): string | undefined =>
  u ? `${BACKEND}${u}` : undefined;

async function req(path: string, options: RequestInit = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch {}
    throw new Error(detail);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

export type BackgroundMode = "blue_on_white" | "white_on_dark";
export type TapeColor = "auto" | "blu" | "giallo" | "verde" | "rosso" | "bianco";
export type CutSide = "inner" | "outer";
export type Layer = "CUT" | "ENGRAVE";
export type CaptureMode = "single" | "multi" | "photogram";

export interface PgPhotoT {
  id: string;
  order: number;
  photo_path: string;
  photo_url?: string | null;
}

export interface PgStitchResult {
  mosaic_url: string;
  w: number;
  h: number;
  warning?: string | null;
}

export interface ShotT {
  id: string;
  order: number;
  photo_path: string;
  photo_url?: string | null;
  n_markers: number;
  anchored: boolean;
}

export interface StitchResult {
  anchored: string[];
  unanchored: string[];
  tape_detected: boolean;
  n_global_markers: number;
  plane_w_mm: number;
  plane_h_mm: number;
  rectified_url?: string | null;
  contour_points: number;
}

export interface ElementT {
  id: string;
  type: string;
  layer: Layer;
  polylines: number[][][];
  params?: Record<string, any>;
}

export interface ProjectT {
  id: string;
  name: string;
  boat_id?: string | null;
  piece_name?: string;
  status: string;
  created_at: string;
  updated_at: string;
  background_mode: BackgroundMode;
  tape_color?: TapeColor;
  marker_diameter_mm: number;
  ref_width_mm: number;
  ref_height_mm: number;
  cut_side: CutSide;
  blade_offset_mm: number;
  fillet_radius_mm: number;
  capture_mode: CaptureMode;
  shots: ShotT[];
  photo_path?: string | null;
  rectified_path?: string | null;
  rectified_url?: string | null;
  photo_url?: string | null;
  dxf_url?: string | null;
  rectified_w_px: number;
  rectified_h_px: number;
  mm_per_px: number;
  markers: any[];
  quality: {
    markers_found: number;
    markers_required: number;
    sharpness: number;
    tape_detected: boolean;
    valid: boolean;
    messages: string[];
  };
  contour_mm: number[][];
  elements: ElementT[];
  eva_color?: string;
  groove_color?: string;
  layout_x?: number;
  layout_y?: number;
  layout_rot?: number;
}

export interface BoatT {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  piece_count?: number;
  thumb_url?: string | null;
  pieces?: ProjectT[];
}

export const api = {
  // Boats (a boat groups one or more mat pieces)
  listBoats: (): Promise<BoatT[]> => req("/boats"),
  getBoat: (id: string): Promise<BoatT> => req(`/boats/${id}`),
  createBoat: (body: { name: string }): Promise<BoatT> =>
    req("/boats", { method: "POST", body: JSON.stringify(body) }),
  updateBoat: (id: string, body: any): Promise<BoatT> =>
    req(`/boats/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteBoat: (id: string) => req(`/boats/${id}`, { method: "DELETE" }),
  boatAssembly: (id: string): Promise<{ sheet_url: string; size: number; count: number; overflow: boolean; total_area_m2: number }> =>
    req(`/boats/${id}/assembly`),
  boatNestedDxf: (id: string): Promise<{ dxf_url: string; size: number; count: number; overflow: boolean }> =>
    req(`/boats/${id}/nested-dxf`, { method: "POST" }),
  exportBoatFormat: (id: string, fmt: string, body: any = {}): Promise<{ url: string; size: number; format: string; ext: string; count: number; overflow: boolean }> =>
    req(`/boats/${id}/export/${fmt}`, { method: "POST", body: JSON.stringify(body) }),

  listProjects: (boatId?: string): Promise<ProjectT[]> =>
    req(`/projects${boatId ? `?boat_id=${boatId}` : ""}`),
  getProject: (id: string): Promise<ProjectT> => req(`/projects/${id}`),
  createProject: (body: any): Promise<ProjectT> =>
    req("/projects", { method: "POST", body: JSON.stringify(body) }),
  boatRenderUrl: (id: string, fmt: "png" | "pdf" = "png") => `${API}/boats/${id}/render.${fmt}`,
  updateProject: (id: string, body: any): Promise<ProjectT> =>
    req(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProject: (id: string) => req(`/projects/${id}`, { method: "DELETE" }),
  processProject: (id: string): Promise<ProjectT> =>
    req(`/projects/${id}/process`, { method: "POST" }),
  preview: (id: string): Promise<any> => req(`/projects/${id}/preview`),
  exportDxf: (id: string): Promise<{ dxf_url: string; size: number }> =>
    req(`/projects/${id}/export`, { method: "POST" }),
  exportFormat: (id: string, fmt: string, body: any = {}): Promise<{ url: string; size: number; format: string; ext: string }> =>
    req(`/projects/${id}/export/${fmt}`, { method: "POST", body: JSON.stringify(body) }),
  techsheet: (id: string, body: any): Promise<{ sheet_url: string; size: number; area_m2: number }> =>
    req(`/projects/${id}/techsheet`, { method: "POST", body: JSON.stringify(body) }),
  patterns: (): Promise<any[]> => req("/patterns"),
  geoText: (body: any): Promise<{ polylines: number[][][] }> =>
    req("/geometry/text", { method: "POST", body: JSON.stringify(body) }),
  geoSvg: (body: any): Promise<{ polylines: number[][][] }> =>
    req("/geometry/svg", { method: "POST", body: JSON.stringify(body) }),
  geoTrack: (body: any): Promise<{ polylines: number[][][] }> =>
    req("/geometry/track", { method: "POST", body: JSON.stringify(body) }),
  geoFill: (body: any): Promise<{ polylines: number[][][]; border_count: number; line_count: number }> =>
    req("/geometry/fill", { method: "POST", body: JSON.stringify(body) }),

  // Multi-shot
  listShots: (id: string): Promise<ShotT[]> => req(`/projects/${id}/shots`),
  deleteShot: (id: string, shotId: string) =>
    req(`/projects/${id}/shots/${shotId}`, { method: "DELETE" }),
  stitch: (id: string): Promise<StitchResult> =>
    req(`/projects/${id}/stitch`, { method: "POST" }),

  // Photogrammetry (markerless, flat pieces)
  listPgPhotos: (id: string): Promise<PgPhotoT[]> =>
    req(`/projects/${id}/photogram/photos`),
  deletePgPhoto: (id: string, photoId: string) =>
    req(`/projects/${id}/photogram/photos/${photoId}`, { method: "DELETE" }),
  pgStitch: (id: string): Promise<PgStitchResult> =>
    req(`/projects/${id}/photogram/stitch`, { method: "POST" }),
  pgExtract: (id: string, reference: any): Promise<ProjectT & { detected?: boolean }> =>
    req(`/projects/${id}/photogram/extract`, { method: "POST", body: JSON.stringify(reference) }),
  pgAruco: (id: string, markerMm: number): Promise<ProjectT & { detected?: boolean; photos_used?: number; markers_found?: number }> =>
    req(`/projects/${id}/photogram/aruco`, { method: "POST", body: JSON.stringify({ marker_mm: markerMm }) }),
  arucoSheetUrl: (mm: number = 40) => `${API}/aruco/sheet.pdf?mm=${mm}`,

  async addPgPhoto(projectId: string, uri: string): Promise<PgPhotoT> {
    const form = new FormData();
    const name = `pg_${Date.now()}.jpg`;
    if (Platform.OS === "web") {
      const blob = await (await fetch(uri)).blob();
      form.append("file", blob, name);
    } else {
      // @ts-ignore native multipart shape
      form.append("file", { uri, name, type: "image/jpeg" });
    }
    const res = await fetch(`${API}/projects/${projectId}/photogram/photos`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Upload foto fallito (${res.status})`);
    return res.json();
  },

  async addShot(projectId: string, uri: string): Promise<ShotT> {    const form = new FormData();
    const name = `shot_${Date.now()}.jpg`;
    if (Platform.OS === "web") {
      const blob = await (await fetch(uri)).blob();
      form.append("file", blob, name);
    } else {
      // @ts-ignore native multipart shape
      form.append("file", { uri, name, type: "image/jpeg" });
    }
    const res = await fetch(`${API}/projects/${projectId}/shots`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Upload scatto fallito (${res.status})`);
    return res.json();
  },

  async uploadPhoto(projectId: string, uri: string) {
    const form = new FormData();
    const name = `photo_${Date.now()}.jpg`;
    if (Platform.OS === "web") {
      const blob = await (await fetch(uri)).blob();
      form.append("file", blob, name);
    } else {
      // @ts-ignore native multipart shape
      form.append("file", { uri, name, type: "image/jpeg" });
    }
    const res = await fetch(`${API}/projects/${projectId}/photo`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) throw new Error(`Upload fallito (${res.status})`);
    return res.json();
  },

  addElement: (projectId: string, element: any): Promise<ProjectT> =>
    req(`/projects/${projectId}/elements`, { method: "POST", body: JSON.stringify(element) }),

  async vectorize(
    uri: string,
    opts: { threshold?: number; invert?: boolean; target_width_mm?: number; simplify?: number; subject?: string; internals?: boolean; roi?: { x: number; y: number; w: number; h: number } | null; clean?: boolean } = {}
  ): Promise<{ polylines: number[][][]; width_mm: number; height_mm: number; count: number; preview_url: string | null; dxf_url: string }> {
    const form = new FormData();
    const name = `vec_${Date.now()}.jpg`;
    if (Platform.OS === "web") {
      const blob = await (await fetch(uri)).blob();
      form.append("file", blob, name);
    } else {
      // @ts-ignore native multipart shape
      form.append("file", { uri, name, type: "image/jpeg" });
    }
    form.append("threshold", String(opts.threshold ?? -1));
    form.append("invert", String(opts.invert ?? true));
    form.append("target_width_mm", String(opts.target_width_mm ?? 200));
    form.append("simplify", String(opts.simplify ?? 0.005));
    form.append("subject", String(opts.subject ?? "logo"));
    form.append("internals", String(opts.internals ?? false));
    if (opts.roi) form.append("roi", JSON.stringify(opts.roi));
    form.append("clean", String(opts.clean ?? false));
    const res = await fetch(`${API}/vectorize`, { method: "POST", body: form });
    if (!res.ok) {
      let d = `Vettorizzazione fallita (${res.status})`;
      try { d = (await res.json()).detail || d; } catch {}
      throw new Error(d);
    }
    return res.json();
  },
};
