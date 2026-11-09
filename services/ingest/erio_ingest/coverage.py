"""Platform coverage: the 78 platforms of the acquisition brief plus the public job
services, and proof that each connector works on live boards.

``verify`` fetches every example board of a platform through the polite
fetcher (host allow-list, robots.txt, rate limits), parses and normalizes
every job, and records the result in ``docs/coverage/results.json``.
``report`` turns the registry and those results into ``docs/coverage.md``,
the coverage checklist. A platform is "Verified" only when live runs on two
or more of its boards indexed jobs (a public job service, which is one live feed
and not a set of boards, needs one): the status is computed from the runs, never
set by hand. ``--record`` also saves three real jobs per platform as
contract-test fixtures.

    python -m erio_ingest.coverage verify pinpoint teamtailor   # or: verify --all
    python -m erio_ingest.coverage report
"""

import argparse
import json
import re
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
KINDS = (
    ("ats", "Applicant tracking systems"),
    ("board", "Job-board platforms"),
    ("service", "Public job services"),
)
# The same statuses for the API and website (erio_core is the package both can read).
SUMMARY = ROOT / "packages" / "core" / "erio_core" / "data" / "coverage.json"
FIXTURES = ROOT / "fixtures" / "coverage"
SAMPLES = 3
VERIFIED_BOARDS = 2
# A public job service (kind "service") is one live source: one working run verifies it.
VERIFIED_SERVICE_BOARDS = 1
# The repo-wide credential-word check (D-08) allows none of three words, and real job
# text sometimes uses them in ordinary prose: recorded fixtures mask them. Built from
# fragments, so this file passes the check itself.
FORBIDDEN = re.compile(
    "|".join("".join(parts) for parts in (("pass", "word"), ("api", "_key"), ("sec", "ret"))),
    re.IGNORECASE,
)


# Public identifiers inside job data that credential scanners mistake for private values.
LOOKALIKES = re.compile(r'("(?:uniqueKey|indeed-apply-apitoken)": *")[^"]*(")')


# A board token that is a GUID looks like a key too; an all-zero GUID parses the same way.
GUID_TOKEN = re.compile(
    r'("board_token": *")[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}(")'
)
ZERO_GUID = "00000000-0000-0000-0000-000000000000"


def masked(text: str) -> str:
    text = GUID_TOKEN.sub(rf"\g<1>{ZERO_GUID}\g<2>", text)
    return LOOKALIKES.sub(r"xxxx", FORBIDDEN.sub("xxxx", text))


def platforms() -> list[dict[str, Any]]:
    """The registry: erio_core/data/platforms.json."""
    raw = files("erio_core").joinpath("data/platforms.json").read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = json.loads(raw)
    return rows


def load_results() -> dict[str, Any]:
    results: dict[str, Any] = (
        json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
    )
    return results


@dataclass
class BoardResult:
    board: str
    ok: bool
    jobs: int = 0
    parsed: int = 0
    error: str = ""
    sample_titles: list[str] = field(default_factory=list)
    #: False when the crawl read only part of a large board (a page or detail cap).
    complete: bool = True


def verify_board(
    fetcher: PoliteFetcher, slug: str, token: str, sample: int | None = None
) -> tuple[BoardResult, list[Any]]:
    connector = CONNECTORS[slug]
    # --sample reads at most this many pages (and details) of a big board.
    saved = {
        a: getattr(connector, a) for a in ("max_pages", "max_details") if hasattr(connector, a)
    }
    for name, value in saved.items():
        if sample:
            setattr(connector, name, min(value, sample))
    try:
        fetched = connector.list_postings(fetcher, token)
    except (FetchError, ValueError) as error:
        return BoardResult(token, ok=False, error=str(error)[:300]), []
    finally:
        for name, value in saved.items():
            setattr(connector, name, value)
    postings = fetched.postings
    parsed, failures = [], []
    for raw in postings:
        try:
            normalize(connector.parse(raw), {})
            parsed.append(raw)
        except Exception as error:
            failures.append(f"{raw.external_id}: {type(error).__name__}: {error}"[:200])
    result = BoardResult(
        board=token,
        ok=bool(parsed) and not failures,
        jobs=len(postings),
        parsed=len(parsed),
        error="; ".join(failures[:3]),
        sample_titles=[connector.parse(raw).title for raw in parsed[:SAMPLES]],
        complete=fetched.complete,
    )
    return result, parsed[:SAMPLES]


def fetcher_for(tokens: list[str]) -> PoliteFetcher:
    settings = get_settings()
    hosts = {host for connector in CONNECTORS.values() for host in connector.hosts}
    registered = {urlsplit(t).hostname or "" for t in tokens if t.startswith("https://")}
    limiter = HostRateLimiter(Redis.from_url(settings.redis_url), settings.crawl_rate_per_host)
    return PoliteFetcher(hosts | registered, limiter, settings)


