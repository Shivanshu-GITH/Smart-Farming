"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import maplibregl from "maplibre-gl";
import { api, type FieldSummary, type Recommendation, type LayoutResult, type Geometry, type SavedField, type ValidationResult, type DesignResult, type DesignStack, type PlanResult, type EconomicsResult, type CatalogueCrop, type FarmingSystem, type GeoResult, type GeoVillage } from "@/lib/api";
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

/*
 * Esri answers a request for imagery it does not have with HTTP 200 and a grey
 * "Map data not yet available" JPEG, rather than a 404. MapLibre therefore sees
 * a perfectly good tile and paints it over the farmer's field.
 *
 * A fixed source `maxzoom` cannot fix this, because the depth of Esri's cache
 * varies *per tile*, not globally: over Amethi (UP) and Banswada (TS) the
 * imagery stops at z18, while other places have real z19. Any single cap is
 * simultaneously too deep somewhere and needlessly blurry somewhere else.
 *
 * So detect the placeholder instead. It is one fixed 2521-byte JPEG, identical
 * for every tile it is served for. When we see it we fail the tile, and
 * MapLibre's normal missing-tile handling walks up the pyramid and keeps the
 * nearest real parent on screen (upscaled). The result is that zooming in never
 * reveals the grey placeholder, wherever you are — the imagery just softens.
 */
const ESRI_PROTOCOL = "esri";
const ESRI_NO_DATA_BYTES = 2521;
// Cheap pre-filter (length) plus a content check, so a real 2521-byte tile —
// a uniform stretch of water, say — is not mistaken for the placeholder.
const ESRI_NO_DATA_PROBES: ReadonlyArray<readonly [number, number]> = [
  [100, 9], [600, 0], [1200, 222], [1800, 86], [2400, 0],
];

function isEsriNoDataTile(buf: ArrayBuffer): boolean {
  if (buf.byteLength !== ESRI_NO_DATA_BYTES) return false;
  const bytes = new Uint8Array(buf);
  return ESRI_NO_DATA_PROBES.every(([offset, value]) => bytes[offset] === value);
}

let esriProtocolRegistered = false;

/** Register once per page — addProtocol is global to the maplibre module. */
function registerEsriProtocol() {
  if (esriProtocolRegistered) return;
  esriProtocolRegistered = true;

  maplibregl.addProtocol(ESRI_PROTOCOL, async (params, abortController) => {
    const url = params.url.replace(`${ESRI_PROTOCOL}://`, "https://");
    const response = await fetch(url, { signal: abortController.signal });
    if (!response.ok) throw new Error(`Tile ${response.status}`);

    const data = await response.arrayBuffer();
    if (isEsriNoDataTile(data)) {
      // Throwing marks the tile errored, which is what makes MapLibre fall back
      // to the parent instead of drawing "Map data not yet available".
      throw new Error("No imagery for this tile");
    }
    return { data };
  });
}

const esriTiles = (path: string) =>
  [`${ESRI_PROTOCOL}://server.arcgisonline.com/ArcGIS/rest/services/${path}/MapServer/tile/{z}/{y}/{x}`];

/** Units an Indian farmer is likely to know their plot size in. */
type AreaUnit = "acre" | "hectare" | "guntha";

// Villages rendered as <option> nodes in the picker. Big districts run to
// ~7,600 villages (Sitapur), which is both unscrollable and slow to build as
// DOM nodes; beyond this the type-ahead is the usable path and it still
// searches the full list.
const VILLAGE_SELECT_LIMIT = 400;

