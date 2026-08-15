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
export type CutSide = "inner" | "outer";
export type Layer = "CUT" | "ENGRAVE";

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
  status: string;
  created_at: string;
  updated_at: string;
  background_mode: BackgroundMode;
  marker_diameter_mm: number;
  ref_width_mm: number;
  ref_height_mm: number;
  cut_side: CutSide;
  blade_offset_mm: number;
  fillet_radius_mm: number;
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
}

export const api = {
  listProjects: (): Promise<ProjectT[]> => req("/projects"),
  getProject: (id: string): Promise<ProjectT> => req(`/projects/${id}`),
  createProject: (body: any): Promise<ProjectT> =>
    req("/projects", { method: "POST", body: JSON.stringify(body) }),
  updateProject: (id: string, body: any): Promise<ProjectT> =>
    req(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteProject: (id: string) => req(`/projects/${id}`, { method: "DELETE" }),
  processProject: (id: string): Promise<ProjectT> =>
    req(`/projects/${id}/process`, { method: "POST" }),
  preview: (id: string): Promise<any> => req(`/projects/${id}/preview`),
  exportDxf: (id: string): Promise<{ dxf_url: string; size: number }> =>
    req(`/projects/${id}/export`, { method: "POST" }),
  patterns: (): Promise<any[]> => req("/patterns"),
  geoText: (body: any): Promise<{ polylines: number[][][] }> =>
    req("/geometry/text", { method: "POST", body: JSON.stringify(body) }),
  geoSvg: (body: any): Promise<{ polylines: number[][][] }> =>
    req("/geometry/svg", { method: "POST", body: JSON.stringify(body) }),
  geoTrack: (body: any): Promise<{ polylines: number[][][] }> =>
    req("/geometry/track", { method: "POST", body: JSON.stringify(body) }),

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
};
