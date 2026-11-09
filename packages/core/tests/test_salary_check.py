"""Pay plausibility against labeled cases: figures as boards really print them.

Each case is a salary as the pipeline sees it (low, high, currency, the period it carries and
whether a source or the text stated that period) with the verdict labeled by hand: the period
that is kept, the yearly USD value, and whether the pay is marked unreliable.
"""

import pytest

from erio_core.normalize.job import normalize
from erio_core.normalize.salary import parse_salary
from erio_core.normalize.salary_check import check_pay
from erio_core.schemas import PartialJob, SalaryHint

RATES = {
    "INR": 0.012,
    "PHP": 0.017,
    "AED": 0.272,
    "NGN": 0.00065,
    "KES": 0.0077,
    "GBP": 1.30,
    "EUR": 1.08,
    "JPY": 0.0066,
}

# (low, high, currency, period, period stated, kept period, USD a year, unreliable)
CASES = [
    # Plausible as labeled.
    (90_000, 120_000, "USD", "year", True, "year", 90_000, False),
    (18, 24, "USD", "hour", True, "hour", 37_440, False),
    (4_000_000, 5_500_000, "JPY", "year", True, "year", 26_400, False),
    (450_000, 700_000, "INR", "year", True, "year", 5_400, False),
    (3_500_000, 5_000_000, "NGN", "month", True, "month", 27_300, False),
    (80_000, 95_000, "KES", "month", True, "month", 7_392, False),
    (None, 62_000, "GBP", "year", True, "year", 80_600, False),
    # Labeled yearly but far too small: the label is wrong, nothing says what is right.
    (4, 5, "INR", "year", True, "year", None, True),  # "4.5" lakh, read as rupees
    (45_000, 60_000, "INR", "year", True, "year", None, True),  # a monthly wage
    (374, 420, "PHP", "year", True, "year", None, True),
    (12, 15, "AED", "year", True, "year", None, True),
    (25, 30, "GBP", "year", True, "year", None, True),  # hourly, but only the size says so
    (5, 5, "USD", "year", True, "year", None, True),
    # Labeled monthly or hourly but implausible as such.
    (8_000, 9_000, "KES", "month", True, "month", None, True),
    (5_000, 6_000, "USD", "hour", True, "hour", None, True),
    # Period only assumed: the size may name it when one reading alone is plausible.
    (45, 60, "AED", "year", False, "hour", 25_459, False),
    (25, 32, "GBP", "hour", False, "hour", 67_600, False),
    (1_500_000, 1_900_000, "NGN", "year", False, "month", 11_700, False),
    (2_500, 3_000, "EUR", "year", False, "month", 32_400, False),
    (60_000, 80_000, "EUR", "year", False, "year", 64_800, False),
    # Between the bands, or below them: unreliable.
    (450_000, 600_000, "NGN", "year", False, "year", None, True),
    (11, 12, "AED", "year", False, "year", None, True),
    # Cannot be judged: no rate for the currency, or none given.
    (100_000, 120_000, "XYZ", "year", True, "year", None, False),
    (5, 9, None, "year", True, "year", None, False),
]


@pytest.mark.parametrize(
    ("low", "high", "currency", "period", "stated", "kept", "usd", "unreliable"), CASES
)
def test_labeled_pay_cases(
    low: int | None,
    high: int | None,
    currency: str | None,
    period: str,
    stated: bool,
    kept: str,
    usd: int | None,
    unreliable: bool,
) -> None:
    hint = SalaryHint(
        min=low,
        max=high,
        currency=currency,
        period=period,  # type: ignore[arg-type]
        period_stated=stated,
    )

    verdict = check_pay(hint, RATES)

    assert (verdict.period, verdict.usd_annual_min, verdict.unreliable) == (kept, usd, unreliable)


def test_no_salary_is_neither_reliable_nor_not() -> None:
    assert check_pay(None, RATES) == check_pay(None, {})
    assert check_pay(None, RATES).unreliable is False


def test_a_range_with_no_period_word_is_marked_as_guessed() -> None:
    stated = parse_salary("Salary: AED 45 - 60 per hour")
    guessed = parse_salary("Salary: AED 45 - 60")
    assert stated is not None and guessed is not None
    assert (stated.period, stated.period_stated) == ("hour", True)
    assert (guessed.period, guessed.period_stated) == ("hour", False)


def job(salary: SalaryHint | None, description: str | None = None) -> PartialJob:
    return PartialJob(
        source_slug="greenhouse",
        external_id="1",
        title="Driver",
        apply_url="https://example.test/apply",  # type: ignore[arg-type]
        location_text="Dubai, United Arab Emirates",
        salary=salary,
        description_html=description,
    )


def test_an_implausible_yearly_figure_keeps_its_numbers_but_not_its_usd_value() -> None:
    columns = normalize(
        job(SalaryHint(min=374, max=420, currency="PHP", period="year")), RATES
    ).columns()

    assert (columns["salary_min"], columns["salary_max"], columns["salary_period"]) == (
        374, 420, "year",
    )  # fmt: skip
    assert columns["salary_usd_annual_min"] is None
    assert columns["salary_unreliable"] is True


def test_a_guessed_hourly_period_is_inferred_from_the_description() -> None:
    columns = normalize(job(None, "<p>Salary: AED 45 - 60</p>"), RATES).columns()

    assert columns["salary_period"] == "hour"
    assert columns["salary_usd_annual_min"] == 25_459
    assert columns["salary_unreliable"] is False


def test_a_plausible_salary_is_untouched() -> None:
    columns = normalize(
        job(SalaryHint(min=90_000, max=120_000, currency="USD", period="year")), RATES
    ).columns()

    assert columns["salary_usd_annual_min"] == 90_000
    assert columns["salary_unreliable"] is False
