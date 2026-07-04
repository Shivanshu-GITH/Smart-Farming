"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import maplibregl from "maplibre-gl";
import { api, type FieldSummary, type Recommendation, type LayoutResult, type Geometry, type SavedField, type ValidationResult, type DesignResult, type DesignStack, type PlanResult, type EconomicsResult, type CatalogueCrop, type FarmingSystem, type GeoResult } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import AdvisoryChat from "@/components/AdvisoryChat";
import SchemesCard from "@/components/SchemesCard";

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
  const t = useTranslations();
  const mapEl = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const drawingRef = useRef(false);
  const vertsRef = useRef<number[][]>([]);

  const [drawing, setDrawing] = useState(false);
  const [vertCount, setVertCount] = useState(0);
  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const [summary, setSummary] = useState<FieldSummary | null>(null);
  const [land, setLand] = useState<any>(null);
  const [ndvi, setNdvi] = useState<any>(null);
  const [elevation, setElevation] = useState<any>(null);
  const [ndviSeries, setNdviSeries] = useState<{ date: string; mean: number }[]>([]);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [layout, setLayout] = useState<LayoutResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // ---- Stage 3: moat (validation, 5-layer design, calendar) ----
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [design, setDesign] = useState<DesignResult | null>(null);
  const [designBusy, setDesignBusy] = useState(false);
  const [plans, setPlans] = useState<PlanResult[]>([]);
  const [economics, setEconomics] = useState<EconomicsResult | null>(null);

  // ---- farming systems + full crop catalogue ----
  const [systems, setSystems] = useState<FarmingSystem[]>([]);
  const [system, setSystem] = useState("multilayer");
  const [catalogue, setCatalogue] = useState<CatalogueCrop[]>([]);
  const [cropTab, setCropTab] = useState<"recommended" | "all">("recommended");
  const [cropSearch, setCropSearch] = useState("");

  // ---- map location search ----
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<GeoResult[] | null>(null);
  const [searching, setSearching] = useState(false);

  // ---- manual land entry (no polygon) ----
  const [manualMode, setManualMode] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualPlaceQ, setManualPlaceQ] = useState("");
  const [manualPlace, setManualPlace] = useState<GeoResult | null>(null);
  const [manualResults, setManualResults] = useState<GeoResult[] | null>(null);
  const [manualArea, setManualArea] = useState("");
  const [manualUnit, setManualUnit] = useState<"acre" | "hectare" | "guntha">("acre");

  useEffect(() => {
    api.systems().then((r) => setSystems(r.systems)).catch(() => {});
    api.crops().then((r) => setCatalogue(r.crops)).catch(() => {});
  }, []);

  function landCtx(): Record<string, unknown> {
    return {
      ph: land?.soil?.ph ?? undefined,
      texture: land?.soil?.texture_class ?? undefined,
      rainfall_mm: land?.climate?.annual_rainfall_mm ?? undefined,
      temp_max_c: land?.climate?.temp_max_avg_c ?? undefined,
      season: land?.climate?.season ?? undefined,
    };
  }

  // Validate the selected combo (for the chosen system) whenever it changes.
  useEffect(() => {
    if (selected.length === 0) { setValidation(null); return; }
    let cancelled = false;
    api.validate(selected, { ...landCtx(), system })
      .then((v) => { if (!cancelled) setValidation(v); })
      .catch(() => { if (!cancelled) setValidation(null); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, land, system]);

  // ---- auth + saved fields ----
  const { user } = useAuth();
  const [savedFields, setSavedFields] = useState<SavedField[]>([]);
  const [fieldName, setFieldName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [savedFieldId, setSavedFieldId] = useState<string | null>(null);
  const [planSaved, setPlanSaved] = useState(false);

  // Load the user's saved fields whenever they sign in (clear on sign-out).
  useEffect(() => {
    if (!user) { setSavedFields([]); return; }
    api.listFields().then(setSavedFields).catch(() => {});
  }, [user]);

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
      setVertCount(vertsRef.current.length);
      renderDraw(m, vertsRef.current);
    });
    map.current = m;
  }, []);

  // ---- drawing controls ----
  function startDraw() {
    vertsRef.current = [];
    drawingRef.current = true;
    setDrawing(true); setVertCount(0);
    setManualMode(false); setManualOpen(false);
    setGeometry(null); setSummary(null); setLand(null); setNdvi(null); setNdviSeries([]);
    setElevation(null); setSavedFieldId(null); setPlanSaved(false);
    setRecs([]); setSelected([]); setLayout(null);
    setValidation(null); setDesign(null); setPlans([]); setEconomics(null);
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
    (map.current.getSource("draw") as any)?.setData(emptyFC());
    await applyGeometry(geom, { fit: false });
  }

  /** Render a polygon as the active field and run the analysis pipeline.
   *  Shared by fresh drawing and loading a saved field. */
  async function applyGeometry(geom: Geometry, opts: { fit: boolean }) {
    setGeometry(geom);
    setSaveMsg(null);
    setFieldName("");
    if (map.current) {
      (map.current.getSource("field") as any)?.setData({
        type: "FeatureCollection",
        features: [{ type: "Feature", geometry: geom, properties: {} }],
      });
      (map.current.getSource("plants") as any)?.setData(emptyFC());
      (map.current.getSource("heat") as any)?.setData(emptyFC());
      if (opts.fit) fitToRing(map.current, geom.coordinates[0]);
    }
    setLayout(null); setSelected([]); setPlanSaved(false);
    await analyze(geom);
  }

  async function saveField() {
    if (!geometry || !user) return;
    setSaving(true); setSaveMsg(null);
    try {
      const name = fieldName.trim() ||
        summary?.region?.village || summary?.region?.district || "My field";
      const saved = await api.createField(name, geometry);
      setSavedFields((cur) => [saved, ...cur]);
      setSavedFieldId(saved.id);
      setSaveMsg(`Saved “${saved.name}”.`);
      setFieldName("");
    } catch {
      setSaveMsg("Could not save field.");
    } finally {
      setSaving(false);
    }
  }

  async function loadSavedField(f: SavedField) {
    startDraw();               // reset all state + map layers
    drawingRef.current = false;
    setDrawing(false);
    await applyGeometry(f.geometry, { fit: true });
    setSavedFieldId(f.id);     // subsequent plans/layouts attach to this field
  }

  async function savePlanAndLayout() {
    if (!savedFieldId || !layout) return;
    try {
      await api.saveLayout(savedFieldId, layout);
      if (plans.length) await api.savePlan(savedFieldId, null, { plans, economics });
      setPlanSaved(true);
    } catch {
      /* ignore — surfaced via button state */
    }
  }

  async function deleteSavedField(id: string) {
    try {
      await api.deleteField(id);
      setSavedFields((cur) => cur.filter((f) => f.id !== id));
    } catch {
      /* ignore */
    }
  }

  async function analyze(geom: Geometry) {
    try {
      setBusy("Computing area & region…");
      const s = await api.fieldSummary(geom);
      setSummary(s);
      api.elevation(s.centroid.lat, s.centroid.lon).then(setElevation).catch(() => setElevation(null));
      setBusy("Fetching soil & climate…");
      const report = await api.landReport(s.centroid.lat, s.centroid.lon).catch(() => null);
      setLand(report);
      // NDVI needs the polygon; fetch in the background (may be unconfigured).
      api.ndvi(geom).then(setNdvi).catch(() => setNdvi(null));
      api.ndviSeries(geom).then((r) => setNdviSeries(r.series || [])).catch(() => setNdviSeries([]));
      setBusy("Recommending crops…");
      const recRes = await api.recommend({
        ph: report?.soil?.ph ?? undefined,
        texture: report?.soil?.texture_class ?? undefined,
        rainfall_mm: report?.climate?.annual_rainfall_mm ?? undefined,
        temp_max_c: report?.climate?.temp_max_avg_c ?? undefined,
        season: report?.climate?.season ?? undefined,
        system,
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
    const max = systems.find((s) => s.id === system)?.crops_max ?? 5;
    setSelected((cur) => {
      if (cur.includes(id)) return cur.filter((c) => c !== id);
      if (max === 1) return [id];        // monoculture: picking replaces
      if (cur.length >= max) return cur;  // at the system's cap
      return [...cur, id];
    });
  }

  function changeSystem(id: string) {
    if (id === system) return;
    setSystem(id);
    setSelected([]); setLayout(null); setValidation(null); setDesign(null);
    setPlans([]); setEconomics(null); setPlanSaved(false);
    if (land) {
      api.recommend({ ...landCtx(), system: id, limit: 8 })
        .then((r) => setRecs(r.recommendations)).catch(() => {});
    }
  }

  // ---- map location search ----
  async function doSearch() {
    const q = searchQ.trim();
    if (q.length < 2) return;
    setSearching(true);
    try {
      const r = await api.geoSearch(q);
      setSearchResults(r.results);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }

  function gotoResult(r: GeoResult) {
    setSearchResults(null);
    setSearchQ(r.display_name.split(",")[0]);
    if (!map.current) return;
    if (r.bbox) {
      const [s, n, w, e] = r.bbox;  // Nominatim: [south, north, west, east]
      map.current.fitBounds([[w, s], [e, n]], { padding: 60, duration: 900, maxZoom: 16 });
    } else {
      map.current.flyTo({ center: [r.lon, r.lat], zoom: 15, duration: 900 });
    }
  }

  // ---- manual land entry (plans without a drawn polygon) ----
  async function findManualPlace() {
    const q = manualPlaceQ.trim();
    if (q.length < 2) return;
    try {
      const r = await api.geoSearch(q);
      setManualResults(r.results);
    } catch {
      setManualResults([]);
    }
  }

  async function manualAnalyze() {
    const areaVal = parseFloat(manualArea);
    if (!manualPlace || !areaVal || areaVal <= 0) return;
    const m2 = areaVal * (manualUnit === "acre" ? 4046.8564224
      : manualUnit === "hectare" ? 10000 : 101.17141056);

    setManualOpen(false); setManualMode(true);
    setGeometry(null); setLayout(null); setSelected([]); setPlans([]);
    setEconomics(null); setValidation(null); setDesign(null);
    setNdvi(null); setNdviSeries([]); setSavedFieldId(null); setPlanSaved(false);

    // "Tenali, Guntur, Andhra Pradesh, 522200, India" → drop postcode + country
    const parts = manualPlace.display_name.split(",").map((p) => p.trim())
      .filter((p) => !/^\d+$/.test(p) && p.toLowerCase() !== "india");
    setSummary({
      area: {
        square_meters: m2,
        hectares: +(m2 / 10000).toFixed(4),
        acres: +(m2 / 4046.8564224).toFixed(4),
        guntha: +(m2 / 101.17141056).toFixed(2),
      },
      perimeter_meters: 0,
      centroid: { lat: manualPlace.lat, lon: manualPlace.lon },
      bbox: [],
      region: {
        display_name: manualPlace.display_name,
        district: parts.length > 1 ? parts[parts.length - 2] : parts[0],
        state: parts.length ? parts[parts.length - 1] : undefined,
      },
    } as FieldSummary);
    map.current?.flyTo({ center: [manualPlace.lon, manualPlace.lat], zoom: 14, duration: 900 });

    try {
      setBusy("Fetching soil & climate…");
      const report = await api.landReport(manualPlace.lat, manualPlace.lon).catch(() => null);
      setLand(report);
      api.elevation(manualPlace.lat, manualPlace.lon).then(setElevation).catch(() => setElevation(null));
      setBusy("Recommending crops…");
      const recRes = await api.recommend({
        ph: report?.soil?.ph ?? undefined,
        texture: report?.soil?.texture_class ?? undefined,
        rainfall_mm: report?.climate?.annual_rainfall_mm ?? undefined,
        temp_max_c: report?.climate?.temp_max_avg_c ?? undefined,
        season: report?.climate?.season ?? undefined,
        system,
        limit: 8,
      });
      setRecs(recRes.recommendations);
    } finally {
      setBusy(null);
    }
  }

  /** Manual mode: plans + economics from area alone (layout needs a polygon). */
  async function generatePlanOnly() {
    if (selected.length === 0) return;
    const areaM2 = summary?.area.square_meters ?? 0;
    setBusy("Preparing crop plan…");
    try {
      const ps = await Promise.all(
        selected.map((id) => api.plan(id, areaM2).catch(() => null)));
      setPlans(ps.filter((p): p is PlanResult => p !== null));
      api.economics(selected, areaM2, summary?.region?.state)
        .then(setEconomics).catch(() => setEconomics(null));
    } finally {
      setBusy(null);
    }
  }

  async function designStack() {
    if (!land) return;
    setDesignBusy(true);
    try {
      setDesign(await api.design(landCtx()));
    } catch {
      setDesign(null);
    } finally {
      setDesignBusy(false);
    }
  }

  function applyStack(stack: DesignStack) {
    setSelected(stack.crop_ids);
    setDesign(null);
  }

  async function generateLayout() {
    if (!geometry || selected.length === 0) return;
    setBusy("Placing plants…");
    try {
      const res = await api.layout(geometry, selected, system);
      setLayout(res);
      // Fetch per-crop plans (seed / fertiliser / calendar) for the summary.
      const areaM2 = summary?.area.square_meters ?? 0;
      const ps = await Promise.all(
        selected.map((id) => api.plan(id, areaM2).catch(() => null)));
      setPlans(ps.filter((p): p is PlanResult => p !== null));
      // Cost / revenue / profit estimate (mandi prices when available).
      const state = summary?.region?.state;
      api.economics(selected, areaM2, state).then(setEconomics).catch(() => setEconomics(null));
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

  async function downloadPdf() {
    if (!geometry) return;
    setPdfBusy(true);
    try {
      const blob = await api.reportPdf(geometry, selected);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "smartfarm-report.pdf";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
    } finally {
      setPdfBusy(false);
    }
  }

  return (
    <div className="app">
      <div id="map" ref={mapEl} />

      <div className="map-search">
        <input
          value={searchQ}
          placeholder={t("map.search")}
          onChange={(e) => setSearchQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }}
        />
        <button className="btn btn-sm" disabled={searching || searchQ.trim().length < 2}
          onClick={doSearch}>
          {searching ? "…" : "🔍"}
        </button>
        {searchResults !== null && (
          <div className="map-search-results">
            {searchResults.length === 0 && (
              <div className="map-search-item muted">{t("map.noResults")}</div>
            )}
            {searchResults.map((r, i) => (
              <div className="map-search-item" key={i} onClick={() => gotoResult(r)}>
                {r.display_name}
              </div>
            ))}
          </div>
        )}
      </div>

      <aside className="sidebar">
        <div className="brand">
          <span className="leaf">🌱</span>
          <h1>SmartFarm</h1>
        </div>
        <p className="tagline">{t("brand.tagline")}</p>

        <div className="card">
          <h3>{t("land.title")}</h3>
          <div className="btn-row">
            {!drawing ? (
              <button className="btn" onClick={startDraw}>{t("land.draw")}</button>
            ) : (
              <button className="btn" onClick={finishDraw}>{t("land.finish", { n: vertCount })}</button>
            )}
            {drawing && <span className="hint">{t("land.drawHint")}</span>}
          </div>

          {!drawing && !geometry && !manualMode && (
            <button className="btn-link" style={{ marginTop: 8 }}
              onClick={() => setManualOpen((o) => !o)}>
              {t("manual.cant")}
            </button>
          )}
          {manualOpen && (
            <div className="manual-panel">
              <p className="hint" style={{ fontWeight: 600 }}>{t("manual.title")}</p>
              <div className="save-row">
                <input className="input" placeholder={t("manual.place")}
                  value={manualPlaceQ}
                  onChange={(e) => setManualPlaceQ(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") findManualPlace(); }} />
                <button className="btn btn-sm" onClick={findManualPlace}>
                  {t("manual.findPlace")}
                </button>
              </div>
              {manualResults !== null && !manualPlace && (
                <div className="manual-results">
                  {manualResults.length === 0 && (
                    <div className="map-search-item muted">{t("map.noResults")}</div>
                  )}
                  {manualResults.map((r, i) => (
                    <div className="map-search-item" key={i}
                      onClick={() => { setManualPlace(r); setManualResults(null); setManualPlaceQ(r.display_name.split(",")[0]); }}>
                      {r.display_name}
                    </div>
                  ))}
                </div>
              )}
              {manualPlace && (
                <p className="hint">📍 {manualPlace.display_name}</p>
              )}
              <div className="save-row">
                <input className="input" type="number" min="0" step="0.1"
                  placeholder={t("manual.area")}
                  value={manualArea} onChange={(e) => setManualArea(e.target.value)} />
                <select className="lang-select" value={manualUnit}
                  onChange={(e) => setManualUnit(e.target.value as any)}>
                  <option value="acre">{t("manual.unitAcre")}</option>
                  <option value="hectare">{t("manual.unitHectare")}</option>
                  <option value="guntha">{t("manual.unitGuntha")}</option>
                </select>
              </div>
              <button className="btn" style={{ width: "100%", marginTop: 8 }}
                disabled={!manualPlace || !parseFloat(manualArea)}
                onClick={manualAnalyze}>
                {t("manual.submit")}
              </button>
              <p className="disclaimer">{t("manual.note")}</p>
            </div>
          )}

          {busy && <p className="spinner">⏳ {busy}</p>}
          {summary && (
            <div style={{ marginTop: 10 }}>
              <div className="kv"><span className="k">{t("land.area")}</span>
                <span className="v">{summary.area.acres} ac · {summary.area.hectares} ha</span></div>
              <div className="kv"><span className="k">{t("land.guntha")}</span>
                <span className="v">{summary.area.guntha}</span></div>
              {summary.perimeter_meters > 0 && (
                <div className="kv"><span className="k">{t("land.perimeter")}</span>
                  <span className="v">{summary.perimeter_meters} m</span></div>
              )}
              <div className="kv"><span className="k">{t("land.region")}</span>
                <span className="v">{summary.region.district || summary.region.village || "—"}, {summary.region.state || ""}</span></div>
            </div>
          )}
          {geometry && summary && (
            user ? (
              <div className="save-row">
                <input className="input" placeholder={t("land.nameField")}
                  value={fieldName} onChange={(e) => setFieldName(e.target.value)} />
                <button className="btn btn-sm" disabled={saving} onClick={saveField}>
                  {saving ? t("land.saving") : t("land.save")}
                </button>
              </div>
            ) : (
              <p className="hint" style={{ marginTop: 8 }}>{t("land.signInToSave")}</p>
            )
          )}
          {saveMsg && <p className="hint" style={{ marginTop: 6 }}>{saveMsg}</p>}
        </div>

        {user && savedFields.length > 0 && (
          <div className="card">
            <h3>{t("myFields.title")}</h3>
            {savedFields.map((f) => (
              <div className="saved-field" key={f.id}>
                <button className="btn-link" onClick={() => loadSavedField(f)}>
                  {f.name}
                </button>
                <span className="meta">
                  {f.area ? `${f.area.acres} ac` : ""}
                </span>
                <button className="icon-btn" title="Delete"
                  onClick={() => deleteSavedField(f.id)}>✕</button>
              </div>
            ))}
          </div>
        )}

        {land && (
          <div className="card">
            <h3>{t("intel.title")}</h3>
            <div className="kv"><span className="k">{t("intel.soilTexture")}</span>
              <span className="v">{land.soil?.texture_class || "—"}</span></div>
            <div className="kv"><span className="k">{t("intel.soilPh")}</span>
              <span className="v">{land.soil?.ph ?? "—"}</span></div>
            <div className="kv"><span className="k">{t("intel.season")}</span>
              <span className="v">{land.climate?.season || "—"}</span></div>
            <div className="kv"><span className="k">{t("intel.rainfall")}</span>
              <span className="v">{land.climate?.annual_rainfall_mm ?? "—"} mm ({land.climate?.rainfall_band || "—"})</span></div>
            <div className="kv"><span className="k">{t("intel.maxTemp")}</span>
              <span className="v">{land.climate?.temp_max_avg_c ?? "—"} °C</span></div>
            {elevation?.elevation_m != null && (
              <div className="kv"><span className="k">{t("intel.elevation")}</span>
                <span className="v">{elevation.elevation_m} m
                  {elevation.slope_class ? ` · ${t("intel.slope")} ${elevation.slope_class}` : ""}
                  {elevation.aspect ? ` (${elevation.aspect})` : ""}</span></div>
            )}
            {ndvi?.mean != null && (
              <div className="kv"><span className="k">{t("intel.ndvi")}</span>
                <span className="v">{ndvi.mean} · {ndvi.vigour || "—"}</span></div>
            )}
            {ndvi && ndvi.configured === false && (
              <div className="kv"><span className="k">NDVI</span>
                <span className="v" style={{ color: "var(--muted)", fontWeight: 400 }}>
                  {t("intel.ndviKey")}</span></div>
            )}
            {ndviSeries.length >= 2 && (
              <div className="kv" style={{ alignItems: "center" }}>
                <span className="k">{t("monitor.title")}</span>
                <span className="v">
                  {sparkline(ndviSeries.map((p) => p.mean))}{" "}
                  {ndviSeries[ndviSeries.length - 1].mean >= ndviSeries[0].mean
                    ? t("monitor.improving") : t("monitor.declining")}
                </span>
              </div>
            )}
            <p className="disclaimer">{t("intel.disclaimer")}</p>
          </div>
        )}

        {land && (
          <div className="card">
            <h3>{t("method.title")}</h3>

            <div className="sys-row">
              {(systems.length ? systems : [
                { id: "monoculture" }, { id: "intercrop" }, { id: "multilayer" },
              ] as FarmingSystem[]).map((s) => (
                <button key={s.id}
                  className={"sys" + (system === s.id ? " active" : "")}
                  onClick={() => changeSystem(s.id)}>
                  {t(`systems.${s.id}.name`)}
                </button>
              ))}
            </div>
            <p className="hint" style={{ marginBottom: 8 }}>{t(`systems.${system}.desc`)}</p>

            <div className="tabs">
              <button className={"tab" + (cropTab === "recommended" ? " active" : "")}
                onClick={() => setCropTab("recommended")}>{t("method.tabRecommended")}</button>
              <button className={"tab" + (cropTab === "all" ? " active" : "")}
                onClick={() => setCropTab("all")}>{t("method.tabAll")}</button>
            </div>

            {cropTab === "recommended" && recs.map((r) => (
              <div key={r.crop_id}
                className={"crop" + (selected.includes(r.crop_id) ? " selected" : "")}
                onClick={() => toggleCrop(r.crop_id)}>
                <span className="dot" style={{ background: LAYER_COLORS[r.layer] }} />
                <div>
                  <div className="name">{r.name}</div>
                  <div className="meta">{r.layer} · {r.category}</div>
                </div>
                <span className={"badge " + (r.score >= 0.8 ? "high" : r.score >= 0.6 ? "ok" : "")}>
                  {r.suitability}
                </span>
              </div>
            ))}

            {cropTab === "all" && (
              <>
                <input className="input" placeholder={t("method.searchCrops")}
                  value={cropSearch} onChange={(e) => setCropSearch(e.target.value)} />
                <div className="crop-list">
                  {catalogue
                    .filter((c) => c.systems.includes(system))
                    .filter((c) => {
                      const q = cropSearch.trim().toLowerCase();
                      if (!q) return true;
                      return c.name.toLowerCase().includes(q) ||
                        c.common_names.some((n) => n.toLowerCase().includes(q));
                    })
                    .map((c) => (
                      <div key={c.id}
                        className={"crop" + (selected.includes(c.id) ? " selected" : "")}
                        onClick={() => toggleCrop(c.id)}>
                        <span className="dot" style={{ background: LAYER_COLORS[c.layer] }} />
                        <div>
                          <div className="name">{c.name}</div>
                          <div className="meta">
                            {c.common_names[0] ? `${c.common_names[0]} · ` : ""}
                            {c.category} · {c.seasons.map((s) => s.split(" ")[0]).join("/")}
                          </div>
                        </div>
                        <span className="badge">{c.duration_days}d</span>
                      </div>
                    ))}
                </div>
              </>
            )}

            {system === "multilayer" && (
              <div className="btn-row" style={{ marginTop: 8 }}>
                <button className="btn secondary" disabled={designBusy || !land}
                  onClick={designStack}>
                  {designBusy ? t("recommend.designing") : t("recommend.design")}
                </button>
              </div>
            )}

            {design && (
              <div className="stacks">
                <p className="hint">{t("recommend.stacksIntro")}
                  {design.season ? ` (${design.season})` : ""}:</p>
                {design.stacks.length === 0 && (
                  <p className="hint">{t("recommend.noStack")}</p>)}
                {design.stacks.map((st, i) => (
                  <div className="stack" key={i} onClick={() => applyStack(st)}>
                    <div className="stack-head">
                      Stack {i + 1} · {st.filled_layers}
                      <span className="badge ok">{t("recommend.use")}</span>
                    </div>
                    {st.layers.map((L) => (
                      <div className="kv" key={L.crop_id}>
                        <span className="k">
                          <span className="dot" style={{ background: LAYER_COLORS[L.layer] }} />
                          {L.layer}</span>
                        <span className="v">{L.name}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}

            {validation && (validation.conflicts.length > 0 ||
              validation.warnings.length > 0 || validation.synergies.length > 0) && (
              <div className="validation">
                {validation.conflicts.map((c, i) => (
                  <p key={"c" + i} className="v-conflict">⛔ {c.message}</p>))}
                {validation.warnings.map((w, i) => (
                  <p key={"w" + i} className="v-warn">⚠️ {w.message}</p>))}
                {validation.synergies.map((s, i) => (
                  <p key={"s" + i} className="v-syn">✅ {s.message}</p>))}
              </div>
            )}

            {validation?.fillers && Object.keys(validation.fillers).length > 0 && (
              <div className="fillers">
                <p className="hint">{t("recommend.fillEmpty")}</p>
                {Object.entries(validation.fillers).map(([layer, cands]) => (
                  <div className="kv" key={layer}>
                    <span className="k"><span className="dot"
                      style={{ background: LAYER_COLORS[layer] }} />{layer}</span>
                    <span className="v">
                      {cands.map((c) => (
                        <button key={c.crop_id} className="chip"
                          onClick={() => toggleCrop(c.crop_id)}>
                          + {c.name}{c.companion_with.length ? " ★" : ""}
                        </button>
                      ))}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {manualMode ? (
              <>
                <button className="btn" style={{ marginTop: 8 }}
                  disabled={selected.length === 0} onClick={generatePlanOnly}>
                  {t("method.planOnly")}
                </button>
                <p className="hint" style={{ marginTop: 6 }}>{t("layout.drawNeeded")}</p>
              </>
            ) : (
              <button className="btn" style={{ marginTop: 8 }}
                disabled={selected.length === 0 || !geometry} onClick={generateLayout}>
                {t("recommend.generate")}
              </button>
            )}
          </div>
        )}

        {(layout || plans.length > 0) && (
          <div className="card">
            <h3>{layout ? t("layout.title") : t("layout.planTitle")}</h3>
            {layout && (
              <div className="kv"><span className="k">{t("layout.totalPlants")}</span>
                <span className="v">{layout.total_plants.toLocaleString()}{layout.truncated ? " (sampled view)" : ""}</span></div>
            )}
            {layout?.crops.map((c) => (
              <div className="kv" key={c.crop_id}>
                <span className="k"><span className="dot" style={{ background: LAYER_COLORS[c.layer] }} />{c.name}</span>
                <span className="v">{c.plant_count.toLocaleString()}</span>
              </div>
            ))}

            {plans.length > 0 && (
              <div className="calendar">
                <p className="hint" style={{ marginTop: 8 }}>{t("layout.calendar")}</p>
                {plans.map((p) => (
                  <details className="cal-crop" key={p.crop.id}>
                    <summary>
                      <span className="dot" style={{ background: LAYER_COLORS[p.crop.layer] }} />
                      {p.crop.name} · {p.seed.quantity_kg} kg {t("layout.seed")} ·
                      N{p.fertilizer.total_kg.N}-P{p.fertilizer.total_kg.P}-K{p.fertilizer.total_kg.K}
                    </summary>
                    {p.calendar.map((s) => (
                      <div className="kv" key={s.stage}>
                        <span className="k">{s.stage}</span>
                        <span className="v">day {s.day} · {s.date}</span>
                      </div>
                    ))}
                  </details>
                ))}
              </div>
            )}
            {layout && (
              <>
                <div className="btn-row" style={{ marginTop: 10 }}>
                  <label className="hint">
                    <input type="checkbox" onChange={(e) => toggleHeatmap(e.target.checked)} /> {t("layout.showHeatmap")}
                  </label>
                </div>
                <div className="legend">
                  {Object.entries(LAYER_COLORS).map(([k, v]) => (
                    <span key={k}><span className="dot" style={{ background: v }} />{k}</span>
                  ))}
                </div>
              </>
            )}
            {geometry && (
              <button className="btn secondary" style={{ marginTop: 10, width: "100%" }}
                disabled={pdfBusy} onClick={downloadPdf}>
                {pdfBusy ? t("layout.preparing") : t("layout.downloadPdf")}
              </button>
            )}
            {layout && user && (savedFieldId ? (
              <button className="btn" style={{ marginTop: 8, width: "100%" }}
                disabled={planSaved} onClick={savePlanAndLayout}>
                {planSaved ? t("layout.savePlanDone") : t("layout.savePlan")}
              </button>
            ) : (
              <p className="hint" style={{ marginTop: 8 }}>{t("layout.savePlanHint")}</p>
            ))}
          </div>
        )}

        {economics && economics.crops.length > 0 && (
          <div className="card">
            <h3>{t("profit.title")}</h3>
            {economics.crops.map((c) => (
              <div className="kv" key={c.crop_id}>
                <span className="k">
                  <span className="dot" style={{ background: LAYER_COLORS[c.layer] }} />
                  {c.name}
                  {c.price_source === "mandi" && <span className="tag">mandi</span>}
                </span>
                <span className="v" style={{ color: c.margin[0] >= 0 ? "#6fe39a" : "#ff6b57" }}>
                  {inr(c.margin[0])}–{inr(c.margin[1])}
                </span>
              </div>
            ))}
            <div className="kv total-row"><span className="k">{t("profit.inputCost")}</span>
              <span className="v">{inr(economics.totals.cost)}</span></div>
            <div className="kv"><span className="k">{t("profit.revenue")}</span>
              <span className="v">{inr(economics.totals.revenue[0])}–{inr(economics.totals.revenue[1])}</span></div>
            <div className="kv"><span className="k"><b>{t("profit.netProfit")}</b></span>
              <span className="v"><b style={{ color: economics.totals.margin[0] >= 0 ? "#6fe39a" : "#ff6b57" }}>
                {inr(economics.totals.margin[0])}–{inr(economics.totals.margin[1])}</b></span></div>
            {economics.layers > 1 && (
              <p className="hint" style={{ marginTop: 6 }}>
                {t("profit.multiLayer", { n: economics.layers })}
              </p>
            )}
            <p className="disclaimer">{economics.disclaimer}</p>
          </div>
        )}

        {!geometry && !drawing && !manualMode && (
          <p className="empty">{t("land.empty")}</p>
        )}

        <SchemesCard state={summary?.region?.state} />
      </aside>
      <AdvisoryChat context={{
        area: summary?.area, region: summary?.region,
        soil: land?.soil, climate: land?.climate,
        ndvi: ndvi ? { mean: ndvi.mean, vigour: ndvi.vigour } : null,
        selected_crops: selected,
      }} />
    </div>
  );
}

function sparkline(values: number[]): React.ReactNode {
  const w = 70, h = 18, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - 2 * pad);
    const y = h - pad - ((v - min) / span) * (h - 2 * pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={w} height={h} style={{ verticalAlign: "middle" }}>
      <polyline points={pts} fill="none" stroke="#6fe39a" strokeWidth="1.5" />
    </svg>
  );
}

function inr(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}₹${Math.abs(Math.round(n)).toLocaleString("en-IN")}`;
}

function emptyFC() {
  return { type: "FeatureCollection", features: [] } as any;
}

function fitToRing(m: maplibregl.Map, ring: number[][]) {
  if (!ring.length) return;
  const b = new maplibregl.LngLatBounds(
    [ring[0][0], ring[0][1]], [ring[0][0], ring[0][1]]);
  for (const [lng, lat] of ring) b.extend([lng, lat]);
  m.fitBounds(b, { padding: 60, duration: 600 });
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