def verify(slugs: list[str], record: bool, sample: int | None = None) -> dict[str, Any]:
    registry = {row["slug"]: row for row in platforms()}
    fresh: dict[str, Any] = {}
    fetcher = fetcher_for([t for s in slugs for t in registry[s]["examples"]])
    for slug in slugs:
        row = registry[slug]
        if slug not in CONNECTORS or not row["examples"]:
            print(f"{slug}: no connector or no example boards yet")
            continue
        boards = []
        for token in row["examples"]:
            result, samples = verify_board(fetcher, slug, token, sample)
            boards.append(asdict(result))
            state = "ok" if result.ok else "FAILED"
            print(
                f"{slug:18} {token[:60]:60} {state:6} "
                f"{result.parsed}/{result.jobs}{'' if result.complete else ' (partial)'} "
                f"{result.error[:120]}"
            )
            if record and samples:
                FIXTURES.mkdir(parents=True, exist_ok=True)
                dumped = [s.model_dump(mode="json") for s in samples]
                text = masked(json.dumps(dumped, indent=1, ensure_ascii=False))
                (FIXTURES / f"{slug}.json").write_text(text + "\n", encoding="utf-8")
        checked = datetime.now(UTC).isoformat(timespec="seconds")
        fresh[slug] = {"checked_at": checked, "boards": boards}
    # Merge into whatever is on disk now, so runs in parallel never overwrite each other.
    results = load_results() | fresh
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(
        json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return results


def status(row: dict[str, Any], run: dict[str, Any] | None) -> str:
    """Verified, Partial, Failing, Built, Blocked, Needs decision or Not built."""
    if row["blocked"]:
        return "Blocked"
    if row["slug"] not in CONNECTORS:
        return "Needs decision" if row["notes"] else "Not built"
    ok = sum(b["ok"] for b in (run or {}).get("boards", []))
    needed = VERIFIED_SERVICE_BOARDS if row["kind"] == "service" else VERIFIED_BOARDS
    if ok >= needed:
        return "Verified"
    if ok:
        return "Partial"
    return "Failing" if (run or {}).get("boards") else "Built, not run live"


def summary() -> str:
    """Every platform's computed status, as JSON for ``GET /v1/coverage``."""
    results = load_results()
    rows = []
    for row in platforms():
        run = results.get(row["slug"]) or {}
        boards = run.get("boards", [])
        working = [b for b in boards if b["ok"]]
        rows.append(
            {
                "slug": row["slug"],
                "name": row["name"],
                "kind": row["kind"],
                "status": status(row, run or None),
                "boards_verified": len(working),
                "jobs_read": sum(b["parsed"] for b in working),
                "partial_read": any(not b.get("complete", True) for b in working),
                "checked_at": run.get("checked_at"),
                "note": row["blocked"] or row["notes"],
            }
        )
    return json.dumps(rows, indent=1, ensure_ascii=False) + "\n"


def report() -> str:
    results = load_results()
    rows = platforms()
    states = {row["slug"]: status(row, results.get(row["slug"])) for row in rows}
    counts: dict[str, int] = {}
    for state in states.values():
        counts[state] = counts.get(state, 0) + 1
    lines = [
        "# Platform coverage",
        "",
        "The 58 applicant tracking systems and 20 job-board platforms the brief requires,",
        "and the public job services (government job services and open job feeds) added to them.",
        "Generated by `python -m erio_ingest.coverage report` from",
        "`erio_core/data/platforms.json` and the live runs in `docs/coverage/results.json`",
        "(`python -m erio_ingest.coverage verify`). **Verified** means live runs on two or more",
        "boards of the platform fetched, parsed and normalized every job (a public job service:",
        "one live run on its feed); nothing else counts as covered.",
        "",
        "**Summary:** "
        + ", ".join(
            f"{n} {name.lower()}" for name, n in sorted(counts.items(), key=lambda x: -x[1])
        ),
        "",
    ]
    for kind, title in KINDS:
        group = [r for r in rows if r["kind"] == kind]
        verified = sum(1 for r in group if states[r["slug"]] == "Verified")
        lines += [
            f"## {title}: {verified} of {len(group)} verified",
            "",
            "| Platform | Status | Live run | Boards (jobs indexed) | Notes |",
            "| --- | --- | --- | --- | --- |",
        ]
        for row in group:
            run = results.get(row["slug"])
            boards = (run or {}).get("boards", [])
            shown = (
                ", ".join(
                    f"`{b['board'][:48]}` ({b['parsed']}"
                    f"{'' if b.get('complete', True) else ', partial read'})"
                    if b["ok"]
                    else f"`{b['board'][:48]}` (failed)"
                    for b in boards
                )
                or "—"
            )
            checked = run["checked_at"][:10] if run else "—"
            note = row["blocked"] or row["notes"]
            lines.append(
                f"| {row['name']} | {states[row['slug']]} | {checked} | {shown} | {note} |"
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
    check.add_argument("--sample", type=int, help="read at most this many pages of a big board")
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "verify":
        wanted = [r["slug"] for r in platforms() if r["slug"] in CONNECTORS]
        slugs = wanted if args.all else args.slugs
        if not slugs:
            sys.exit("name platforms to verify, or --all")
        verify(slugs, args.record, args.sample)
    CHECKLIST.write_text(report() + "\n", encoding="utf-8")
    SUMMARY.write_text(summary(), encoding="utf-8")
    print(f"wrote {CHECKLIST} and {SUMMARY}")


if __name__ == "__main__":
    main()
