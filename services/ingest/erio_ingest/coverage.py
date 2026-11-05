"""Platform coverage: the 78 platforms of the acquisition brief, and proof that
each connector works on live boards.

``verify`` fetches every example board of a platform through the polite
fetcher (host allow-list, robots.txt, rate limits), parses and normalizes
every job, and records the result in ``docs/coverage/results.json``.
``report`` turns the registry and those results into ``docs/coverage.md``,
the coverage checklist. ``--record`` also saves three real jobs per platform
as contract-test fixtures.

    python -m erio_ingest.coverage verify pinpoint teamtailor   # or: verify --all
    python -m erio_ingest.coverage report
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from redis import Redis

from erio_core.connectors import CONNECTORS, FetchError
from erio_core.normalize.job import normalize
from erio_core.settings import get_settings
from erio_ingest.fetcher import PoliteFetcher
from erio_ingest.ratelimit import HostRateLimiter

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "docs" / "coverage" / "results.json"
CHECKLIST = ROOT / "docs" / "coverage.md"
FIXTURES = ROOT / "fixtures" / "coverage"
SAMPLES = 3


def platforms() -> list[dict[str, Any]]:
    """The registry: erio_core/data/platforms.json."""
    raw = files("erio_core").joinpath("data/platforms.json").read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = json.loads(raw)
    return rows


@dataclass
class BoardResult:
    board: str
    ok: bool
    jobs: int = 0
    parsed: int = 0
    error: str = ""
    sample_titles: list[str] = field(default_factory=list)


def verify_board(fetcher: PoliteFetcher, slug: str, token: str) -> tuple[BoardResult, list[Any]]:
    connector = CONNECTORS[slug]
    try:
        postings = connector.list_postings(fetcher, token).postings
    except (FetchError, ValueError) as error:
        return BoardResult(token, ok=False, error=str(error)[:300]), []
    parsed, failures = [], []
    for raw in postings:
        try:
            normalize(connector.parse(raw), {})
            parsed.append(raw)
        except Exception as error:  # noqa: BLE001 (every failure is reported, none hidden)
            failures.append(f"{raw.external_id}: {type(error).__name__}: {error}"[:200])
    result = BoardResult(
        board=token,
        ok=bool(parsed) and not failures,
        jobs=len(postings),
        parsed=len(parsed),
        error="; ".join(failures[:3]),
        sample_titles=[connector.parse(raw).title for raw in parsed[:SAMPLES]],
    )
    return result, parsed[:SAMPLES]


def fetcher_for(examples: dict[str, list[str]]) -> PoliteFetcher:
    settings = get_settings()
    hosts = {host for connector in CONNECTORS.values() for host in connector.hosts}
    board_hosts = {
        urlsplit(token).hostname or ""
        for tokens in examples.values()
        for token in tokens
        if token.startswith("https://")
    }
    limiter = HostRateLimiter(Redis.from_url(settings.redis_url), settings.crawl_rate_per_host)
    return PoliteFetcher(hosts | board_hosts, limiter, settings)


def verify(slugs: list[str], record: bool) -> dict[str, Any]:
    registry = {row["slug"]: row for row in platforms()}
    results: dict[str, Any] = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    fetcher = fetcher_for({s: registry[s]["examples"] for s in slugs})
    for slug in slugs:
        row = registry[slug]
        if slug not in CONNECTORS or not row["examples"]:
            print(f"{slug}: no connector or no example boards yet")
            continue
        boards = []
        for token in row["examples"]:
            result, samples = verify_board(fetcher, slug, token)
            boards.append(asdict(result))
            state = "ok" if result.ok else "FAILED"
            print(f"{slug:18} {token[:60]:60} {state:6} {result.parsed}/{result.jobs} {result.error[:120]}")
            if record and samples:
                FIXTURES.mkdir(parents=True, exist_ok=True)
                path = FIXTURES / f"{slug}.json"
                path.write_text(
                    json.dumps([s.model_dump(mode="json") for s in samples], indent=1, ensure_ascii=False)
                    + "\n",
                    encoding="utf-8",
                )
        results[slug] = {"checked_at": datetime.now(UTC).isoformat(timespec="seconds"), "boards": boards}
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return results


STATUS = {
    "live": "Live", "partial": "Partial", "blocked": "Blocked", "planned": "Not built yet",
}  # fmt: skip


def report() -> str:
    results: dict[str, Any] = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    rows = platforms()
    lines = [
        "# Platform coverage",
        "",
        "The 58 applicant tracking systems and 20 job-board platforms the brief requires.",
        "Generated by `python -m erio_ingest.coverage report` from",
        "`erio_core/data/platforms.json` and the live runs in `docs/coverage/results.json`",
        "(`python -m erio_ingest.coverage verify`). A platform counts as covered only when a",
        "live run on two or more of its boards indexed jobs.",
        "",
    ]
    for kind, title in (("ats", "Applicant tracking systems"), ("board", "Job-board platforms")):
        group = [r for r in rows if r["kind"] == kind]
        verified = sum(
            1 for r in group
            if sum(b["ok"] for b in results.get(r["slug"], {}).get("boards", [])) >= 2
        )  # fmt: skip
        lines += [
            f"## {title}: {verified} of {len(group)} verified on two or more live boards",
            "",
            "| Platform | Status | Live run | Boards (jobs indexed) | Notes |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in group:
            run = results.get(row["slug"])
            boards = (run or {}).get("boards", [])
            shown = ", ".join(
                f"`{b['board'][:48]}` ({b['parsed']})" if b["ok"] else f"`{b['board'][:48]}` (failed)"
                for b in boards
            ) or "—"
            checked = run["checked_at"][:10] if run else "—"
            lines.append(
                f"| {row['name']} | {STATUS[row['status']]} | {checked} | {shown} | {row['notes']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Platform coverage: verify connectors live")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify")
    check.add_argument("slugs", nargs="*")
    check.add_argument("--all", action="store_true")
    check.add_argument("--record", action="store_true", help="save sample jobs as fixtures")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "verify":
        slugs = [r["slug"] for r in platforms() if r["slug"] in CONNECTORS] if args.all else args.slugs
        if not slugs:
            sys.exit("name platforms to verify, or --all")
        verify(slugs, args.record)
    CHECKLIST.write_text(report() + "\n", encoding="utf-8")
    print(f"wrote {CHECKLIST}")


if __name__ == "__main__":
    main()
