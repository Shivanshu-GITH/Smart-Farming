# SmartFarm — Architecture

## High-level flow
```
Farmer → draws polygon on satellite map (web)
      → API computes geometry (area/perimeter/centroid/region)
      → API fetches land intelligence (soil via SoilGrids, NDVI via Sentinel, weather)
      → Farmer selects crop(s) + farming style (1 / 2 / multi / 5-layer)
      → API generates agronomic plan (seed rate, fertilizer schedule, calendar, plant count)
      → API generates spatial planting layout (per-plant points clipped to polygon) + heatmap
      → Farmer exports plan (PDF/GeoJSON)
```

## Backend modules (`apps/api/app`)
| Module | Responsibility |
|---|---|
| `fields` | Polygon geometry: area, perimeter, centroid, bbox, reverse-geocoded region |
| `land_intel` | Adapters for soil (SoilGrids), vegetation (NDVI), weather/agro-climate |
| `agronomy` | Crop suitability + recommendation, seed/fertilizer plan, crop calendar |
| `layout` | Plant-placement engine (single & multi-layer) + suitability heatmap grid |
| `advisory` | Claude-powered Q&A / plan explanation (later) |
| `core` | config, caching, geo helpers, (optional) DB session |

## Key design rules
- **Modular monolith first** — one FastAPI app, clean modules. Split to services only if needed.
- **Stateless compute runs without a DB.** Persistence is optional and turns on when
  `DATABASE_URL` (Postgres+PostGIS) is set.
- **Cache aggressively** by geohash — SoilGrids is rate-limited (5 calls/min). Redis in prod,
  in-process LRU fallback in dev.
- **Data is guidance, not lab-grade.** Soil/satellite come from global 250m datasets. Always
  labelled as estimates. Agronomy advice needs agronomist review before production.
- **Integration-ready** — standalone app, clean REST, shareable token auth, no hardcoded
  domain, so it drops into the Kadapala Groups site (subdomain + SSO) later.

## External data sources
- **Soil:** SoilGrids v2.0 REST — `https://rest.isric.org/soilgrids/v2.0/properties/query`
- **Vegetation/land cover:** Sentinel Hub or Google Earth Engine (Sentinel-2 NDVI)
- **Weather/climate:** Open-Meteo (free) / OpenWeather
- **Geocoding (region):** Nominatim / Mapbox
- **Elevation/slope:** Open-Elevation / SRTM DEM
- **Market prices (Phase 3):** Agmarknet / data.gov.in

## Roadmap
- **Phase 0 — Foundation:** repo, map+draw+area+region, API skeleton. *(in progress)*
- **Phase 1 — MVP:** soil+NDVI+weather reports, rules-based crop recommend, agronomic plan,
  plant count, basic layout map, PDF export.
- **Phase 2 — Differentiator:** multi-layer/5-layer design engine, advanced layout+heatmap,
  crop calendar + reminders, Claude advisory, cost/profit estimator.
- **Phase 3 — Platform:** marketplace / govt-scheme / mandi links, time-series monitoring,
  pest ID from photo, admin analytics, full Kadapala integration.
