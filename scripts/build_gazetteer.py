"""Build the offline gazetteer the normalizer resolves locations with.

Source: GeoNames (https://www.geonames.org, CC BY 4.0): cities15000 (every
city with at least 15,000 people) and admin1CodesASCII (states, provinces).
GeoNames updates daily, so the output records the download date.

    uv run python scripts/build_gazetteer.py

Writes packages/core/erio_core/data/gazetteer.json.gz:
    {"source": ..., "admin1": {"US.CA": "California", ...},
     "cities": [[name, other_names, country, admin1, lat, lon, population], ...]}
"""

import csv
import gzip
import io
import json
import re
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "packages" / "core" / "erio_core" / "data" / "gazetteer.json.gz"
BASE = "https://download.geonames.org/export/dump"

# Alternate names are kept only for bigger cities, where job ads use them
# ("Bangalore" for Bengaluru), and only in Latin script.
ALT_NAMES_MIN_POPULATION = 100_000
LATIN_NAME = re.compile(r"^[A-Z][A-Za-z .'\-]{2,39}$")


def download(name: str) -> bytes:
    url = f"{BASE}/{name}"
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 (fixed https host)
        return bytes(response.read())


def main() -> None:
    admin1 = {}
    for row in csv.reader(
        io.StringIO(download("admin1CodesASCII.txt").decode("utf-8")), delimiter="\t"
    ):
        admin1[row[0]] = row[2]  # code -> ASCII name

    archive = zipfile.ZipFile(io.BytesIO(download("cities15000.zip")))
    text = archive.read("cities15000.txt").decode("utf-8")
    cities = []
    for row in csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        name, ascii_name, alternates = row[1], row[2], row[3]
        country, admin_code, population = row[8], row[10], int(row[14] or 0)
        names = {ascii_name} - {name}
        if population >= ALT_NAMES_MIN_POPULATION:
            # All-capital alternates are mostly airport codes (BLR, NBO); skip them.
            names |= {n for n in alternates.split(",") if LATIN_NAME.match(n) and not n.isupper()}
        names.discard(name)
        cities.append(
            [
                name,
                sorted(names),
                country,
                admin_code,
                round(float(row[4]), 3),
                round(float(row[5]), 3),
                population,
            ]
        )
    cities.sort(key=lambda city: -int(city[6]))

    data = {
        "source": f"GeoNames cities15000 and admin1CodesASCII (CC BY 4.0), "
        f"downloaded {datetime.now(UTC):%Y-%m-%d}",
        "admin1": admin1,
        "cities": cities,
    }
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    OUTPUT.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    print(f"wrote {len(cities)} cities, {len(admin1)} regions, {OUTPUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
