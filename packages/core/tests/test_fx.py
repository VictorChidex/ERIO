from datetime import date
from pathlib import Path

import pytest

from erio_core.normalize.fx import parse_ecb, parse_fallback, usd_annual

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "fx"


def test_parses_ecb_daily_rates_as_usd_per_unit() -> None:
    day, rates = parse_ecb((FIXTURES / "ecb-daily.xml").read_bytes())

    assert day == date(2026, 11, 4)
    assert rates["USD"] == 1.0
    assert rates["EUR"] == pytest.approx(1.1267)
    assert 1.0 < rates["GBP"] < 1.6
    assert 0.005 < rates["INR"] < 0.02
    assert "NGN" not in rates  # the ECB does not publish naira


def test_parses_fallback_rates_for_currencies_ecb_skips() -> None:
    day, rates = parse_fallback((FIXTURES / "er-api-usd.json").read_bytes())

    assert day >= date(2026, 11, 4)
    assert rates["USD"] == pytest.approx(1.0)
    assert 0.0001 < rates["NGN"] < 0.01
    assert 0.001 < rates["KES"] < 0.05


def test_rejects_other_files() -> None:
    with pytest.raises(ValueError):
        parse_ecb(b"<html>maintenance</html>")
    with pytest.raises(ValueError):
        parse_fallback(b'{"result": "error"}')


RATES = {"EUR": 1.10, "GBP": 1.30, "NGN": 0.0007}


@pytest.mark.parametrize(
    ("amount", "currency", "period", "usd"),
    [
        (100_000, "USD", "year", 100_000),
        (60_000, "EUR", "year", 66_000),
        (85_000, "GBP", "year", 110_500),
        (3_500_000, "NGN", "month", 29_400),
        (50, "USD", "hour", 104_000),
    ],
)
def test_converts_to_usd_per_year(amount: float, currency: str, period: str, usd: int) -> None:
    assert usd_annual(amount, currency, period, RATES) == usd  # type: ignore[arg-type]


def test_unconvertible_or_implausible_values_give_none() -> None:
    assert usd_annual(100_000, "XYZ", "year", RATES) is None
    assert usd_annual(None, "USD", "year", RATES) is None
    assert usd_annual(5, "USD", "year", RATES) is None  # $5 a year is a parse error
    assert usd_annual(900_000_000, "USD", "year", RATES) is None
