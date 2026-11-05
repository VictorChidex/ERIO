"""Reference data every environment needs: countries and job sources.

Run after migrations with ``python -m erio_core.db.seed``. Safe to repeat:
rows are inserted or updated in place, never duplicated.
"""

import json
from importlib.resources import files
from typing import Any

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert

from erio_core.db.models import Country, Source
from erio_core.settings import Settings

# The six first-release ATS sources (decision D-04). They stay "scheduled"
# until their connector exists and legal review is recorded.
SOURCES = [
    {"slug": "greenhouse", "name": "Greenhouse", "kind": "ats"},
    {"slug": "lever", "name": "Lever", "kind": "ats"},
    {"slug": "ashby", "name": "Ashby", "kind": "ats"},
    {"slug": "smartrecruiters", "name": "SmartRecruiters", "kind": "ats"},
    {"slug": "recruitee", "name": "Recruitee", "kind": "ats"},
    {"slug": "workable", "name": "Workable", "kind": "ats"},
]


def load_countries() -> list[dict[str, Any]]:
    """The 233 countries the globe draws, from erio_core/data/countries.json."""
    raw = files("erio_core").joinpath("data/countries.json").read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = json.loads(raw)
    return rows


def sync_countries(engine: Engine) -> int:
    rows = [
        {key: row[key] for key in ("code", "name", "region", "subregion", "region_groups")}
        for row in load_countries()
    ]
    statement = insert(Country).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=[Country.code],
        set_={
            "name": statement.excluded.name,
            "region": statement.excluded.region,
            "subregion": statement.excluded.subregion,
            "region_groups": statement.excluded.region_groups,
        },
    )
    with engine.begin() as connection:
        connection.execute(statement)
    return len(rows)


def sync_sources(engine: Engine) -> int:
    statement = insert(Source).values(SOURCES)
    statement = statement.on_conflict_do_update(
        index_elements=[Source.slug],
        set_={"name": statement.excluded.name, "kind": statement.excluded.kind},
    )
    with engine.begin() as connection:
        connection.execute(statement)
    return len(SOURCES)


def seed(engine: Engine) -> dict[str, int]:
    sync_countries(engine)
    sync_sources(engine)
    with engine.connect() as connection:
        return {
            "countries": connection.scalar(select(func.count()).select_from(Country)) or 0,
            "sources": connection.scalar(select(func.count()).select_from(Source)) or 0,
        }


def main() -> None:
    engine = create_engine(Settings().sqlalchemy_url)
    try:
        counts = seed(engine)
    finally:
        engine.dispose()
    print(f"seeded {counts['countries']} countries and {counts['sources']} sources")


if __name__ == "__main__":
    main()
