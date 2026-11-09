"""Read job search results for the API (spec section 7).

The query builder itself lives in ``erio_core.search.query``, shared with the workers.
"""

from typing import Any

from erio_core.schemas import JobRecord
from erio_core.search.query import (
    COUNTRY_FACET_SIZE,
    TEXT_FIELDS,
    BadCursor,
    JobQuery,
    Sort,
    build_search,
    decode_cursor,
    encode_cursor,
)

__all__ = [
    "COUNTRY_FACET_SIZE",
    "TEXT_FIELDS",
    "BadCursor",
    "JobQuery",
    "Sort",
    "build_search",
    "decode_cursor",
    "encode_cursor",
    "read_results",
    "record_from_source",
]


def record_from_source(source: dict[str, Any]) -> JobRecord:
    """A JobRecord from a search hit. Lists leave out the description; the
    single-job endpoint returns it in full."""
    return JobRecord.model_validate(
        {
            "canonical_id": source["canonical_id"],
            "title": source["title"],
            "company": {
                "name": source["company_name"],
                "slug": source.get("company_slug"),
                "domain": source.get("company_domain"),
                "logo_url": source.get("company_logo_url"),
            },
            "role_category": source["role_category"],
            "location_text": source.get("location_text"),
            "city": source.get("city"),
            "region": source.get("region"),
            "country_code": source.get("country_code"),
            "lat": (source.get("location") or {}).get("lat"),
            "lon": (source.get("location") or {}).get("lon"),
            "remote_status": source["remote_status"],
            "remote_scope": source.get("remote_scope"),
            "eligible_country_codes": source.get("eligible_country_codes") or [],
            "salary_min": source.get("salary_min"),
            "salary_max": source.get("salary_max"),
            "salary_currency": source.get("salary_currency"),
            "salary_period": source.get("salary_period"),
            "salary_usd_annual_min": source.get("salary_usd_annual_min"),
            "status": source["status"],
            "posted_at": source.get("posted_at"),
            "indexed_at": source["indexed_at"],
            "last_verified_at": source.get("last_verified_at"),
            "closed_at": source.get("closed_at"),
            "sources": source.get("sources") or [],
            "dedup_method": source.get("dedup_method"),
            "apply_url": source["apply_url"],
            "description_html": None,
            "description_text": None,
        }
    )


def read_results(response: dict[str, Any], per_page: int) -> dict[str, Any]:
    hits = response["hits"]["hits"]
    aggs = response["aggregations"]

    def buckets(name: str) -> dict[str, int]:
        return {b["key"]: b["doc_count"] for b in aggs[name]["values"]["buckets"]}

    next_cursor = encode_cursor(hits[-1]["sort"]) if len(hits) == per_page else None
    return {
        "data": [record_from_source(hit["_source"]) for hit in hits],
        "meta": {
            "total": response["hits"]["total"]["value"],
            "next_cursor": next_cursor,
            "facets": {
                "country": buckets("country"),
                "role": buckets("role"),
                "remote_status": buckets("remote_status"),
            },
        },
    }
