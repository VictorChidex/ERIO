"""Stored searches turn into the same query the API builds for GET /v1/jobs."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from erio_core.search.params import SearchParams
from erio_core.search.query import build_search


def test_params_become_the_jobs_query() -> None:
    params = SearchParams.model_validate(
        {"q": " nurse ", "country": ["NG"], "remote_status": ["remote"], "salary_min_usd": 1000}
    )
    query = params.to_query()
    assert query.q == "nurse"
    assert query.countries == ["NG"]
    assert query.status == ["open"]
    body = build_search(query)
    assert body["post_filter"]["bool"]["filter"]
    assert {"range": {"salary_usd_annual_min": {"gte": 1000}}} in body["query"]["bool"]["filter"]


def test_indexed_after_limits_to_new_jobs() -> None:
    since = datetime(2026, 11, 5, tzinfo=UTC)
    body = build_search(SearchParams().to_query(indexed_after=since))
    assert {"range": {"indexed_at": {"gt": since.isoformat()}}} in body["query"]["bool"]["filter"]
    plain = build_search(SearchParams().to_query())
    assert all("indexed_at" not in str(f) for f in plain["query"]["bool"]["filter"])


@pytest.mark.parametrize(
    "bad",
    [
        {"country": ["nigeria"]},
        {"role": ["wizard"]},
        {"unknown": 1},
        {"salary_min_usd": -1},
        {"q": "x" * 201},
    ],
)
def test_bad_params_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SearchParams.model_validate(bad)
