"""Coverage report for the step 7 targets: ``python -m erio_ingest.report``.

Prints, per source, the fetch success rate over the last few days and the
latest smoke test, then the boards tracked and the countries with local
(non-worldwide) open listings.
"""

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, case, create_engine, func, select
from sqlalchemy.orm import Session

from erio_core.db.models import CompanyBoard, CrawlRun, Job, Source, SourceCheck
from erio_core.settings import get_settings


@dataclass(frozen=True)
class SourceLine:
    source: str
    status: str
    boards: int
    runs: int
    ok_runs: int
    smoke_ok: bool | None

    @property
    def success(self) -> float | None:
        return self.ok_runs / self.runs if self.runs else None


@dataclass(frozen=True)
class Coverage:
    sources: list[SourceLine]
    boards: int
    local_countries: int


def coverage(engine: Engine, since: datetime) -> Coverage:
    with Session(engine) as session:
        # Results have .keys(), so dict() would read them as mappings: unpack rows.
        boards = {
            slug: count
            for slug, count in session.execute(
                select(CompanyBoard.source_slug, func.count()).group_by(CompanyBoard.source_slug)
            ).tuples()
        }
        runs = {
            slug: (total, ok)
            for slug, total, ok in session.execute(
                select(
                    CompanyBoard.source_slug,
                    func.count(),
                    func.sum(case((CrawlRun.outcome == "ok", 1), else_=0)),
                )
                .join(CompanyBoard, CompanyBoard.id == CrawlRun.board_id)
                .where(CrawlRun.started_at >= since)
                .group_by(CompanyBoard.source_slug)
            ).tuples()
        }
        latest = (
            select(SourceCheck.source_slug, SourceCheck.ok)
            .distinct(SourceCheck.source_slug)
            .order_by(SourceCheck.source_slug, SourceCheck.checked_at.desc())
        )
        smoke = {slug: ok for slug, ok in session.execute(latest).tuples()}
        lines = [
            SourceLine(slug, status, boards.get(slug, 0), *runs.get(slug, (0, 0)), smoke.get(slug))
            for slug, status in session.execute(
                select(Source.slug, Source.status).order_by(Source.slug)
            ).tuples()
        ]
        local = session.scalar(
            select(func.count(func.distinct(Job.country_code))).where(
                Job.status == "open", Job.country_code.is_not(None)
            )
        )
    return Coverage(lines, sum(boards.values()), local or 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=3)
    days = parser.parse_args().days
    engine = create_engine(get_settings().sqlalchemy_url)
    try:
        report = coverage(engine, datetime.now(UTC) - timedelta(days=days))
    finally:
        engine.dispose()
    print(f"{'source':<16}{'status':<11}{'boards':>7}{'runs':>7}  success ({days}d)  smoke")
    for line in report.sources:
        rate = f"{line.success:.1%}" if line.success is not None else "-"
        smoke = {True: "ok", False: "FAIL", None: "-"}[line.smoke_ok]
        print(
            f"{line.source:<16}{line.status:<11}{line.boards:>7}{line.runs:>7}  {rate:>13}  {smoke}"
        )
    print(f"\nboards tracked: {report.boards} (target 3,000)")
    print(f"countries with local listings: {report.local_countries} (target 40)")


if __name__ == "__main__":
    main()
