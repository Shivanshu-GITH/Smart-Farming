"""Build the per-state village index from the GeoNames India dump.

Produces villages/<state-slug>.json.gz files, each:
    {"state": "<canonical name>", "source": "GeoNames (CC BY 4.0)",
     "villages": [[name, lat, lon, kind], ...]}   # kind: "v" village, "t" town

The API serves a district's villages by filtering a state file on the
district's bounding box (resolved once via Nominatim and cached), which keeps
working even for districts created after the GeoNames admin2 split.

Rebuild (data refresh):
    python build_villages.py --source-dir <dir with IN.txt + admin1CodesASCII.txt>
With no --source-dir the files are downloaded from download.geonames.org.

Data: GeoNames (https://www.geonames.org), licensed CC BY 4.0 — attribution
is kept in every generated file and surfaced by the API.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "villages"
DUMP_URL = "https://download.geonames.org/export/dump/IN.zip"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"

# GeoNames admin1 name -> our canonical name (states-districts.json) where
# a plain normalised comparison doesn't match.
STATE_ALIASES = {
    "andaman and nicobar": "Andaman and Nicobar Islands",
}

# Populated places that no longer exist don't belong in a farmer's finder.
EXCLUDED_FCODES = {"PPLH", "PPLQ", "PPLW", "PPLCH"}
# Administrative seats get flagged as towns so the UI can hint at them.
TOWN_FCODES = {"PPLC", "PPLA", "PPLA2", "PPLA3", "PPLA4"}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def load_sources(source_dir: Path | None) -> tuple[list[str], list[str]]:
    if source_dir:
        in_txt = (source_dir / "IN.txt").read_text(encoding="utf-8").splitlines()
        admin1 = (source_dir / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines()
        return in_txt, admin1
    print("downloading", DUMP_URL)
    with urllib.request.urlopen(DUMP_URL) as resp:
        zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    in_txt = zf.read("IN.txt").decode("utf-8").splitlines()
    print("downloading", ADMIN1_URL)
    with urllib.request.urlopen(ADMIN1_URL) as resp:
        admin1 = resp.read().decode("utf-8").splitlines()
    return in_txt, admin1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", type=Path, default=None,
                    help="dir containing IN.txt and admin1CodesASCII.txt")
    args = ap.parse_args()

    ours = json.loads((HERE / "states-districts.json").read_text(encoding="utf-8"))
    canonical = {norm(s["name"]): s["name"] for s in ours["states"]}
    for alias, name in STATE_ALIASES.items():
        canonical[norm(alias)] = name

    in_txt, admin1 = load_sources(args.source_dir)

    # GeoNames admin1 code ('36') -> our canonical state name
    code_to_state: dict[str, str] = {}
    for line in admin1:
        f = line.rstrip("\n").split("\t")
        if not f[0].startswith("IN."):
            continue
        code = f[0].split(".")[1]
        state = canonical.get(norm(f[2]))
        if state is None:
            print(f"!! geonames state not matched, skipped: {f[2]}")
            continue
        code_to_state[code] = state

    # state -> {(name, coarse lat, coarse lon) -> [name, lat, lon, kind]}
    by_state: dict[str, dict] = {s["name"]: {} for s in ours["states"]}
    kept = 0
    for line in in_txt:
        f = line.rstrip("\n").split("\t")
        if f[6] != "P" or f[7] in EXCLUDED_FCODES:
            continue
        state = code_to_state.get(f[10])
        name = f[2].strip() or f[1].strip()  # asciiname, fall back to name
        if state is None or not name:
            continue
        lat, lon = round(float(f[4]), 5), round(float(f[5]), 5)
        # Same-named *distinct* villages are real (many Rampurs per district) —
        # only collapse true duplicates: same name within ~1 km.
        key = (name.lower(), round(lat, 2), round(lon, 2))
        if key in by_state[state]:
            continue
        kind = "t" if f[7] in TOWN_FCODES else "v"
        by_state[state][key] = [name, lat, lon, kind]
        kept += 1

    OUT_DIR.mkdir(exist_ok=True)
    for state, entries in sorted(by_state.items()):
        villages = sorted(entries.values(), key=lambda v: (v[0].lower(), v[1]))
        out = {"state": state, "source": "GeoNames (CC BY 4.0)", "villages": villages}
        path = OUT_DIR / f"{slug(state)}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
        print(f"{state:45s} {len(villages):>7,} places  -> {path.name}")
    print(f"total: {kept:,} places")


if __name__ == "__main__":
    main()
