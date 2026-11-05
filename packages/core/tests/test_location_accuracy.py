"""Country resolution against the labeled set (spec section 6: at least 97%)."""

import csv
from pathlib import Path

from erio_core.normalize.gazetteer import gazetteer
from erio_core.normalize.location import LocationResult, resolve_location

LABELED = Path(__file__).resolve().parents[3] / "fixtures" / "labeled" / "locations.tsv"
COUNTRY_GATE = 0.97
WORK_TYPE_GATE = 0.95


def load() -> list[dict[str, str]]:
    lines = [
        line
        for line in LABELED.read_text(encoding="utf-8").splitlines()
        if not line.startswith("#")
    ]
    return list(csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE))


def expected_countries(label: str) -> frozenset[str]:
    if label.startswith("@"):
        group = label[1:]
        return frozenset(
            c for c, info in gazetteer().countries.items() if group in info.region_groups
        )
    return frozenset(label.split(","))


def predicted_countries(result: LocationResult) -> frozenset[str]:
    if result.review_reason:
        return frozenset({"REVIEW"})
    if result.remote_scope == "worldwide":
        return frozenset({"WORLDWIDE"})
    codes = set(result.eligible_country_codes)
    if result.country_code:
        codes.add(result.country_code)
    return frozenset(codes)


def score() -> tuple[float, float, list[str]]:
    rows = load()
    country_ok = work_ok = 0
    misses = []
    for row in rows:
        result = resolve_location(row["text"])
        expected, got = expected_countries(row["countries"]), predicted_countries(result)
        country_ok += expected == got
        work_ok += row["work_type"] == result.remote_status
        if expected != got or row["work_type"] != result.remote_status:
            misses.append(
                f"{row['text']!r}: expected {sorted(expected)[:6]} {row['work_type']}, "
                f"got {sorted(got)[:6]} {result.remote_status}"
            )
    return country_ok / len(rows), work_ok / len(rows), misses


def test_labeled_set_is_large_and_varied() -> None:
    rows = load()
    assert len(rows) >= 300
    continents = {
        gazetteer().countries[code].region_groups
        for row in rows
        for code in row["countries"].split(",")
        if code in gazetteer().countries
    }
    regions = {g for groups in continents for g in groups}
    assert {"AFRICA", "EUROPE", "LATAM", "APAC", "NORTH_AMERICA"} <= regions


def test_country_accuracy_meets_the_gate() -> None:
    country, _, misses = score()
    assert country >= COUNTRY_GATE, f"country accuracy {country:.1%}; misses:\n" + "\n".join(misses)


def test_work_type_accuracy_meets_the_gate() -> None:
    _, work_type, misses = score()
    assert work_type >= WORK_TYPE_GATE, f"work type accuracy {work_type:.1%}:\n" + "\n".join(misses)
