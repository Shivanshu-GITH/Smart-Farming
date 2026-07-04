const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Geometry = { type: "Polygon"; coordinates: number[][][] };

const TOKEN_KEY = "smartfarm_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

async function post<T>(path: string, body: unknown, auth = false): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(auth ? authHeaders() : {}) },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function get<T>(path: string, auth = false): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: auth ? authHeaders() : {},
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
}

export interface LayoutResult {
  total_plants: number;
  truncated: boolean;
  crops: { crop_id: string; name: string; layer: string; plant_count: number }[];
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

export interface PlanResult {
  crop: { id: string; name: string; layer: string };
  plants: { total_estimate: number; per_hectare: number };
  seed: { quantity_kg: number };
  fertilizer: { total_kg: Record<string, number> };
  calendar: { stage: string; day: number; date: string }[];
  best_practices: string[];
}

export interface ChatMessage { role: "user" | "assistant"; content: string; }

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
  area_hectares: number; currency: string;
  crops: EconCrop[];
  totals: { cost: number; revenue: [number, number]; margin: [number, number] };
  layers: number; disclaimer: string;
}

export interface User {
  id: string; phone: string; name?: string | null;
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

  layout: (geometry: Geometry, crop_ids: string[]) =>
    post<LayoutResult>("/layout", { geometry, crop_ids }),

  ndvi: (geometry: Geometry) =>
    post<{
      configured: boolean; mean?: number | null; vigour?: string | null;
      date?: string; note?: string; error?: string;
    }>("/land-intel/ndvi", { geometry }),

  validate: (crop_ids: string[], ctx: Record<string, unknown> = {}) =>
    post<ValidationResult>("/agronomy/validate", { crop_ids, ...ctx }),

  design: (ctx: Record<string, unknown>) =>
    post<DesignResult>("/agronomy/design", ctx),

  plan: (crop_id: string, area_m2: number) =>
    post<PlanResult>("/agronomy/plan", { crop_id, area_m2 }),

  advisoryStatus: () => get<{ configured: boolean }>("/advisory/status"),

  advisoryChat: (messages: ChatMessage[], context: unknown) =>
    post<{ reply: string }>("/advisory/chat", { messages, context }),

  economics: (crop_ids: string[], area_m2: number, state?: string) =>
    post<EconomicsResult>("/economics/estimate", { crop_ids, area_m2, state }),

  diagnose: (image_base64: string, media_type: string, note?: string, context?: unknown) =>
    post<{ reply: string }>("/advisory/diagnose", { image_base64, media_type, note, context }),

  ndviSeries: (geometry: Geometry, months = 6) =>
    post<{ configured: boolean; series: { date: string; mean: number }[]; trend?: string }>(
      "/land-intel/ndvi-series", { geometry, months }),

  schemes: (state?: string) =>
    get<{ count: number; resources: SchemeResource[] }>(
      `/resources/schemes${state ? `?state=${encodeURIComponent(state)}` : ""}`),

  reportPdf: async (geometry: Geometry, crop_ids: string[]): Promise<Blob> => {
    const res = await fetch(`${BASE}/reports/pdf`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ geometry, crop_ids }),
    });
    if (!res.ok) throw new Error(`/reports/pdf -> ${res.status}`);
    return res.blob();
  },

  // --- auth ---
  requestOtp: (phone: string) =>
    post<{ sent: boolean; dev_code?: string | null }>("/auth/otp/request", { phone }),

  verifyOtp: (phone: string, code: string) =>
    post<{ access_token: string; token_type: string; user: User }>(
      "/auth/otp/verify", { phone, code }),

  me: () => get<User>("/auth/me", true),

  // --- saved fields (require auth) ---
  createField: (name: string, geometry: Geometry) =>
    post<SavedField>("/fields", { name, geometry }, true),

  listFields: () => get<SavedField[]>("/fields", true),

  deleteField: async (id: string) => {
    const res = await fetch(`${BASE}/fields/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error(`/fields/${id} -> ${res.status}`);
  },
};
