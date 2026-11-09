"""Exchange rates for salary filtering (spec section 6).

Salaries are shown in the currency the employer posted. Filtering and
sorting use ``salary_usd_annual_min``, converted with daily rates: European
Central Bank reference rates first, then a fallback source for currencies
the ECB does not publish (NGN, KES, GHS, ...). Rates are stored as US
dollars per one unit of each currency.
"""

import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime

from erio_core.schemas import SalaryPeriod

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
FALLBACK_URL = "https://open.er-api.com/v6/latest/USD"

# The ECB file is small and fixed in shape; reading it with patterns avoids
# running an XML parser on downloaded content.
ECB_DAY = re.compile(r"""<Cube\s+time=['"](\d{4}-\d{2}-\d{2})['"]""")
ECB_RATE = re.compile(r"""<Cube\s+currency=['"]([A-Z]{3})['"]\s+rate=['"]([0-9.]+)['"]""")

PERIOD_FACTOR: dict[SalaryPeriod, float] = {"year": 1.0, "month": 12.0, "hour": 2080.0}
# Converted values outside this band are almost certainly parse errors or a wrong period:
# nobody is paid under 3,000 dollars a year for a posted job (an hourly or monthly figure
# stored as yearly lands far below it).
PLAUSIBLE_USD_ANNUAL = (3_000, 5_000_000)


def parse_ecb(body: bytes) -> tuple[date, dict[str, float]]:
    """ECB daily reference rates as US dollars per unit of each currency."""
    text = body.decode("utf-8", "replace")
    day_match = ECB_DAY.search(text)
    per_eur = {code: float(rate) for code, rate in ECB_RATE.findall(text)}
    if day_match is None or "USD" not in per_eur:
        raise ValueError("not an ECB daily rates file")
    usd_per_eur = per_eur["USD"]
    rates = {code: usd_per_eur / rate for code, rate in per_eur.items() if rate > 0}
    rates["EUR"], rates["USD"] = usd_per_eur, 1.0
    return date.fromisoformat(day_match.group(1)), rates


def parse_fallback(body: bytes) -> tuple[date, dict[str, float]]:
    """open.er-api.com latest USD rates (units per USD) as US dollars per unit."""
    data = json.loads(body)
    if data.get("result") != "success" or data.get("base_code") != "USD":
        raise ValueError("not a successful USD rates response")
    day = datetime.fromtimestamp(int(data["time_last_update_unix"]), UTC).date()
    rates = {code: 1.0 / float(rate) for code, rate in data["rates"].items() if float(rate) > 0}
    return day, rates


def usd_annual(
    amount: float | None,
    currency: str | None,
    period: SalaryPeriod | None,
    usd_per_unit: Mapping[str, float],
) -> int | None:
    """An amount as US dollars per year, or None if it cannot be converted."""
    if amount is None or currency is None:
        return None
    rate = 1.0 if currency == "USD" else usd_per_unit.get(currency)
    if rate is None:
        return None
    value = amount * PERIOD_FACTOR[period or "year"] * rate
    low, high = PLAUSIBLE_USD_ANNUAL
    return round(value) if low <= value <= high else None
