"""Runtime configuration shared by all services.

Values come from environment variables prefixed with ``ERIO_``. They hold
addresses only, never credentials (decision D-08): local services trust
connections on the compose network, and deployed services get
credentials at runtime from the cloud credential vault through their IAM role.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ERIO_")

    environment: str = "local"
    database_url: str = "postgresql://erio@localhost:5432/erio"
    redis_url: str = "redis://localhost:6379/0"
    opensearch_url: str = "http://localhost:9200"
    s3_endpoint_url: str = "http://localhost:9000"
    raw_bucket: str = "erio-raw"
    dependency_timeout_s: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
