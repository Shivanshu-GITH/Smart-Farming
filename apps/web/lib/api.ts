const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Geometry = { type: "Polygon"; coordinates: number[][][] };

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
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

export const api = {
  fieldSummary: (geometry: Geometry) =>
    post<FieldSummary>("/fields/summary", { geometry }),

  landReport: (lat: number, lon: number) =>
    get<any>(`/land-intel/report?lat=${lat}&lon=${lon}`),

  recommend: (q: Record<string, unknown>) =>
    post<{ count: number; recommendations: Recommendation[] }>(
      "/agronomy/recommend", q),

  plan: (crop_id: string, area_m2: number) =>
    post<any>("/agronomy/plan", { crop_id, area_m2 }),

  layout: (geometry: Geometry, crop_ids: string[]) =>
    post<LayoutResult>("/layout", { geometry, crop_ids }),
};
