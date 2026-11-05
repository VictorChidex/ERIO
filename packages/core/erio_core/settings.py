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
    database_url: str = "postgresql://erio@127.0.0.1:5432/erio"
    redis_url: str = "redis://127.0.0.1:6379/0"
    opensearch_url: str = "http://127.0.0.1:9200"
    s3_endpoint_url: str = "http://127.0.0.1:9090"
    raw_bucket: str = "erio-raw"
    dependency_timeout_s: float = 2.0

    @property
    def sqlalchemy_url(self) -> str:
        """``database_url`` with the psycopg 3 driver named, as SQLAlchemy expects."""
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
