"""Daily FX refresh: ECB reference rates, then a fallback for the rest."""

from datetime import date

from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from erio_core.connectors import Fetcher, FetchError
from erio_core.db.models import FxRate
from erio_core.normalize.fx import ECB_URL, FALLBACK_URL, parse_ecb, parse_fallback

FX_HOSTS = frozenset({"www.ecb.europa.eu", "open.er-api.com"})


def _get(fetcher: Fetcher, url: str) -> bytes:
    response = fetcher.get(url)
    if response.status != 200:
        raise FetchError("http_error", f"{url} answered {response.status}", response.status)
    return response.body


def _store(engine: Engine, day: date, rates: dict[str, float], source: str) -> int:
    if not rates:
        return 0
    rows = [
        {"day": day, "currency": c, "usd_per_unit": r, "source": source} for c, r in rates.items()
    ]
    statement = insert(FxRate).values(rows)
    with engine.begin() as connection:
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[FxRate.day, FxRate.currency],
                set_={
                    "usd_per_unit": statement.excluded.usd_per_unit,
                    "source": statement.excluded.source,
                },
            )
        )
    return len(rows)


def refresh_rates(engine: Engine, fetcher: Fetcher) -> dict[str, int]:
    """Store today's rates; ECB wins wherever it publishes a currency."""
    ecb_day, ecb = parse_ecb(_get(fetcher, ECB_URL))
    counts = {"ecb": _store(engine, ecb_day, ecb, "ecb")}
    try:
        fallback_day, fallback = parse_fallback(_get(fetcher, FALLBACK_URL))
    except (FetchError, ValueError, KeyError):
        counts["fallback"] = 0  # ECB rates alone still cover the major currencies
        return counts
    extra = {code: rate for code, rate in fallback.items() if code not in ecb}
    counts["fallback"] = _store(engine, fallback_day, extra, "exchangerate-api")
    return counts
