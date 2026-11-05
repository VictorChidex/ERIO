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
    # Name searches use; it always points at the live jobs index.
    search_alias: str = "jobs"
    s3_endpoint_url: str = "http://127.0.0.1:9090"
    raw_bucket: str = "erio-raw"
    # Local S3Mock accepts unsigned requests; real S3 uses the IAM role.
    s3_unsigned: bool = True
    dependency_timeout_s: float = 2.0

    # API access (decision D-15). Requests from these networks count as
    # internal and need no token: in local compose, the website's network.
    api_internal_cidrs: list[str] = []
    api_rate_anonymous: int = 30
    api_rate_free: int = 100
    api_rate_pro: int = 2000
    api_rate_internal: int = 6000

    # Crawler identity and politeness (spec section 5). The bot page moves to
    # the product domain once decision D-06 is made.
    crawler_user_agent: str = "ERIO-Indexer/0.1 (+https://github.com/VictorChidex/ERIO)"
    crawl_rate_per_host: float = 2.0
    crawl_timeout_s: float = 20.0
    crawl_max_response_bytes: int = 10 * 1024 * 1024

    # AI gateway (spec section 13). Routing lives in erio_core/ai/routing.json
    # unless a path is given; provider addresses can be overridden per
    # environment. Tokens never come from here: only from the credential vault.
    ai_enabled: bool = True
    ai_routing_path: str | None = None
    ai_provider_urls: dict[str, str] = {}
    ai_timeout_s: float = 60.0

    @property
    def sqlalchemy_url(self) -> str:
        """``database_url`` with the psycopg 3 driver named, as SQLAlchemy expects."""
        return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
