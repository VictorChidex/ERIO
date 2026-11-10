"""Contract tests from real recorded jobs, and the coverage registry's rules.

``fixtures/coverage/{slug}.json`` holds three real postings per platform, saved
by ``python -m erio_ingest.coverage verify --record`` from live boards. Each
must parse and normalize with its connector, so a connector change that breaks
real data fails CI for that platform only.
"""

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from erio_core.connectors import CONNECTORS
from erio_core.data import platforms_path
from erio_core.normalize.job import normalize
from erio_core.schemas import RawPosting

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "coverage"
RECORDED = sorted(FIXTURES.glob("*.json"))


def registry() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = json.loads(platforms_path().read_text(encoding="utf-8"))
    return rows


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.stem)
def test_recorded_postings_parse_and_normalize(path: Path) -> None:
    connector = CONNECTORS[path.stem]
    postings = json.loads(path.read_text(encoding="utf-8"))
    assert postings, "an empty fixture proves nothing"
    for data in postings:
        raw = RawPosting.model_validate(data)
        job = connector.parse(raw)
        assert job.source_slug == path.stem
        assert job.title.strip()
        assert str(job.apply_url).startswith("https://")
        normalize(job, {})


def test_every_connector_with_examples_has_recorded_postings() -> None:
    recorded = {p.stem for p in RECORDED}
    for row in registry():
        slug = str(row["slug"])
        if slug in CONNECTORS and row["examples"] and not row["blocked"]:
            assert slug in recorded, f"{slug} has example boards but no recorded postings"


def test_registry_lists_the_58_ats_and_20_job_board_platforms() -> None:
    rows = registry()
    kinds = [row["kind"] for row in rows]
    # The brief's 58 and 20, plus platforms added later by comparing with the reference index.
    assert kinds.count("ats") >= 58 and kinds.count("board") >= 20
    assert set(kinds) == {"ats", "board", "service"}
    slugs = [row["slug"] for row in rows]
    assert len(set(slugs)) == len(slugs)


def test_public_job_services_are_listed_apart_from_the_78_platforms() -> None:
    services = [row for row in registry() if row["kind"] == "service"]
    assert len(services) >= 9
    built = [row for row in services if not row["blocked"]]
    assert built, "at least one service must be built"
    for row in built:
        connector = CONNECTORS[str(row["slug"])]
        assert getattr(connector, "multi_employer", False), row["slug"]
        assert row["examples"] and row["notes"], f"{row['slug']} needs an example and its credit"
    for row in services:
        if row["blocked"]:
            assert row["slug"] not in CONNECTORS, f"{row['slug']} is blocked but has a connector"


def test_every_connector_is_a_listed_platform() -> None:
    listed = {str(row["slug"]) for row in registry()}
    assert set(CONNECTORS) <= listed


def test_blocked_platforms_say_why() -> None:
    for row in registry():
        if row["blocked"]:
            assert len(str(row["blocked"])) > 20, row["slug"]


HOSTILE_TOKENS = [
    "http://169.254.169.254/latest/meta-data",
    "https://evil.example.org/x",
    "../../etc/passwd-not-a-board",
    "a b",
    "a.b/c",
    "x@evil.example.org",
]


def host_is_declared(host: str, declared: frozenset[str]) -> bool:
    return host in declared or any(d.startswith("*.") and host.endswith(d[1:]) for d in declared)


@pytest.mark.parametrize("slug", sorted(CONNECTORS))
def test_a_hostile_board_token_cannot_aim_a_connector_at_another_host(slug: str) -> None:
    connector = CONNECTORS[slug]
    for token in HOSTILE_TOKENS:
        try:
            url = connector.board_url(token)
        except ValueError:
            continue
        host = urlsplit(url).hostname
        assert host, (slug, token, url)
        # Connectors for boards on their own domain take the board's address as the token:
        # that host is admitted only because the board is registered (PoliteFetcher).
        takes_addresses = token.startswith("https://") and host == urlsplit(token).hostname
        assert host_is_declared(host, connector.hosts) or takes_addresses, (slug, token, url)
