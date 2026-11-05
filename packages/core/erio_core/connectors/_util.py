"""Small readers shared by the connectors."""

from datetime import UTC, datetime
from typing import Any

from erio_core.schemas import SalaryHint, SalaryPeriod

PERIOD_WORDS: dict[str, SalaryPeriod] = {
    "year": "year", "annual": "year", "month": "month", "hour": "hour"
}  # fmt: skip


def iso_datetime(value: Any) -> datetime | None:
    """An ISO 8601 timestamp; a bare date is taken as midnight UTC."""
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace(" UTC", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def epoch_ms(value: Any) -> datetime | None:
    if not isinstance(value, int | float) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def salary_period(text: Any) -> SalaryPeriod | None:
    """The period a source names: "per-year-salary", "1 YEAR", "month", "Hourly"."""
    folded = str(text or "").lower()
    return next((period for word, period in PERIOD_WORDS.items() if word in folded), None)


def salary(low: Any, high: Any, currency: Any, period: Any) -> SalaryHint | None:
    """A structured salary, or None so the normalizer reads the description instead."""

    def amount(value: Any) -> int | None:
        try:
            number = round(float(value))
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    low_n, high_n = amount(low), amount(high)
    named = salary_period(period)
    code = str(currency or "").strip().upper()
    if (low_n is None and high_n is None) or named is None or len(code) != 3:
        return None
    return SalaryHint(min=low_n, max=high_n, currency=code, period=named)


def join_html(*parts: str | None) -> str | None:
    html = "".join(part for part in parts if part)
    return html or None
