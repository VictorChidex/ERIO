"""Shared dependencies: database engine and search client."""

from functools import lru_cache

from opensearchpy import OpenSearch
from sqlalchemy import Engine, create_engine

from erio_core.search.index import client
from erio_core.settings import get_settings


@lru_cache
def engine() -> Engine:
    return create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True)


def search_client() -> OpenSearch:
    return client()


def search_alias() -> str:
    return get_settings().search_alias