const SAT_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    sat: {
      type: "raster",
      tiles: esriTiles("World_Imagery"),
      tileSize: 256,
      attribution: "Esri World Imagery",
    },
    // Google-Maps-style hybrid overlays: roads + place names/admin borders.
    // These are transparent PNGs whose "nothing here" state is simply empty, so
    // they never produce the grey placeholder and need no special handling.
    roads: {
      type: "raster",
      tiles: esriTiles("Reference/World_Transportation"),
      tileSize: 256,
    },
    labels: {
      type: "raster",
      tiles: esriTiles("Reference/World_Boundaries_and_Places"),
      tileSize: 256,
      attribution: "Esri Boundaries & Places",
    },
  },
  layers: [
    { id: "sat", type: "raster", source: "sat" },
    { id: "roads", type: "raster", source: "roads" },
    { id: "labels", type: "raster", source: "labels" },
  ],
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
  // Read through `validation` below (derived), not this — it is gated on the
  // selection so an empty pick can't briefly show the previous combo's verdict.
  const [fetchedValidation, setFetchedValidation] = useState<ValidationResult | null>(null);
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

  // ---- layered location finder (state → district → village) ----
  const [finderOpen, setFinderOpen] = useState(false);
  const [statesList, setStatesList] = useState<string[]>([]);
  const [districtsList, setDistrictsList] = useState<string[]>([]);
  const [finderState, setFinderState] = useState("");
  const [finderDistrict, setFinderDistrict] = useState("");
  const [finderVillage, setFinderVillage] = useState("");
  const [finderResults, setFinderResults] = useState<GeoResult[] | null>(null);
  const [finderBusy, setFinderBusy] = useState(false);
  const [villagesList, setVillagesList] = useState<GeoVillage[]>([]);
  const [villagesBusy, setVillagesBusy] = useState(false);
  const [villagesFailed, setVillagesFailed] = useState(false);
  const [villageSuggest, setVillageSuggest] = useState(false);
  const [villageIdx, setVillageIdx] = useState("");   // <select> value (index)
  const villagesReq = useRef(0);
  const villageMarker = useRef<maplibregl.Marker | null>(null);

  // ---- map overlays (place names, borders, roads) ----
  const [showLabels, setShowLabels] = useState(true);

  // ---- "use my location" (device GPS, never sent to the server) ----
  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState("");
  const [locateAccuracy, setLocateAccuracy] = useState<number | null>(null);

  // Whether the planning service answered at all. Every call in this component
  // swallows its own failure so one dead provider cannot take out the page —
  // but that also meant a completely unreachable service looked identical to a
  // working one with nothing to say. These two calls are the canary: they have
  // no external dependencies, so if they fail the service itself is gone.
  const [serviceDown, setServiceDown] = useState(false);

  // ---- manual land entry (no polygon) ----
  const [manualMode, setManualMode] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [manualPlaceQ, setManualPlaceQ] = useState("");
  const [manualPlace, setManualPlace] = useState<GeoResult | null>(null);
  const [manualResults, setManualResults] = useState<GeoResult[] | null>(null);
  const [manualArea, setManualArea] = useState("");
  const [manualUnit, setManualUnit] = useState<AreaUnit>("acre");

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.systems().then((r) => setSystems(r.systems)),
      api.crops().then((r) => setCatalogue(r.crops)),
    ])
      .then(() => { if (!cancelled) setServiceDown(false); })
      .catch(() => { if (!cancelled) setServiceDown(true); });
    return () => { cancelled = true; };
  }, []);

  // Toggle the names/borders/roads overlay (Google-Maps-hybrid look).
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    const vis = showLabels ? "visible" : "none";
    for (const id of ["roads", "labels"]) {
      if (m.getLayer(id)) m.setLayoutProperty(id, "visibility", vis);
    }
  }, [showLabels]);

  // Water source the farmer reports. The crop statistics behind the recommender
  // mix irrigated and rain-fed land; for rain-fed farms the API also applies
  // each crop's rain-fed rainfall requirement.
  const [water, setWater] = useState<"unknown" | "irrigated" | "rainfed">("unknown");

  function landCtx(): Record<string, unknown> {
    return siteCtx(land, summary?.region?.state, water);
  }

  // Validate the selected combo (for the chosen system) whenever it changes.
  // With nothing selected there is nothing to validate, so `validation` is
  // derived rather than stored — an empty selection cannot show a stale verdict.
  const validation = selected.length === 0 ? null : fetchedValidation;

  useEffect(() => {
    if (selected.length === 0) return;
    let cancelled = false;
    api.validate(selected, { ...landCtx(), system })
      .then((v) => { if (!cancelled) setFetchedValidation(v); })
      .catch(() => { if (!cancelled) setFetchedValidation(null); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, land, system]);

  // ---- auth + saved fields ----
  const { user } = useAuth();
  const [fetchedFields, setFetchedFields] = useState<SavedField[]>([]);
  const [fieldName, setFieldName] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [savedFieldId, setSavedFieldId] = useState<string | null>(null);
  const [planSaved, setPlanSaved] = useState(false);

  // Signed out means no saved fields, so derive it rather than clearing state —
  // one user's fields can never flash up for the next.
  const savedFields = user ? fetchedFields : [];

  // Load the account's saved fields on sign-in.
  useEffect(() => {
    if (!user) return;
    api.listFields().then(setFetchedFields).catch(() => {});
  }, [user]);

  // ---- map init ----
  useEffect(() => {
    if (!mapEl.current || map.current) return;
    // Must happen before the style resolves any tile URL.
    registerEsriProtocol();
    const m = new maplibregl.Map({
      container: mapEl.current,
      style: SAT_STYLE,
      center: [80.62, 16.5], // Andhra Pradesh
      zoom: 15,
    });
    m.addControl(new maplibregl.NavigationControl(), "top-left");
    // Without a listener MapLibre console.errors every failed tile, and the Next
    // dev overlay turns each into an error. Tile failures are expected here —
    // the no-imagery placeholder is rejected on purpose (see registerEsriProtocol)
    // and a flaky connection drops tiles — and MapLibre already falls back to the
    // parent tile. Only non-tile errors are worth surfacing.
    m.on("error", (e) => {
      const tileError = "tile" in e || "sourceId" in e;
      if (!tileError) console.warn("map:", e.error?.message ?? e.error);
    });
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
          // Keep growing past 18 — deep zoom falls back to upscaled parent tiles, so a
          // clamped radius would leave plant dots pinned at 4px while the ground
          // under them keeps scaling up.
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 14, 2, 18, 4, 22, 14],
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

    // Dev-only handle for poking at the map from the console.
    if (process.env.NODE_ENV !== "production") {
      (window as unknown as { __map?: maplibregl.Map }).__map = m;
    }
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
    setFetchedValidation(null); setDesign(null); setPlans([]); setEconomics(null);
    if (map.current) {
      geoSource(map.current, "field")?.setData(emptyFC());
      geoSource(map.current, "plants")?.setData(emptyFC());
      geoSource(map.current, "heat")?.setData(emptyFC());
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
    geoSource(map.current, "draw")?.setData(emptyFC());
    await applyGeometry(geom, { fit: false });
  }

  /** Render a polygon as the active field and run the analysis pipeline.
   *  Shared by fresh drawing and loading a saved field. */
  async function applyGeometry(geom: Geometry, opts: { fit: boolean }) {
    setGeometry(geom);
    setSaveMsg(null);
    setFieldName("");
    if (map.current) {
      geoSource(map.current, "field")?.setData({
        type: "FeatureCollection",
        features: [{ type: "Feature", geometry: geom, properties: {} }],
      });
      geoSource(map.current, "plants")?.setData(emptyFC());
      geoSource(map.current, "heat")?.setData(emptyFC());
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
      setFetchedFields((cur) => [saved, ...cur]);
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
      setFetchedFields((cur) => cur.filter((f) => f.id !== id));
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
        ...siteCtx(report, s.region?.state, water), system, limit: 8,
      });
      setRecs(recRes.recommendations);
    } catch (err) {
      console.error(err);
    } finally {
      setBusy(null);
    }
  }

  function changeWater(w: "unknown" | "irrigated" | "rainfed") {
    if (w === water) return;
    setWater(w);
    if (land) {
      api.recommend({ ...siteCtx(land, summary?.region?.state, w), system, limit: 8 })
        .then((r) => setRecs(r.recommendations)).catch(() => {});
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
    setSelected([]); setLayout(null); setFetchedValidation(null); setDesign(null);
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

  // Fixed `duration` (and custom `speed`) freeze MapLibre's flight math on
  // long jumps — the camera reports isMoving() but never lands. Default speed
  // + maxDuration animates short hops and snaps cross-country jumps.
  const FLY: maplibregl.FlyToOptions = { maxDuration: 6000 };

  function gotoResult(r: GeoResult) {
    setSearchResults(null);
    setFinderResults(null);
    setSearchQ(r.display_name.split(",")[0]);
    if (!map.current) return;
    if (r.bbox) {
      const [s, n, w, e] = r.bbox;  // Nominatim: [south, north, west, east]
      map.current.fitBounds([[w, s], [e, n]], { padding: 60, maxZoom: 16, ...FLY });
    } else {
      map.current.flyTo({ center: [r.lon, r.lat], zoom: 15, ...FLY });
    }
  }

  // ---- "use my location" ----
  /** Centre the map on the device's own GPS fix, with the user's permission.
   *
   *  Nothing is sent anywhere: the fix is used purely to move the map and drop
   *  a marker, so a farmer standing in their field can start drawing straight
   *  away instead of hunting for it by name. */
  function locateMe() {
    setLocateError("");
    if (typeof navigator === "undefined" || !("geolocation" in navigator)) {
      setLocateError(t("map.locateUnsupported"));
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setLocating(false);
        const { latitude: lat, longitude: lon, accuracy } = p.coords;
        setLocateAccuracy(accuracy ?? null);
        const m = map.current;
        if (!m) return;

        // Zoom to roughly the reported accuracy so the pin is not implying more
        // precision than the device actually has.
        const zoom = accuracy && accuracy > 500 ? 14 : accuracy && accuracy > 100 ? 16 : 17;
        m.flyTo({ center: [lon, lat], zoom, ...FLY });

        villageMarker.current?.remove();
        villageMarker.current = new maplibregl.Marker({ color: "#d8a23a" })
          .setLngLat([lon, lat])
          .setPopup(new maplibregl.Popup({ offset: 24 }).setText(t("map.youAreHere")))
          .addTo(m);
      },
      (err) => {
        setLocating(false);
        setLocateError(
          err.code === err.PERMISSION_DENIED
            ? t("map.locateDenied")
            : t("map.locateFailed"),
        );
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 },
    );
  }

  // ---- layered finder helpers ----
  const finderRef = useRef<HTMLDivElement>(null);

  function openFinder() {
    const opening = !finderOpen;
    setFinderOpen(opening);
    if (!statesList.length) {
      api.geoStates().then((r) => setStatesList(r.states)).catch(() => {});
    }
    // The finder panel opens beneath the map search; on a phone bring it into
    // view so the newly revealed steps aren't below the fold.
    if (opening) {
      requestAnimationFrame(() =>
        finderRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }),
      );
    }
  }

  function pickFinderState(s: string) {
    setFinderState(s); setFinderDistrict(""); setFinderResults(null);
    setDistrictsList([]);
    setVillagesList([]); setVillagesFailed(false); setFinderVillage(""); setVillageSuggest(false);
    setVillageIdx("");
    if (s) api.geoDistricts(s).then((r) => setDistrictsList(r.districts)).catch(() => {});
  }

  function pickFinderDistrict(d: string) {
    setFinderDistrict(d); setFinderResults(null);
    setFinderVillage(""); setVillageSuggest(false);
    setVillagesList([]); setVillagesFailed(false);
    setVillageIdx("");
    if (!d || !finderState) return;
    // fetch the district's village directory; first load can take a few
    // seconds (OSM Overpass), later loads are served from the API cache
    const reqId = ++villagesReq.current;
    setVillagesBusy(true);
    api.geoVillages(finderState, d)
      .then((r) => {
        if (villagesReq.current !== reqId) return;
        setVillagesList(r.villages);
        setVillagesFailed(!!r.error || r.villages.length === 0);
      })
      .catch(() => { if (villagesReq.current === reqId) { setVillagesList([]); setVillagesFailed(true); } })
      .finally(() => { if (villagesReq.current === reqId) setVillagesBusy(false); });
  }

  function pickVillage(v: GeoVillage) {
    setFinderVillage(v.name); setVillageSuggest(false); setFinderResults(null);
    const m = map.current;
    if (!m) return;
    // Drop/move a pin so the farmer can tell which settlement the map jumped
    // to before zooming further to their field.
    if (!villageMarker.current) {
      villageMarker.current = new maplibregl.Marker({ color: "#e2b13c" });
    }
    villageMarker.current.setLngLat([v.lon, v.lat]).addTo(m);
    m.flyTo({ center: [v.lon, v.lat], zoom: 15, ...FLY });
  }

  // Substring match first; then a consonant-skeleton pass so transliteration
  // variants still hit (farmer types "haidergarh", data says "Haidargarh").
  //
  // Memoised, and this matters: a big district is ~7,600 villages (Sitapur),
  // and as a bare expression this re-scanned the whole list on every render of
  // a component that re-renders on map moves. The `seen` membership test is a
  // Set for the same reason — Array.includes inside a filter made the fuzzy
  // pass quadratic over those 7,600 entries.
  const villageMatches = useMemo(() => {
    const strip = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    const q = strip(finderVillage.trim());
    const direct = villagesList.filter((v) => strip(v.name).includes(q));
    if (direct.length >= 40 || q.length < 3) return direct.slice(0, 40);
    const seen = new Set(direct);
    const skel = (s: string) => s.replace(/[^bcdfghjklmnpqrstvwxyz]/g, "");
    const qs = skel(q);
    const fuzzy = qs
      ? villagesList.filter((v) => !seen.has(v) && skel(strip(v.name)).includes(qs))
      : [];
    return [...direct, ...fuzzy].slice(0, 40);
  }, [villagesList, finderVillage]);

  // The dropdown lists a slice, not the whole district. Every <option> is a DOM
  // node built synchronously the moment a district resolves, so a 7,600-village
  // district froze the page for seconds on a control nobody can scroll usefully.
  // Past this many, the type-ahead below is the way to find a village.
  const villageOptions = useMemo(
    () => villagesList.slice(0, VILLAGE_SELECT_LIMIT),
    [villagesList],
  );

  async function finderGo(target?: string) {
    // search the village scoped to district+state; with no village, jump to
    // the district (or state) itself
    const q = (target ?? finderVillage).trim() || finderDistrict || finderState;
    if (!q) return;
    setFinderBusy(true);
    try {
      const r = await api.geoSearch(q, {
        state: finderState || undefined,
        district: q === finderDistrict ? undefined : (finderDistrict || undefined),
      });
      if (r.results.length === 1) gotoResult(r.results[0]);
      else setFinderResults(r.results);
    } catch {
      setFinderResults([]);
    } finally {
      setFinderBusy(false);
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
    setEconomics(null); setFetchedValidation(null); setDesign(null);
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
    map.current?.flyTo({ center: [manualPlace.lon, manualPlace.lat], zoom: 14, ...FLY });

    try {
      setBusy("Fetching soil & climate…");
      const report = await api.landReport(manualPlace.lat, manualPlace.lon).catch(() => null);
      setLand(report);
      api.elevation(manualPlace.lat, manualPlace.lon).then(setElevation).catch(() => setElevation(null));
      setBusy("Recommending crops…");
      const recRes = await api.recommend({
        ...siteCtx(report, parts.length ? parts[parts.length - 1] : undefined, water),
        system, limit: 8,
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
        selected.map((id) => api.plan(id, areaM2, system).catch(() => null)));
      setPlans(ps.filter((p): p is PlanResult => p !== null));
      api.economics(selected, areaM2, summary?.region?.state, system)
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
      // Fetch per-crop plans (planting material / fertiliser / calendar). The
      // plant count comes from the layout, so the seedlings/suckers to buy
      // match the positions drawn on the map.
      const areaM2 = summary?.area.square_meters ?? 0;
      const laidOut = new Map(res.crops.map((c) => [c.crop_id, c.plant_count]));
      const ps = await Promise.all(
        selected.map((id) => api.plan(id, areaM2, system, {
          plant_count: laidOut.get(id),
          perimeter_m: summary?.perimeter_meters || undefined,
        }).catch(() => null)));
      setPlans(ps.filter((p): p is PlanResult => p !== null));
      // Cost / revenue / profit estimate (mandi prices when available).
      const state = summary?.region?.state;
      api.economics(selected, areaM2, state, system).then(setEconomics).catch(() => setEconomics(null));
      if (map.current) {
        geoSource(map.current, "plants")?.setData(res.planting_points);
        const heatFC: GeoJSON.FeatureCollection = {
          type: "FeatureCollection",
          features: res.heatmap.cells.map((c) => ({
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
        geoSource(map.current, "heat")?.setData(heatFC);
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
      const blob = await api.reportPdf(geometry, selected, system);
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
        {/* Labelled so the finder and GPS are discoverable on a phone, where a
            title tooltip never shows. The row wraps on small screens. */}
        <button className={"map-btn" + (finderOpen ? "" : " secondary")}
          title={t("finder.title")} onClick={openFinder}>
          📍 <span>{t("map.finderBtn")}</span>
        </button>
        <button className="map-btn" disabled={locating}
          title={t("map.locateBtn")} onClick={locateMe}>
          🎯 <span>{locating ? t("map.locating") : t("map.locateBtn")}</span>
        </button>
        <button className={"map-btn" + (showLabels ? "" : " secondary")}
          title={t("map.labels")} onClick={() => setShowLabels((v) => !v)}>
          🏷️ <span>{t("map.labelsBtn")}</span>
        </button>
        {(locateError || locateAccuracy != null) && (
          <div className="map-note">
            {locateError ? (
              <span className="map-note-error">{locateError}</span>
            ) : (
              t("map.locateAccuracy", { n: Math.round(locateAccuracy as number) })
            )}
            <button className="map-note-close"
              onClick={() => { setLocateError(""); setLocateAccuracy(null); }}>✕</button>
          </div>
        )}
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

        {finderOpen && (
          <div className="finder-panel" ref={finderRef}>
            <p className="hint" style={{ fontWeight: 600, margin: "0 0 6px" }}>
              {t("finder.title")}
            </p>
            <select className="lang-select finder-select" value={finderState}
              onChange={(e) => pickFinderState(e.target.value)}>
              <option value="">{t("finder.state")}</option>
              {statesList.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select className="lang-select finder-select" value={finderDistrict}
              disabled={!finderState}
              onChange={(e) => pickFinderDistrict(e.target.value)}>
              <option value="">{t("finder.district")}</option>
              {districtsList.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            {villagesList.length > 0 && (
              <select className="lang-select finder-select" value={villageIdx}
                onChange={(e) => {
                  setVillageIdx(e.target.value);
                  const v = villagesList[Number(e.target.value)];
                  if (v) pickVillage(v);
                }}>
                <option value="">{t("finder.villagePick")}</option>
                {villageOptions.map((v, i) => (
                  <option key={`${v.name}:${v.lat}:${v.lon}`} value={i}>
                    {v.name}{v.kind === "town" ? " 🏙" : ""}
                  </option>
                ))}
                {villagesList.length > villageOptions.length && (
                  <option value="" disabled>
                    {t("finder.villageMore", {
                      n: villagesList.length - villageOptions.length,
                    })}
                  </option>
                )}
              </select>
            )}
            <div className="save-row" style={{ marginTop: 6 }}>
              <input className="input"
                placeholder={villagesList.length ? t("finder.typeInstead") : t("finder.village")}
                disabled={!finderState}
                value={finderVillage}
                onChange={(e) => { setFinderVillage(e.target.value); setVillageSuggest(true); setFinderResults(null); }}
                onFocus={() => { if (villagesList.length) setVillageSuggest(true); }}
                onKeyDown={(e) => { if (e.key === "Enter") { setVillageSuggest(false); finderGo(); } }} />
              <button className="btn btn-sm" disabled={finderBusy || !finderState}
                onClick={() => { setVillageSuggest(false); finderGo(); }}>
                {finderBusy ? "…" : t("finder.go")}
              </button>
            </div>
            {villagesBusy && (
              <p className="disclaimer" style={{ marginTop: 6 }}>{t("finder.loadingVillages")}</p>
            )}
            {!villagesBusy && villagesList.length > 0 && (
              <p className="disclaimer" style={{ marginTop: 6 }}>
                {t("finder.villageCount", { n: villagesList.length })}
              </p>
            )}
            {!villagesBusy && villagesFailed && finderDistrict !== "" && (
              <p className="disclaimer" style={{ marginTop: 6 }}>{t("finder.noVillageList")}</p>
            )}
            {villageSuggest && villageMatches.length > 0 && (
              <div className="manual-results village-list">
                {villageMatches.map((v) => (
                  <div className="map-search-item" key={v.name} onClick={() => pickVillage(v)}>
                    {v.name}
                    {v.kind && v.kind !== "village" && <span className="muted"> · {v.kind}</span>}
                  </div>
                ))}
              </div>
            )}
            {finderResults !== null && (
              <div className="manual-results">
                {finderResults.length === 0 && (
                  <div className="map-search-item muted">{t("map.noResults")}</div>
                )}
                {finderResults.map((r, i) => (
                  <div className="map-search-item" key={i} onClick={() => gotoResult(r)}>
                    {r.display_name}
                  </div>
                ))}
              </div>
            )}
            <p className="disclaimer" style={{ marginTop: 6 }}>{t("finder.hint")}</p>
          </div>
        )}
      </div>

      <aside className="sidebar">
        <div className="brand">
          <span className="leaf">🌱</span>
          <h1>SmartFarm</h1>
        </div>
        <p className="tagline">{t("brand.tagline")}</p>

        {serviceDown && (
          <div className="card" role="alert" style={{ borderColor: "#b45309" }}>
            <h3 style={{ color: "#b45309" }}>{t("planner.offlineTitle")}</h3>
            <p className="hint">{t("planner.offlineBody")}</p>
          </div>
        )}

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
                  onChange={(e) => setManualUnit(e.target.value as AreaUnit)}>
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
              <span className="v">{land.climate?.annual_rainfall_mm ?? "—"} mm ({land.climate?.rainfall_band || "—"})
                {land.climate?.annual_rainfall_normal_mm != null &&
                  ` · ${t("intel.rainNormal", { n: Math.round(land.climate.annual_rainfall_normal_mm) })}`}
              </span></div>
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

            <p className="hint" style={{ margin: "4px 0" }}>{t("method.water")}</p>
            <div className="sys-row">
              {(["irrigated", "rainfed", "unknown"] as const).map((w) => (
                <button key={w} className={"sys" + (water === w ? " active" : "")}
                  onClick={() => changeWater(w)}>
                  {t(`method.water_${w}`)}
                </button>
              ))}
            </div>

            <div className="tabs">
              <button className={"tab" + (cropTab === "recommended" ? " active" : "")}
                onClick={() => setCropTab("recommended")}>{t("method.tabRecommended")}</button>
              <button className={"tab" + (cropTab === "all" ? " active" : "")}
                onClick={() => setCropTab("all")}>{t("method.tabAll")}</button>
            </div>

            {cropTab === "recommended" && recs.map((r, i) => (
              <div key={r.crop_id}>
              {/* Expert-only crops follow the validated ranking, under a divider. */}
              {r.calibrated === false && recs[i - 1]?.calibrated !== false && (
                <p className="hint" style={{ margin: "8px 0 4px" }}>{t("method.expertGroup")}</p>
              )}
              <div
                className={"crop" + (selected.includes(r.crop_id) ? " selected" : "")}
                title={r.reasons.join("\n")}
                onClick={() => toggleCrop(r.crop_id)}>
                <span className="dot" style={{ background: LAYER_COLORS[r.layer] }} />
                <div>
                  <div className="name">{r.name}</div>
                  <div className="meta">
                    {r.layer} · {r.category}
                    {r.needs_irrigation && <span className="tag tag-water">💧 {t("method.needsIrrigation")}</span>}
                    {r.calibrated === false && <span className="tag tag-muted">{t("method.expertOnly")}</span>}
                  </div>
                </div>
                <span className={"badge " + badgeClass(r)}>
                  {r.suitability}
                </span>
              </div>
              </div>
            ))}
            {cropTab === "recommended" && recs.length > 0 && (
              <p className="disclaimer" style={{ marginTop: 4 }}>
                {recs.some((r) => r.calibrated !== undefined)
                  ? t("method.whyHint") : t("method.whyHintRules")}
              </p>
            )}

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
            {layout && (
              <p className="hint" style={{ margin: "4px 0 6px" }}>
                {t("layout.geoNote")}
                {layout.row_orientation_deg
                  ? " " + t("layout.rotated", { deg: Math.round(layout.row_orientation_deg) })
                  : ""}
              </p>
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
                      {p.crop.name} · {materialLine(p, t)} ·
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
            {economics.usable_fraction != null && economics.usable_fraction < 1 && (
              <p className="hint" style={{ marginTop: 6 }}>
                {t("profit.usableArea", {
                  pct: Math.round(economics.usable_fraction * 100),
                  planted: economics.planting_area_hectares ?? 0,
                })}
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

/** Soil, climate and place context for /agronomy/recommend, validate and design.
 *  Seasonal mean temperatures feed the calibrated recommender (the crop
 *  database's temperature ranges are growing-season means); the state enables
 *  its state-level prior; water toggles the rain-fed rainfall requirement. */
function siteCtx(report: any, state: string | undefined,
                 water: "unknown" | "irrigated" | "rainfed"): Record<string, unknown> {
  const c = report?.climate;
  return {
    ph: report?.soil?.ph ?? undefined,
    texture: report?.soil?.texture_class ?? undefined,
    // 10-year normal (what the recommender was trained on), else last year's total
    rainfall_mm: c?.annual_rainfall_normal_mm ?? c?.annual_rainfall_mm ?? undefined,
    temp_max_c: c?.temp_max_avg_c ?? undefined,
    tmean_kharif_c: c?.tmean_kharif_c ?? undefined,
    tmean_rabi_c: c?.tmean_rabi_c ?? undefined,
    tmean_zaid_c: c?.tmean_zaid_c ?? undefined,
    season: c?.season ?? undefined,
    state: state || undefined,
    irrigated: water === "irrigated" ? true : water === "rainfed" ? false : undefined,
  };
}

/** Badge colour: the calibrated model's own level, else the rule-score bands. */
function badgeClass(r: Recommendation): string {
  if (r.level) return r.level === "high" ? "high" : r.level === "ok" ? "ok" : "";
  return r.score >= 0.8 ? "high" : r.score >= 0.6 ? "ok" : "";
}

function inr(n: number): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}₹${Math.abs(Math.round(n)).toLocaleString("en-IN")}`;
}

/** "≈ 2,100 suckers" / "2,000 kg rhizomes" / "95 kg seed" for a crop plan. */
function materialLine(p: PlanResult, t: (k: string) => string): string {
  const m = p.planting_material;
  if (!m) return `${p.seed.quantity_kg} kg ${t("material.seed")}`;
  if (m.unit === "plants") {
    return `≈ ${Math.round(m.quantity).toLocaleString("en-IN")} ${t(`material.${m.type}`)}`;
  }
  return `${m.quantity} kg ${t(`material.${m.type}`)}`;
}

/** Typed accessor for the planner's GeoJSON overlays (draw/field/plants/heat).
 *  Returns undefined before the style has finished loading. */
function geoSource(m: maplibregl.Map, id: string): maplibregl.GeoJSONSource | undefined {
  return m.getSource(id) as maplibregl.GeoJSONSource | undefined;
}

function emptyFC(): GeoJSON.FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}

function fitToRing(m: maplibregl.Map, ring: number[][]) {
  if (!ring.length) return;
  const b = new maplibregl.LngLatBounds(
    [ring[0][0], ring[0][1]], [ring[0][0], ring[0][1]]);
  for (const [lng, lat] of ring) b.extend([lng, lat]);
  // no fixed duration/speed — they freeze long flights: see FLY in Planner()
  m.fitBounds(b, { padding: 60, maxDuration: 6000 });
}

function renderDraw(m: maplibregl.Map, verts: number[][]) {
  const features: GeoJSON.Feature[] = verts.map((c) => ({
    type: "Feature", geometry: { type: "Point", coordinates: c }, properties: {},
  }));
  if (verts.length >= 2) {
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates: verts },
      properties: {},
    });
  }
  geoSource(m, "draw")?.setData({ type: "FeatureCollection", features });
}
