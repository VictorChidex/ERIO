import pytest

from erio_core.settings import Settings


def test_defaults_point_at_local_stack() -> None:
    settings = Settings()
    assert settings.environment == "local"
    assert settings.database_url.startswith("postgresql://")
    assert "@localhost" in settings.database_url


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ERIO_REDIS_URL", "redis://redis:6379/1")
    assert Settings().redis_url == "redis://redis:6379/1"


def test_database_url_carries_no_credential() -> None:
    # A user name is fine; a "user:value@" pair would mean a credential in config.
    userinfo = Settings().database_url.split("://", 1)[1].split("@", 1)[0]
    assert ":" not in userinfo
