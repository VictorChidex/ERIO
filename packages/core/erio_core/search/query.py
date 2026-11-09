"""The job search query builder, shared by the API and the workers (spec section 7).

One source of truth for what a job filter means: ``GET /v1/jobs``, saved searches and
CV matching all build their OpenSearch body here.

Filters split in two. Base filters (status, salary, posted date, platform,
the text query) narrow everything. Facet dimensions (country, role, work
type) apply to the hits through ``post_filter``, and each facet is counted
with every filter except its own, so the sidebar can show how many jobs
picking another value would give.
"""

import base64
import binascii
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Sort = Literal["recent", "salary", "relevance"]
TEXT_FIELDS = ["title^3", "company_name^2", "location_text^2", "description_text"]
COUNTRY_FACET_SIZE = 300


class BadCursor(ValueError):
    pass


@dataclass
class JobQuery:
    q: str | None = None
    countries: list[str] = field(default_factory=list)
    include_worldwide: bool = True
    remote_status: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    salary_min_usd: int | None = None
    platforms: list[str] = field(default_factory=list)
    company: str | None = None
    location: str | None = None
    employment_types: list[str] = field(default_factory=list)
    posted_after: datetime | None = None
    # Only jobs the index first saw after this moment (saved searches look for new matches).
    indexed_after: datetime | None = None
    status: list[str] = field(default_factory=lambda: ["open"])
    sort: Sort = "recent"
    cursor: str | None = None
    per_page: int = 25


def encode_cursor(sort_values: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(sort_values).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded))
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise BadCursor("cursor is not one this API returned") from error
    if not isinstance(values, list):
        raise BadCursor("cursor is not one this API returned")
    return values


def _country_filter(query: JobQuery) -> dict[str, Any] | None:
    if not query.countries:
        return None
    should: list[dict[str, Any]] = [{"terms": {"filter_countries": query.countries}}]
    if query.include_worldwide:
        should.append({"term": {"worldwide": True}})
    return {"bool": {"should": should, "minimum_should_match": 1}}


def _dimension_filters(query: JobQuery) -> dict[str, dict[str, Any]]:
    filters: dict[str, dict[str, Any]] = {}
    if country := _country_filter(query):
        filters["country"] = country
    if query.roles:
        filters["role"] = {"terms": {"role_category": query.roles}}
    if query.remote_status:
        filters["remote_status"] = {"terms": {"remote_status": query.remote_status}}
    return filters


def base_query(query: JobQuery) -> dict[str, Any]:
    must: list[dict[str, Any]] = []
    if query.q:
        must.append(
            {
                "multi_match": {
                    "query": query.q,
                    "fields": TEXT_FIELDS,
                    "type": "cross_fields",
                    "operator": "and",
                }
            }
        )
    filters: list[dict[str, Any]] = [{"terms": {"status": query.status}}]
    if query.salary_min_usd is not None:
        filters.append({"range": {"salary_usd_annual_min": {"gte": query.salary_min_usd}}})
    if query.posted_after is not None:
        filters.append({"range": {"posted_at": {"gte": query.posted_after.isoformat()}}})
    if query.indexed_after is not None:
        filters.append({"range": {"indexed_at": {"gt": query.indexed_after.isoformat()}}})
    if query.platforms:
        filters.append({"terms": {"sources": query.platforms}})
    if query.company:
        # The employer's name (every word), or exactly its domain.
        filters.append(
            {
                "bool": {
                    "should": [
                        {"match": {"company_name": {"query": query.company, "operator": "and"}}},
                        {"term": {"company_domain": query.company.lower()}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if query.location:
        filters.append({"match": {"location_text": {"query": query.location, "operator": "and"}}})
    if query.employment_types:
        filters.append({"terms": {"employment_type": query.employment_types}})
    return {"bool": {"must": must or [{"match_all": {}}], "filter": filters}}


def _sort(query: JobQuery) -> list[dict[str, Any]]:
    tiebreak = {"canonical_id": "asc"}
    if query.sort == "relevance" and query.q:
        return [{"_score": "desc"}, tiebreak]
    if query.sort == "salary":
        return [{"salary_usd_annual_min": {"order": "desc", "missing": "_last"}}, tiebreak]
    return [{"posted_at": {"order": "desc", "missing": "_last"}}, tiebreak]


def _facet(name: str, field_name: str, others: list[dict[str, Any]], size: int) -> dict[str, Any]:
    return {
        "filter": {"bool": {"filter": others}} if others else {"match_all": {}},
        "aggs": {"values": {"terms": {"field": field_name, "size": size}}},
    }


def build_search(query: JobQuery) -> dict[str, Any]:
    dimensions = _dimension_filters(query)
    body: dict[str, Any] = {
        "query": base_query(query),
        "sort": _sort(query),
        "size": query.per_page,
        "track_total_hits": True,
        "_source": {"excludes": ["description_text"]},
        "aggs": {
            "country": _facet(
                "country",
                "filter_countries",
                [f for k, f in dimensions.items() if k != "country"],
                COUNTRY_FACET_SIZE,
            ),
            "role": _facet(
                "role", "role_category", [f for k, f in dimensions.items() if k != "role"], 20
            ),
            "remote_status": _facet(
                "remote_status",
                "remote_status",
                [f for k, f in dimensions.items() if k != "remote_status"],
                10,
            ),
        },
    }
    if dimensions:
        body["post_filter"] = {"bool": {"filter": list(dimensions.values())}}
    if query.cursor:
        body["search_after"] = decode_cursor(query.cursor)
    return body
