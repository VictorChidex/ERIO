"""Saved searches: find new matches, tell a webhook, and retire unused workspaces.

Shared by the API (a first look when a search is saved) and the scheduled worker task, so a
saved search always means exactly what the same filters mean on GET /v1/jobs.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from erio_core.db.workspace_models import (
    MAX_MATCHES_PER_SEARCH,
    RETENTION_DAYS,
    SavedSearch,
    SavedSearchMatch,
    Workspace,
)
from erio_core.search.params import SearchParams
from erio_core.search.query import build_search
from erio_core.webhook import Resolver, deliver, resolve

log = logging.getLogger(__name__)

# Jobs are searchable a little after they are indexed; look back this far each time and let
# the unique (search, job) key drop what was already seen.
OVERLAP = timedelta(minutes=2)
PER_RUN = 50
BASELINE = 20
WEBHOOK_BATCH = 25
MAX_WEBHOOK_FAILURES = 5
SOURCE_FIELDS = ["canonical_id", "title", "company_name", "location_text", "apply_url"]
SOURCE_FIELDS += ["posted_at", "indexed_at"]


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def search_hits(
    client: OpenSearch,
    alias: str,
    params: dict[str, Any],
    *,
    since: datetime | None,
    size: int,
) -> list[dict[str, Any]]:
    """Jobs matching ``params`` (newest first), only those indexed after ``since`` if given."""
    query = SearchParams.model_validate(params).to_query(indexed_after=since, per_page=size)
    body = build_search(query)
    body.pop("aggs", None)
    body["track_total_hits"] = False
    body["_source"] = SOURCE_FIELDS
    try:
        response = client.search(index=alias, body=body)
    except NotFoundError:
        return []
    return [hit["_source"] for hit in response["hits"]["hits"]]


def _add_matches(
    session: Session,
    search: SavedSearch,
    hits: Sequence[dict[str, Any]],
    *,
    matched_at: datetime | None,
    delivered: bool,
    now: datetime,
) -> list[SavedSearchMatch]:
    known = set(
        session.scalars(
            select(SavedSearchMatch.job_id).where(SavedSearchMatch.search_id == search.id)
        )
    )
    added = []
    for hit in hits:
        if hit["canonical_id"] in known:
            continue
        match = SavedSearchMatch(
            search_id=search.id,
            job_id=hit["canonical_id"],
            title=str(hit["title"])[:300],
            company=str(hit["company_name"])[:200],
            location=(str(hit["location_text"])[:300] if hit.get("location_text") else None),
            apply_url=hit["apply_url"],
            posted_at=_parse(hit.get("posted_at")),
            matched_at=matched_at or _parse(hit.get("indexed_at")) or now,
            delivered_at=now if delivered else None,
        )
        session.add(match)
        added.append(match)
    session.flush()
    return added


def trim_matches(session: Session, search_id: int) -> None:
    """Keep only the newest MAX_MATCHES_PER_SEARCH matches."""
    keep = (
        select(SavedSearchMatch.id)
        .where(SavedSearchMatch.search_id == search_id)
        .order_by(SavedSearchMatch.matched_at.desc(), SavedSearchMatch.id.desc())
        .limit(MAX_MATCHES_PER_SEARCH)
    )
    session.execute(
        delete(SavedSearchMatch).where(
            SavedSearchMatch.search_id == search_id, SavedSearchMatch.id.not_in(keep)
        )
    )


def baseline(
    session: Session, search: SavedSearch, client: OpenSearch, alias: str, now: datetime
) -> int:
    """First look at a new search: the current best matches go in the feed, none count as new."""
    hits = search_hits(client, alias, search.params, since=None, size=BASELINE)
    # Dated by when each job was indexed, so they are older than "your last look".
    added = _add_matches(session, search, hits, matched_at=None, delivered=True, now=now)
    search.last_evaluated_at = now
    search.last_viewed_at = now
    return len(added)


def evaluate(
    session: Session, search: SavedSearch, client: OpenSearch, alias: str, now: datetime
) -> list[SavedSearchMatch]:
    """New matches for one search since its last evaluation; records them."""
    since = search.last_evaluated_at - OVERLAP
    hits = search_hits(client, alias, search.params, since=since, size=PER_RUN)
    added = _add_matches(session, search, hits, matched_at=now, delivered=False, now=now)
    search.last_evaluated_at = now
    trim_matches(session, search.id)
    return added


def new_count(session: Session, search: SavedSearch) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(SavedSearchMatch)
            .where(
                SavedSearchMatch.search_id == search.id,
                SavedSearchMatch.matched_at > search.last_viewed_at,
            )
        )
        or 0
    )


def webhook_body(
    search: SavedSearch, matches: Sequence[SavedSearchMatch], site_url: str, now: datetime
) -> bytes:
    payload = {
        "event": "saved_search.matches",
        "search": {"name": search.name},
        "sent_at": now.isoformat(),
        "matches": [
            {
                "id": m.job_id,
                "title": m.title,
                "company": m.company,
                "location": m.location,
                "url": f"{site_url.rstrip('/')}/jobs/{m.job_id}",
                "apply_url": m.apply_url,
                "posted_at": m.posted_at.isoformat() if m.posted_at else None,
            }
            for m in matches
        ],
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def deliver_pending(
    session: Session,
    search: SavedSearch,
    site_url: str,
    now: datetime,
    *,
    resolver: Resolver = resolve,
    transport: httpx.BaseTransport | None = None,
) -> bool | None:
    """Tell the search's webhook about matches it has not heard of. True sent, False failed,
    None nothing to do. Five failures in a row switch the webhook off."""
    if not search.webhook_url or search.webhook_disabled:
        return None
    pending = session.scalars(
        select(SavedSearchMatch)
        .where(SavedSearchMatch.search_id == search.id, SavedSearchMatch.delivered_at.is_(None))
        .order_by(SavedSearchMatch.matched_at, SavedSearchMatch.id)
        .limit(WEBHOOK_BATCH)
    ).all()
    if not pending:
        return None
    result = deliver(
        search.webhook_url,
        webhook_body(search, pending, site_url, now),
        resolver=resolver,
        transport=transport,
    )
    if result.ok:
        for match in pending:
            match.delivered_at = now
        search.webhook_failures = 0
        return True
    search.webhook_failures += 1
    if search.webhook_failures >= MAX_WEBHOOK_FAILURES:
        search.webhook_disabled = True
    log.warning(
        "saved search webhook failed",
        extra={"search_id": search.id, "status": result.status, "reason": result.error},
    )
    return False


@dataclass
class RunResult:
    searches: int = 0
    new_matches: int = 0
    webhooks_sent: int = 0
    webhooks_failed: int = 0
    errors: int = 0


def run_all(
    session: Session,
    client: OpenSearch,
    alias: str,
    site_url: str,
    now: datetime,
    *,
    resolver: Resolver = resolve,
    transport: httpx.BaseTransport | None = None,
) -> RunResult:
    """Evaluate every saved search, then deliver webhooks; one failing never stops the rest."""
    result = RunResult()
    for search_id in session.scalars(select(SavedSearch.id).order_by(SavedSearch.id)).all():
        search = session.get(SavedSearch, search_id)
        if search is None:
            continue
        result.searches += 1
        try:
            with session.begin_nested():
                result.new_matches += len(evaluate(session, search, client, alias, now))
                outcome = deliver_pending(
                    session, search, site_url, now, resolver=resolver, transport=transport
                )
        except Exception:
            log.exception("saved search failed", extra={"search_id": search_id})
            result.errors += 1
            continue
        if outcome is True:
            result.webhooks_sent += 1
        elif outcome is False:
            result.webhooks_failed += 1
    return result


def delete_unused_workspaces(session: Session, now: datetime) -> int:
    """Retention: a workspace not used for RETENTION_DAYS goes, with everything in it."""
    cutoff = now - timedelta(days=RETENTION_DAYS)
    ids = session.scalars(select(Workspace.id).where(Workspace.last_used_at < cutoff)).all()
    if ids:
        session.execute(delete(Workspace).where(Workspace.id.in_(ids)))
    return len(ids)
