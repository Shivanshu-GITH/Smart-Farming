import { supabase } from "@/lib/supabase";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Geometry = { type: "Polygon"; coordinates: number[][][] };

/** The current Supabase access token (the backend verifies it). Empty headers
 *  when signed out, so the API answers with a 401 the caller can handle. */
async function authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function post<T>(path: string, body: unknown, auth = false): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(auth ? await authHeaders() : {}) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function get<T>(path: string, auth = false): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: auth ? await authHeaders() : {},
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export interface FieldSummary {
  area: { square_meters: number; hectares: number; acres: number; guntha: number };
  perimeter_meters: number;
  centroid: { lat: number; lon: number };
  bbox: number[];
  region: {
    display_name?: string; village?: string; district?: string;
    state?: string; country?: string;
  };
}

export interface Recommendation {
  crop_id: string; name: string; layer: string; category: string;
  score: number; suitability: string; reasons: string[];
  // calibrated recommender only
  level?: "high" | "ok" | "low" | "none";
  calibrated?: boolean;          // false: expert ranges, not in the crop statistics
  needs_irrigation?: boolean;    // local rainfall is below its rain-fed requirement
}

export interface LayoutResult {
  total_plants: number;
  rendered_points?: number;
  system?: string;
  truncated: boolean;
  crops: { crop_id: string; name: string; layer: string; plant_count: number;
           rendered_points?: number;
           count_method?: "layout" | "layout-scaled" | "geometric-estimate" | "area-estimate" }[];
  row_orientation_deg?: number;
  planting_points: { type: "FeatureCollection"; features: any[] };
  heatmap: { grid: number; max_count: number; cells: any[] };
}

export interface ValidationResult {
  compatible: boolean;
  conflicts: { crops: string[]; message: string }[];
  warnings: { type: string; layer?: string; message: string }[];
  synergies: { crops: string[]; message: string }[];
  common_seasons: string[];
  fillers?: Record<string, {
    crop_id: string; name: string; combo_score: number;
    companion_with: string[]; suitability: string;
  }[]>;
}

export interface DesignStack {
  crop_ids: string[];
  filled_layers: number;
  total_score: number;
  layers: {
    layer: string; crop_id: string; name: string;
    suitability: string; companions_in_stack: string[];
  }[];
}
export interface DesignResult {
  season?: string | null; count: number; stacks: DesignStack[];
}

export interface PlantingMaterial {
  type: "seed" | "seedling" | "sucker" | "rhizome" | "sett" | "tuber";
  label: string;
  unit: "kg" | "plants";
  quantity: number;
  note?: string | null;
}

export interface PlanResult {
  crop: { id: string; name: string; layer: string };
  plants: { total_estimate: number; per_hectare: number };
  planting_material?: PlantingMaterial;
  planting_area_hectares?: number;
  usable_fraction?: number;
  seed: { quantity_kg: number };
  fertilizer: { total_kg: Record<string, number> };
  calendar: { stage: string; day: number; date: string }[];
  best_practices: string[];
}

export interface ChatMessage { role: "user" | "assistant"; content: string; }

export interface LayerMeta { order: number; label: string; height_m: [number, number]; }

export interface CatalogueCrop {
  id: string; name: string; common_names: string[]; category: string;
  layer: string; seasons: string[]; systems: string[];
  spacing_cm: { row: number; plant: number };
  duration_days: number; notes?: string;
}

export interface FarmingSystem {
  id: string; name: string; crops_min: number; crops_max: number;
  description: string; best_for: string;
}

export interface GeoResult {
  display_name: string; lat: number; lon: number; type?: string;
  bbox?: [number, number, number, number] | null; // [south, north, west, east]
}

export interface GeoVillage { name: string; lat: number; lon: number; kind?: string }

export interface SchemeResource {
  id: string; name: string; category: string; audience: string;
  description: string; url: string;
}

export interface EconCrop {
  crop_id: string; name: string; layer: string;
  cost: { seed: number; inputs: number; labour: number; total: number };
  revenue: [number, number]; margin: [number, number];
  price_per_kg: number; price_source: string;
}
export interface EconomicsResult {
  area_hectares: number;
  planting_area_hectares?: number;
  usable_fraction?: number;
  currency: string;
  crops: EconCrop[];
  totals: { cost: number; revenue: [number, number]; margin: [number, number] };
  layers: number; disclaimer: string;
}

export interface User {
  id: string; phone?: string | null; email?: string | null; name?: string | null;
}

export interface SavedField {
  id: string;
  name: string;
  geometry: Geometry;
  area?: FieldSummary["area"] | null;
  region?: FieldSummary["region"] | null;
  created_at: string;
}

