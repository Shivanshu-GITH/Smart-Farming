# india-geo

Bundled place data that powers the layered location finder
(state → district → village) in the SmartFarm API (`/geo/*`).

## Files

- `states-districts.json` — 36 states/UTs with their districts (indicative,
  hand-maintained; districts change occasionally — update as notified).
- `villages/<state>.json.gz` — ~550,000 populated places (villages, towns,
  hamlets) with coordinates, one gzipped JSON file per state. Entry format:
  `[name, lat, lon, kind]` where kind is `"v"` (village) or `"t"` (town /
  administrative seat). Served by `GET /geo/villages?state=&district=`,
  filtered by the district's bounding box.
- `build_villages.py` — regenerates the `villages/` files from the GeoNames
  dump. Run `python build_villages.py` (downloads ~16 MB) whenever a data
  refresh is wanted.
- `district-bboxes.json` — one bounding box `[south, north, west, east]` per
  district, so `/geo/villages` can slice a state's village file per district
  with **no live geocoding call** (works offline / when Nominatim is
  unreachable). Districts absent from this file fall back to a cached
  Nominatim lookup at runtime.
- `build_district_bboxes.py` — regenerates `district-bboxes.json` from OSM
  Nominatim (1 request/second per their usage policy, ~15 min for all 779
  districts). Resumable: re-running only fetches districts still missing, so
  run it again after adding new districts to `states-districts.json`.

## Data source & licence

Village data: [GeoNames](https://www.geonames.org) (`IN.zip` +
`admin1CodesASCII.txt`), licensed **CC BY 4.0**. Attribution is embedded in
every generated file and returned in the API response (`"source"` field).
Same-named villages within a district are real and are kept (only true
duplicates — same name within ~1 km — are collapsed).

District bounding boxes: © OpenStreetMap contributors via
[Nominatim](https://nominatim.org), licensed **ODbL**.
