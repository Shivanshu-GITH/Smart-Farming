"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { api, type FieldSummary, type Recommendation, type LayoutResult, type Geometry } from "@/lib/api";

const LAYER_COLORS: Record<string, string> = {
  underground: "#b5651d",
  ground: "#7cd14f",
  middle: "#3fae6a",
  vine: "#56c2c2",
  top: "#e2b13c",
};

const SAT_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    sat: {
      type: "raster",
      tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
      tileSize: 256,
      attribution: "Esri World Imagery",
    },
  },
  layers: [{ id: "sat", type: "raster", source: "sat" }],
};

export default function Planner() {
  const mapEl = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const drawingRef = useRef(false);
  const vertsRef = useRef<number[][]>([]);

  const [drawing, setDrawing] = useState(false);
  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const [summary, setSummary] = useState<FieldSummary | null>(null);
  const [land, setLand] = useState<any>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [layout, setLayout] = useState<LayoutResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // ---- map init ----
  useEffect(() => {
    if (!mapEl.current || map.current) return;
    const m = new maplibregl.Map({
      container: mapEl.current,
      style: SAT_STYLE,
      center: [80.62, 16.5], // Andhra Pradesh
      zoom: 15,
    });
    m.addControl(new maplibregl.NavigationControl(), "top-left");
    m.on("load", () => {
      m.addSource("draw", { type: "geojson", data: emptyFC() });
      m.addLayer({ id: "draw-line", type: "line", source: "draw",
        paint: { "line-color": "#ffd24a", "line-width": 2, "line-dasharray": [2, 1] } });
      m.addLayer({ id: "draw-pts", type: "circle", source: "draw",
        filter: ["==", "$type", "Point"],
        paint: { "circle-radius": 4, "circle-color": "#ffd24a" } });

      m.addSource("field", { type: "geojson", data: emptyFC() });
      m.addLayer({ id: "field-fill", type: "fill", source: "field",
        paint: { "fill-color": "#3fae6a", "fill-opacity": 0.18 } });
      m.addLayer({ id: "field-outline", type: "line", source: "field",
        paint: { "line-color": "#3fae6a", "line-width": 2 } });

      m.addSource("heat", { type: "geojson", data: emptyFC() });
      m.addLayer({ id: "heat-fill", type: "fill", source: "heat",
        paint: {
          "fill-color": ["interpolate", ["linear"], ["get", "intensity"],
            0, "#0b3d2e", 0.5, "#d8a23a", 1, "#e0492f"],
          "fill-opacity": 0.0,
        } });

      m.addSource("plants", { type: "geojson", data: emptyFC() });
      m.addLayer({ id: "plants-pts", type: "circle", source: "plants",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 14, 2, 18, 4],
          "circle-color": ["match", ["get", "layer"],
            "underground", LAYER_COLORS.underground,
            "ground", LAYER_COLORS.ground,
            "middle", LAYER_COLORS.middle,
            "vine", LAYER_COLORS.vine,
            "top", LAYER_COLORS.top,
            "#ffffff"],
          "circle-stroke-width": 0.5, "circle-stroke-color": "#06120b",
        } });
    });

    m.on("click", (e) => {
      if (!drawingRef.current) return;
      vertsRef.current.push([e.lngLat.lng, e.lngLat.lat]);
      renderDraw(m, vertsRef.current);
    });
    map.current = m;
  }, []);

  // ---- drawing controls ----
  function startDraw() {
    vertsRef.current = [];
    drawingRef.current = true;
    setDrawing(true);
    setGeometry(null); setSummary(null); setLand(null);
    setRecs([]); setSelected([]); setLayout(null);
    if (map.current) {
      (map.current.getSource("field") as any)?.setData(emptyFC());
      (map.current.getSource("plants") as any)?.setData(emptyFC());
      (map.current.getSource("heat") as any)?.setData(emptyFC());
      renderDraw(map.current, []);
    }
  }

  async function finishDraw() {
    drawingRef.current = false;
    setDrawing(false);
    const verts = vertsRef.current;
    if (verts.length < 3 || !map.current) return;
    const ring = [...verts, verts[0]];
    const geom: Geometry = { type: "Polygon", coordinates: [ring] };
    setGeometry(geom);
    (map.current.getSource("draw") as any)?.setData(emptyFC());
    (map.current.getSource("field") as any)?.setData({
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: geom, properties: {} }],
    });
    await analyze(geom);
  }

  async function analyze(geom: Geometry) {
    try {
      setBusy("Computing area & region…");
      const s = await api.fieldSummary(geom);
      setSummary(s);
      setBusy("Fetching soil & climate…");
      const report = await api.landReport(s.centroid.lat, s.centroid.lon).catch(() => null);
      setLand(report);
      setBusy("Recommending crops…");
      const recRes = await api.recommend({
        ph: report?.soil?.ph ?? undefined,
        texture: report?.soil?.texture_class ?? undefined,
        rainfall_mm: report?.climate?.annual_rainfall_mm ?? undefined,
        temp_max_c: report?.climate?.temp_max_avg_c ?? undefined,
        season: report?.climate?.season ?? undefined,
        limit: 8,
      });
      setRecs(recRes.recommendations);
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(null);
    }
  }

  function toggleCrop(id: string) {
    setSelected((cur) =>
      cur.includes(id) ? cur.filter((c) => c !== id) : [...cur, id]);
  }

  async function generateLayout() {
    if (!geometry || selected.length === 0) return;
    setBusy("Placing plants…");
    try {
      const res = await api.layout(geometry, selected);
      setLayout(res);
      if (map.current) {
        (map.current.getSource("plants") as any)?.setData(res.planting_points);
        const heatFC = {
          type: "FeatureCollection",
          features: res.heatmap.cells.map((c: any) => ({
            type: "Feature",
            properties: { intensity: c.intensity, count: c.count },
            geometry: {
              type: "Polygon",
              coordinates: [[
                [c.bbox[0], c.bbox[1]], [c.bbox[2], c.bbox[1]],
                [c.bbox[2], c.bbox[3]], [c.bbox[0], c.bbox[3]], [c.bbox[0], c.bbox[1]],
              ]],
            },
          })),
        };
        (map.current.getSource("heat") as any)?.setData(heatFC);
      }
    } finally {
      setBusy(null);
    }
  }

  function toggleHeatmap(on: boolean) {
    map.current?.setPaintProperty("heat-fill", "fill-opacity", on ? 0.5 : 0.0);
  }

  return (
    <div className="app">
      <div id="map" ref={mapEl} />
      <aside className="sidebar">
        <div className="brand">
          <span className="leaf">🌱</span>
          <h1>SmartFarm</h1>
        </div>
        <p className="tagline">Draw your land → soil & crop intelligence → planting layout</p>

        <div className="card">
          <h3>1 · Your land</h3>
          <div className="btn-row">
            {!drawing ? (
              <button className="btn" onClick={startDraw}>✏️ Draw field</button>
            ) : (
              <button className="btn" onClick={finishDraw}>✓ Finish ({vertsRef.current.length} pts)</button>
            )}
            {drawing && <span className="hint">Click on the map to add corners, then Finish.</span>}
          </div>
          {busy && <p className="spinner">⏳ {busy}</p>}
          {summary && (
            <div style={{ marginTop: 10 }}>
              <div className="kv"><span className="k">Area</span>
                <span className="v">{summary.area.acres} ac · {summary.area.hectares} ha</span></div>
              <div className="kv"><span className="k">Guntha</span>
                <span className="v">{summary.area.guntha}</span></div>
              <div className="kv"><span className="k">Perimeter</span>
                <span className="v">{summary.perimeter_meters} m</span></div>
              <div className="kv"><span className="k">Region</span>
                <span className="v">{summary.region.district || summary.region.village || "—"}, {summary.region.state || ""}</span></div>
            </div>
          )}
        </div>

        {land && (
          <div className="card">
            <h3>2 · Land intelligence</h3>
            <div className="kv"><span className="k">Soil texture</span>
              <span className="v">{land.soil?.texture_class || "—"}</span></div>
            <div className="kv"><span className="k">Soil pH</span>
              <span className="v">{land.soil?.ph ?? "—"}</span></div>
            <div className="kv"><span className="k">Season</span>
              <span className="v">{land.climate?.season || "—"}</span></div>
            <div className="kv"><span className="k">Rainfall</span>
              <span className="v">{land.climate?.annual_rainfall_mm ?? "—"} mm ({land.climate?.rainfall_band || "—"})</span></div>
            <div className="kv"><span className="k">Max temp</span>
              <span className="v">{land.climate?.temp_max_avg_c ?? "—"} °C</span></div>
            <p className="disclaimer">Soil from SoilGrids (~250 m estimate). Verify with a local soil test.</p>
          </div>
        )}

        {recs.length > 0 && (
          <div className="card">
            <h3>3 · Recommended crops — pick your layers</h3>
            {recs.map((r) => (
              <div key={r.crop_id}
                className={"crop" + (selected.includes(r.crop_id) ? " selected" : "")}
                onClick={() => toggleCrop(r.crop_id)}>
                <span className="dot" style={{ background: LAYER_COLORS[r.layer] }} />
                <div>
                  <div className="name">{r.name}</div>
                  <div className="meta">{r.layer} layer · {r.category}</div>
                </div>
                <span className={"badge " + (r.score >= 0.8 ? "high" : r.score >= 0.6 ? "ok" : "")}>
                  {r.suitability}
                </span>
              </div>
            ))}
            <button className="btn" style={{ marginTop: 8 }}
              disabled={selected.length === 0} onClick={generateLayout}>
              🌾 Generate planting layout
            </button>
          </div>
        )}

        {layout && (
          <div className="card">
            <h3>4 · Planting layout</h3>
            <div className="kv"><span className="k">Total plants</span>
              <span className="v">{layout.total_plants.toLocaleString()}{layout.truncated ? "+ (sampled)" : ""}</span></div>
            {layout.crops.map((c) => (
              <div className="kv" key={c.crop_id}>
                <span className="k"><span className="dot" style={{ background: LAYER_COLORS[c.layer] }} />{c.name}</span>
                <span className="v">{c.plant_count.toLocaleString()}</span>
              </div>
            ))}
            <div className="btn-row" style={{ marginTop: 10 }}>
              <label className="hint">
                <input type="checkbox" onChange={(e) => toggleHeatmap(e.target.checked)} /> Show density heatmap
              </label>
            </div>
            <div className="legend">
              {Object.entries(LAYER_COLORS).map(([k, v]) => (
                <span key={k}><span className="dot" style={{ background: v }} />{k}</span>
              ))}
            </div>
          </div>
        )}

        {!geometry && !drawing && (
          <p className="empty">Start by drawing your field on the map.</p>
        )}
      </aside>
    </div>
  );
}

function emptyFC() {
  return { type: "FeatureCollection", features: [] } as any;
}

function renderDraw(m: maplibregl.Map, verts: number[][]) {
  const features: any[] = verts.map((c) => ({
    type: "Feature", geometry: { type: "Point", coordinates: c }, properties: {},
  }));
  if (verts.length >= 2) {
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: verts },
      properties: {},
    });
  }
  (m.getSource("draw") as any)?.setData({ type: "FeatureCollection", features });
}
