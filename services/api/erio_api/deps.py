"""Shared dependencies: database engine and search client."""

from functools import lru_cache
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError
from sqlalchemy import Engine

from erio_core.db.engine import make_engine
from erio_core.search.index import client, ensure_alias
from erio_core.settings import get_settings


@lru_cache
def engine() -> Engine:
    return make_engine(get_settings())


def search_client() -> OpenSearch:
    return client()


def search_alias() -> str:
    return get_settings().search_alias


def run_search(search: OpenSearch, alias: str, body: dict[str, Any]) -> Any:
    """Search ``alias``; if its index is missing, create an empty one and retry,
    so a fresh or reset OpenSearch answers with no results instead of an error."""
    try:
        return search.search(index=alias, body=body)
    except NotFoundError:
        ensure_alias(search, alias)
        return search.search(index=alias, body=body)
