"""Scheduled work for the anonymous workspace: saved searches and retention.

The logic lives in ``erio_core.saved_search`` (shared with the API); this module only opens
the sessions the worker tasks need.
"""

from datetime import datetime

from opensearchpy import OpenSearch
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from erio_core.digest import DigestResult, send_digests
from erio_core.saved_search import RunResult, delete_unused_workspaces, run_all


def evaluate_saved_searches(
    engine: Engine, client: OpenSearch, alias: str, site_url: str, now: datetime
) -> RunResult:
    """Check every saved search for jobs indexed since its last check, then tell webhooks."""
    with Session(engine) as session, session.begin():
        return run_all(session, client, alias, site_url, now)


def cleanup_workspaces(engine: Engine, now: datetime) -> int:
    """Delete workspaces unused for 12 months, with everything in them."""
    with Session(engine) as session, session.begin():
        return delete_unused_workspaces(session, now)


def email_digests(
    engine: Engine, client: OpenSearch, alias: str, site_url: str, now: datetime
) -> DigestResult:
    """Email each confirmed address the new jobs that fit its CV (when its turn has come)."""
    with Session(engine) as session, session.begin():
        return send_digests(session, client, alias, site_url, now)