export const api = {
  fieldSummary: (geometry: Geometry) =>
    post<FieldSummary>("/fields/summary", { geometry }),

  landReport: (lat: number, lon: number) =>
    get<any>(`/land-intel/report?lat=${lat}&lon=${lon}`),

  recommend: (q: Record<string, unknown>) =>
    post<{ count: number; recommendations: Recommendation[] }>(
      "/agronomy/recommend", q),

  layout: (geometry: Geometry, crop_ids: string[], system = "multilayer") =>
    post<LayoutResult>("/layout", { geometry, crop_ids, system }),

  crops: () =>
    get<{ layers: Record<string, LayerMeta>; crops: CatalogueCrop[] }>("/agronomy/crops"),

  systems: () => get<{ systems: FarmingSystem[] }>("/agronomy/systems"),

  geoSearch: (q: string, scope?: { state?: string; district?: string }) => {
    const p = new URLSearchParams({ q });
    if (scope?.state) p.set("state", scope.state);
    if (scope?.district) p.set("district", scope.district);
    return get<{ results: GeoResult[] }>(`/geo/search?${p.toString()}`);
  },

  geoStates: () => get<{ states: string[] }>("/geo/states"),

  geoDistricts: (state: string) =>
    get<{ districts: string[] }>(`/geo/districts?state=${encodeURIComponent(state)}`),

  geoVillages: (state: string, district: string) => {
    const p = new URLSearchParams({ state, district });
    return get<{ district: string; count?: number; villages: GeoVillage[]; error?: string }>(
      `/geo/villages?${p.toString()}`);
  },

  ndvi: (geometry: Geometry) =>
    post<{
      configured: boolean; mean?: number | null; vigour?: string | null;
      date?: string; note?: string; error?: string;
    }>("/land-intel/ndvi", { geometry }),

  validate: (crop_ids: string[], ctx: Record<string, unknown> = {}) =>
    post<ValidationResult>("/agronomy/validate", { crop_ids, ...ctx }),

  design: (ctx: Record<string, unknown>) =>
    post<DesignResult>("/agronomy/design", ctx),

  plan: (crop_id: string, area_m2: number, system?: string,
         geo?: { plant_count?: number; perimeter_m?: number }) =>
    post<PlanResult>("/agronomy/plan", { crop_id, area_m2, system, ...geo }),

  advisoryStatus: () => get<{ configured: boolean }>("/advisory/status"),

  /** `language` is the UI locale — the reply language when the message's is unclear. */
  advisoryChat: (messages: ChatMessage[], context: unknown, language?: string) =>
    post<{ reply: string }>("/advisory/chat", { messages, context, language }),

  economics: (crop_ids: string[], area_m2: number, state?: string, system?: string) =>
    post<EconomicsResult>("/economics/estimate", { crop_ids, area_m2, state, system }),

  diagnose: (image_base64: string, media_type: string, note?: string, context?: unknown) =>
    post<{ reply: string }>("/advisory/diagnose", { image_base64, media_type, note, context }),

  ndviSeries: (geometry: Geometry, months = 6) =>
    post<{ configured: boolean; series: { date: string; mean: number }[]; trend?: string }>(
      "/land-intel/ndvi-series", { geometry, months }),

  schemes: (state?: string) =>
    get<{ count: number; resources: SchemeResource[] }>(
      `/resources/schemes${state ? `?state=${encodeURIComponent(state)}` : ""}`),

  elevation: (lat: number, lon: number) =>
    get<{ elevation_m?: number; slope_pct?: number; slope_class?: string; aspect?: string; error?: string }>(
      `/land-intel/elevation?lat=${lat}&lon=${lon}`),

  savePlan: (fieldId: string, name: string | null, data: unknown) =>
    post<{ id: string }>(`/fields/${fieldId}/plans`, { name, data }, true),

  saveLayout: (fieldId: string, data: unknown) =>
    post<{ id: string }>(`/fields/${fieldId}/layouts`, { data }, true),

  reportPdf: async (geometry: Geometry, crop_ids: string[], system = "multilayer"): Promise<Blob> => {
    const res = await fetch(`${BASE}/reports/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geometry, crop_ids, system }),
    });
    if (!res.ok) throw new Error(`/reports/pdf -> ${res.status}`);
    return res.blob();
  },

  // --- auth (identity is owned by Supabase; this confirms the session) ---
  me: () => get<User>("/auth/me", true),

  // --- saved fields (require auth) ---
  createField: (name: string, geometry: Geometry) =>
    post<SavedField>("/fields", { name, geometry }, true),

  listFields: () => get<SavedField[]>("/fields", true),

  deleteField: async (id: string) => {
    const res = await fetch(`${BASE}/fields/${id}`, {
      method: "DELETE",
      headers: await authHeaders(),
    });
    if (!res.ok) throw new Error(`/fields/${id} -> ${res.status}`);
  },
};
