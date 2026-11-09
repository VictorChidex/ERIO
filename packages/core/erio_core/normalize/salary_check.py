"""Is this pay plausible for its currency and period?

Sources sometimes label an hourly or monthly figure as yearly ("INR 4.5" as a year, "PHP 374.5"),
and the pay statistics then read hundreds of times too low. ``check_pay`` converts the lowest
figure to US dollars a year and compares it with a floor and a ceiling:

- Plausible: kept as it is.
- Implausible and the period was *labeled* by the source: the label cannot be trusted and
  nothing says what is right, so the figures are kept as posted but marked unreliable and left
  out of ``salary_usd_annual_min`` and of pay statistics.
- Implausible and the period was *not stated* (the parser only defaulted to a year, or guessed
  from a small number): the size of the figure may name the period, but only when exactly one
  reading is plausible. A wage of 5 to 150 dollars is hourly (nobody earns that a month or a
  year); 400 to 3,000 dollars is monthly (the same figure a year is below the floor, an hour is
  absurd). Between the bands, or below them, the pay is unreliable.

A figure whose currency has no rate cannot be judged and is left alone.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from erio_core.normalize.fx import PERIOD_FACTOR, PLAUSIBLE_USD_ANNUAL
from erio_core.schemas import SalaryHint, SalaryPeriod

PAY_FLOOR_USD, PAY_CEILING_USD = PLAUSIBLE_USD_ANNUAL
# Dollars per period that only one period can explain, for a figure whose period is unknown.
HOURLY_USD = (5.0, 150.0)
MONTHLY_USD = (400.0, PAY_FLOOR_USD)


@dataclass(frozen=True)
class PayCheck:
    """The period to keep (None: the source gave none), the yearly USD value, and the verdict."""

    period: SalaryPeriod | None
    usd_annual_min: int | None
    unreliable: bool


def _annual(figure_usd: float, period: SalaryPeriod) -> float:
    return figure_usd * PERIOD_FACTOR[period]


def _inferred_period(figure_usd: float) -> SalaryPeriod | None:
    """The one period that makes ``figure_usd`` a plausible wage, if exactly one does."""
    if HOURLY_USD[0] <= figure_usd <= HOURLY_USD[1]:
        return "hour"
    if MONTHLY_USD[0] <= figure_usd < MONTHLY_USD[1]:
        return "month"
    if PAY_FLOOR_USD <= figure_usd <= PAY_CEILING_USD:
        return "year"
    return None


def check_pay(salary: SalaryHint | None, usd_per_unit: Mapping[str, float]) -> PayCheck:
    if salary is None:
        return PayCheck(None, None, False)
    figure = salary.min if salary.min is not None else salary.max
    code = salary.currency
    if figure is None or code is None:
        return PayCheck(salary.period, None, False)
    rate = 1.0 if code == "USD" else usd_per_unit.get(code)
    if rate is None:
        return PayCheck(salary.period, None, False)
    figure_usd = figure * rate

    if not salary.period_stated:
        period = _inferred_period(figure_usd)
        if period is None:
            return PayCheck(salary.period, None, True)
        return PayCheck(period, round(_annual(figure_usd, period)), False)

    annual = _annual(figure_usd, salary.period or "year")
    if PAY_FLOOR_USD <= annual <= PAY_CEILING_USD:
        return PayCheck(salary.period, round(annual), False)
    return PayCheck(salary.period, None, True)
