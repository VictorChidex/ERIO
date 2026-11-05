"""Build the country seed file from the globe's map data.

The 233 countries are exactly the ones the globe draws
(web/public/geo/world.json), with the globe's names. ISO alpha-2 codes,
regions and subregions come from the mledoze/countries dataset (ODbL 1.0),
pinned to one commit and checked by hash. Re-run only when the map changes:

    uv run python scripts/build_countries.py
"""

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD = ROOT / "web" / "public" / "geo" / "world.json"
OUTPUT = ROOT / "packages" / "core" / "erio_core" / "data" / "countries.json"

DATASET_URL = (
    "https://raw.githubusercontent.com/mledoze/countries/"
    "35c2a24a1e5b3ed9b2f6102297cf50bd96f9a39c/countries.json"
)
DATASET_SHA256 = "5781d027d65a98e29351eb8af89ca5bfeea5779c7e31d6ef26ecf0fcc9dd5065"

# Map entries without an ISO 3166-1 code get codes from the user-assigned
# range (XA-XZ). XK is the code the EU and IMF already use for Kosovo.
UNASSIGNED = {
    "Kosovo": ("XK", "Europe", "Southeast Europe"),
    "Somaliland": ("XS", "Africa", "Eastern Africa"),
    "Northern Cyprus": ("XN", "Europe", "Southern Europe"),
}

EU = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
}  # fmt: skip
NORTH_AMERICA = {"US", "CA", "MX"}
NOT_LATAM = {"US", "CA", "GL", "BM", "PM"}
APAC_SUBREGIONS = {
    "Eastern Asia",
    "South-Eastern Asia",
    "Southern Asia",
    "Australia and New Zealand",
    "Melanesia",
    "Micronesia",
    "Polynesia",
}


def region_groups(code: str, region: str, subregion: str) -> list[str]:
    """Region phrases a remote job can name, used to fill eligible countries."""
    groups = []
    if code in EU:
        groups.append("EU")
    if region == "Europe":
        groups.append("EUROPE")
    if region == "Africa":
        groups.append("AFRICA")
    if region in {"Europe", "Africa"} or subregion == "Western Asia":
        groups.append("EMEA")
    if region == "Americas" and code not in NOT_LATAM:
        groups.append("LATAM")
    if code in NORTH_AMERICA:
        groups.append("NORTH_AMERICA")
    if subregion in APAC_SUBREGIONS:
        groups.append("APAC")
    return groups


def load_dataset() -> list[dict[str, object]]:
    with urllib.request.urlopen(DATASET_URL, timeout=30) as response:
        raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != DATASET_SHA256:
        raise SystemExit(f"country dataset hash mismatch: {digest}")
    data: list[dict[str, object]] = json.loads(raw)
    return data


def main() -> None:
    geometries = json.loads(WORLD.read_text(encoding="utf-8"))["objects"]["countries"]["geometries"]
    by_numeric = {str(c["ccn3"]): c for c in load_dataset() if c.get("ccn3")}

    rows = []
    for geometry in geometries:
        name = geometry["properties"]["n"]
        lon, lat = geometry["properties"]["ll"]
        if name in UNASSIGNED:
            code, region, subregion = UNASSIGNED[name]
            numeric = None
        else:
            entry = by_numeric[geometry["id"]]
            code = str(entry["cca2"])
            region, subregion = str(entry["region"]), str(entry.get("subregion") or "")
            numeric = geometry["id"]
        rows.append(
            {
                "code": code,
                "numeric": numeric,
                "name": name,
                "region": region,
                "subregion": subregion or None,
                "region_groups": region_groups(code, region, subregion),
                # The globe's label point for the country, used when a job
                # names a country but no city.
                "lat": lat,
                "lon": lon,
            }
        )

    rows.sort(key=lambda row: row["code"])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(rows, ensure_ascii=False, indent=1) + "\n"
    OUTPUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(rows)} countries to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
