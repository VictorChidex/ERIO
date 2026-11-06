"""Reference data every environment needs: countries, job sources and the
companies ERIO tracks.

Run after migrations with ``python -m erio_core.db.seed``. Safe to repeat:
rows are inserted or updated in place, never duplicated.
"""

import csv
import io
import json
from importlib.resources import files
from typing import Any

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert

from erio_core.db.models import Company, CompanyBoard, Country, Source
from erio_core.settings import Settings


def platform_sources() -> list[dict[str, str]]:
    """One source per platform that has a connector (erio_core/data/platforms.json
    lists the 78 platforms of the coverage brief). A platform whose robots.txt
    turns crawlers away starts "paused"; the rest start "scheduled" until legal
    review is recorded. The status is set only when a source is first added;
    after that it is changed by hand, never by the seed."""
    from erio_core.connectors import CONNECTORS

    raw = files("erio_core").joinpath("data/platforms.json").read_text(encoding="utf-8")
    return [
        {
            "slug": row["slug"],
            "name": row["name"],
            "kind": row["kind"],
            "status": "paused" if row["blocked"] else "scheduled",
        }
        for row in json.loads(raw)
        if row["slug"] in CONNECTORS
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
    sources = platform_sources()
    statement = insert(Source).values(sources)
    statement = statement.on_conflict_do_update(
        index_elements=[Source.slug],
        set_={"name": statement.excluded.name, "kind": statement.excluded.kind},
    )
    with engine.begin() as connection:
        connection.execute(statement)
    return len(sources)


def load_boards() -> list[dict[str, str]]:
    """Starter company boards (erio_core/data/boards.json) until the seed list
    from decision D-07 arrives."""
    raw = files("erio_core").joinpath("data/boards.json").read_text(encoding="utf-8")
    rows: list[dict[str, str]] = json.loads(raw)
    return rows


def sync_boards(engine: Engine) -> int:
    """Add any listed company and board that is missing; never removes one."""
    with engine.begin() as connection:
        for row in load_boards():
            company_id = connection.scalar(
                select(Company.id).where(Company.domain == row["domain"])
            ) or connection.scalar(
                insert(Company)
                .values(name=row["company"], domain=row["domain"])
                .returning(Company.id)
            )
            connection.execute(
                insert(CompanyBoard)
                .values(
                    company_id=company_id,
                    source_slug=row["source"],
                    board_token=row["board_token"],
                )
                .on_conflict_do_nothing(index_elements=["source_slug", "board_token"])
            )
    return len(load_boards())


def load_companies() -> list[dict[str, str]]:
    """The company seed list (erio_core/data/companies.csv, decision D-07):
    name, domain and home country. Discovery finds their boards."""
    raw = files("erio_core").joinpath("data/companies.csv").read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(raw)))


def sync_companies(engine: Engine) -> int:
    """Add any listed company that is missing and fill in its home country."""
    rows = [
        {"name": row["name"], "domain": row["domain"], "country_code": row["country_code"] or None}
        for row in load_companies()
    ]
    statement = insert(Company).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=[Company.domain],
        set_={"country_code": func.coalesce(Company.country_code, statement.excluded.country_code)},
    )
    with engine.begin() as connection:
        connection.execute(statement)
    return len(rows)


def seed(engine: Engine) -> dict[str, int]:
    sync_countries(engine)
    sync_sources(engine)
    sync_boards(engine)
    sync_companies(engine)
    with engine.connect() as connection:
        return {
            "countries": connection.scalar(select(func.count()).select_from(Country)) or 0,
            "sources": connection.scalar(select(func.count()).select_from(Source)) or 0,
            "companies": connection.scalar(select(func.count()).select_from(Company)) or 0,
            "boards": connection.scalar(select(func.count()).select_from(CompanyBoard)) or 0,
        }


def main() -> None:
    engine = create_engine(Settings().sqlalchemy_url)
    try:
        counts = seed(engine)
    finally:
        engine.dispose()
    print(
        f"seeded {counts['countries']} countries, {counts['sources']} sources,"
        f" {counts['companies']} companies and {counts['boards']} boards"
    )


if __name__ == "__main__":
    main()
