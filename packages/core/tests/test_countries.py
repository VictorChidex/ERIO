"""The countries ERIO filters by must be exactly the ones the globe draws."""

import json
from pathlib import Path

from sqlalchemy import Engine, select

from erio_core.db.models import Company, Country, Source
from erio_core.db.seed import load_companies, load_countries, seed

WORLD = Path(__file__).resolve().parents[3] / "web" / "public" / "geo" / "world.json"


def _globe_names() -> list[str]:
    geometries = json.loads(WORLD.read_text(encoding="utf-8"))["objects"]["countries"]["geometries"]
    return [geometry["properties"]["n"] for geometry in geometries]


def test_seed_file_matches_the_globe_exactly() -> None:
    globe = _globe_names()
    seeded = [row["name"] for row in load_countries()]

    assert len(globe) == 233
    assert sorted(seeded) == sorted(globe)


def test_codes_are_unique_two_letter_codes() -> None:
    codes = [row["code"] for row in load_countries()]

    assert len(set(codes)) == len(codes) == 233
    assert all(len(code) == 2 and code.isupper() for code in codes)


def test_region_groups() -> None:
    groups = {row["code"]: set(row["region_groups"]) for row in load_countries()}

    assert {"AFRICA", "EMEA"} <= groups["NG"]
    assert {"EU", "EUROPE", "EMEA"} <= groups["DE"]
    assert {"LATAM", "NORTH_AMERICA"} <= groups["MX"]
    assert "APAC" in groups["IN"]
    assert "LATAM" not in groups["US"]
    assert "EU" not in groups["GB"]
    assert sum("EU" in g for g in groups.values()) == 27


# 30 starter boards, and 84 companies: the 57 in the seed list plus the
# board companies not in it.
SEEDED = {"countries": 233, "sources": 6, "companies": 84, "boards": 30}


def test_seed_loads_countries_and_sources(migrated_engine: Engine) -> None:
    assert seed(migrated_engine) == SEEDED

    with migrated_engine.connect() as connection:
        names = set(connection.scalars(select(Country.name)))
        nigeria = connection.execute(select(Country).where(Country.code == "NG")).one()
        statuses = set(connection.scalars(select(Source.status)))

    assert names == set(_globe_names())
    assert nigeria.region == "Africa"
    assert statuses == {"scheduled", "paused"}  # SmartRecruiters waits (robots.txt)


def test_seed_can_run_again(migrated_engine: Engine) -> None:
    seed(migrated_engine)
    assert seed(migrated_engine) == SEEDED


def test_seed_list_gives_every_company_a_known_home_country(migrated_engine: Engine) -> None:
    seed(migrated_engine)
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            select(Company.domain, Company.country_code).where(
                Company.domain.in_([row["domain"] for row in load_companies()])
            )
        )
        homes = {domain: code for domain, code in rows}
    assert len(homes) == len(load_companies())
    assert homes["kavak.com"] == "MX"  # a board company gains its home from the list
    assert all(homes.values())
