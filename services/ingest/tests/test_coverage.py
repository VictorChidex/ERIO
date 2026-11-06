"""The coverage checklist is generated from live runs, never written by hand."""

from typing import Any

from erio_ingest import coverage
from erio_ingest.coverage import CHECKLIST, report, status


def row(**changes: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "slug": "greenhouse",
        "name": "Greenhouse",
        "kind": "ats",
        "blocked": "",
        "notes": "",
        "examples": ["a", "b"],
    }
    return values | changes


def run(*ok: bool) -> dict[str, Any]:
    return {
        "boards": [{"board": f"b{i}", "ok": o, "parsed": 1, "jobs": 1} for i, o in enumerate(ok)]
    }


def test_verified_needs_two_boards_that_worked() -> None:
    assert status(row(), run(True, True)) == "Verified"
    assert status(row(), run(True, False)) == "Partial"
    assert status(row(), run(False, False)) == "Failing"
    assert status(row(), None) == "Built, not run live"


def test_blocked_and_unbuilt_platforms_are_never_verified() -> None:
    assert status(row(blocked="robots.txt disallows everything"), run(True, True)) == "Blocked"
    assert status(row(slug="no_such_connector"), run(True, True)) == "Not built"
    assert status(row(slug="no_such_connector", notes="needs a decision"), None) == "Needs decision"


def test_committed_checklist_is_what_the_live_results_generate() -> None:
    # Edit docs/coverage.md by hand and this fails: regenerate it with
    # `python -m erio_ingest.coverage report`.
    assert CHECKLIST.read_text(encoding="utf-8") == report() + "\n"


def test_every_verified_platform_in_the_checklist_has_live_results() -> None:
    results = coverage.load_results()
    for platform in coverage.platforms():
        if status(platform, results.get(platform["slug"])) == "Verified":
            boards = results[platform["slug"]]["boards"]
            assert sum(b["ok"] for b in boards) >= 2
            assert all(b["parsed"] > 0 for b in boards if b["ok"])
