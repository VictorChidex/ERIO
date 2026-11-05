"""The jobs index: mapping, documents, and the client.

One document per open or unknown canonical job that resolved to a place.
An alias (``jobs`` by default) always points at the live index; a rebuild fills a new
index and swaps the alias in one step, so searches never see a half-built
index (spec section 7).

``filter_countries`` holds every country a country filter should find the
job under: its own country plus the countries a remote role accepts. Facet
counts and the country filter both use it, so a country's count always
equals the number of jobs its filter returns.
"""

from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from opensearchpy import OpenSearch

from erio_core.settings import get_settings

SEARCHABLE_STATUSES = ("open", "unknown")

SETTINGS: dict[str, Any] = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
        "analyzer": {
            "folded": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "asciifolding"],
            }
        }
    },
}

MAPPINGS: dict[str, Any] = {
    "dynamic": "strict",
    "properties": {
        "canonical_id": {"type": "keyword"},
        "title": {"type": "text", "analyzer": "folded"},
        "company_name": {
            "type": "text",
            "analyzer": "folded",
            "fields": {"kw": {"type": "keyword"}},
        },
        "company_domain": {"type": "keyword"},
        "company_logo_url": {"type": "keyword", "index": False},
        "description_text": {"type": "text", "analyzer": "folded"},
        "role_category": {"type": "keyword"},
        "location_text": {"type": "text", "analyzer": "folded"},
        "city": {"type": "keyword"},
        "region": {"type": "keyword"},
        "country_code": {"type": "keyword"},
        "eligible_country_codes": {"type": "keyword"},
        "filter_countries": {"type": "keyword"},
        "worldwide": {"type": "boolean"},
        "location": {"type": "geo_point"},
        "remote_status": {"type": "keyword"},
        "remote_scope": {"type": "keyword"},
        "salary_min": {"type": "long"},
        "salary_max": {"type": "long"},
        "salary_currency": {"type": "keyword"},
        "salary_period": {"type": "keyword"},
        "salary_usd_annual_min": {"type": "long"},
        "status": {"type": "keyword"},
        "posted_at": {"type": "date"},
        "indexed_at": {"type": "date"},
        "last_verified_at": {"type": "date"},
        "closed_at": {"type": "date"},
        "sources": {"type": "keyword"},
        "dedup_method": {"type": "keyword"},
        "apply_url": {"type": "keyword", "index": False},
    },
}


@lru_cache
def client() -> OpenSearch:
    settings = get_settings()
    return OpenSearch(
        hosts=[settings.opensearch_url], timeout=10, max_retries=2, retry_on_timeout=True
    )


def new_index_name(alias: str, now: datetime | None = None) -> str:
    return f"{alias}_{(now or datetime.now(UTC)):%Y%m%d%H%M%S%f}"


def create_index(search: OpenSearch, name: str) -> None:
    search.indices.create(index=name, body={"settings": SETTINGS, "mappings": MAPPINGS})


def ensure_alias(search: OpenSearch, alias: str) -> str:
    """The index behind ``alias``, creating one if there is none."""
    if search.indices.exists_alias(name=alias):
        return str(next(iter(search.indices.get_alias(name=alias))))
    name = new_index_name(alias)
    create_index(search, name)
    search.indices.put_alias(index=name, name=alias)
    return name


def swap_alias(search: OpenSearch, alias: str, new_index: str) -> list[str]:
    """Point ``alias`` at ``new_index`` atomically; return the old index names."""
    old = (
        list(search.indices.get_alias(name=alias))
        if search.indices.exists_alias(name=alias)
        else []
    )
    actions: list[dict[str, Any]] = [{"remove": {"index": i, "alias": alias}} for i in old]
    actions.append({"add": {"index": new_index, "alias": alias}})
    search.indices.update_aliases(body={"actions": actions})
    return old


def document(job: dict[str, Any]) -> dict[str, Any]:
    """Search document for one job row (joined with its company and sources)."""
    eligible = list(job.get("eligible_country_codes") or [])
    countries = sorted({*eligible, *([job["country_code"]] if job.get("country_code") else [])})
    lat, lon = job.get("lat"), job.get("lon")
    return {
        "canonical_id": job["canonical_id"],
        "title": job["title"],
        "company_name": job["company_name"],
        "company_domain": job.get("company_domain"),
        "company_logo_url": job.get("company_logo_url"),
        "description_text": job.get("description_text"),
        "role_category": job["role_category"],
        "location_text": job.get("location_text"),
        "city": job.get("city"),
        "region": job.get("region"),
        "country_code": job.get("country_code"),
        "eligible_country_codes": eligible,
        "filter_countries": countries,
        "worldwide": job.get("remote_scope") == "worldwide",
        "location": {"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
        "remote_status": job["remote_status"],
        "remote_scope": job.get("remote_scope"),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "salary_currency": job.get("salary_currency"),
        "salary_period": job.get("salary_period"),
        "salary_usd_annual_min": job.get("salary_usd_annual_min"),
        "status": job["status"],
        "posted_at": job.get("posted_at"),
        "indexed_at": job.get("indexed_at"),
        "last_verified_at": job.get("last_verified_at"),
        "closed_at": job.get("closed_at"),
        "sources": list(job.get("sources") or []),
        "dedup_method": job.get("dedup_method"),
        "apply_url": job["apply_url"],
    }


def searchable(job: dict[str, Any]) -> bool:
    """Open or unknown jobs with a resolved place belong in the index."""
    return job["status"] in SEARCHABLE_STATUSES and not job.get("review_reason")
