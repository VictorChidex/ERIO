"""The fallback tasks' checks on model answers, before anything is stored."""

import pytest

from erio_core.ai.tasks import SalaryAnswer, _location, _salary, pay_snippet, stated_amounts

TEXT = "We build payments. Salary: £85k–£110k per year plus equity. We raised over $300 million."


@pytest.mark.parametrize(
    ("text", "amounts"),
    [
        ("£85k–£110k", [85000, 110000]),
        ("NGN 3.5M - 5M", [3500000, 5000000]),
        ("₹45L–₹65L", [4500000, 6500000]),
        ("€55.000 – €70.000", [55000, 70000]),
        ("$1,200.50 an hour", [1200.5]),
    ],
)
def test_stated_amounts(text: str, amounts: list[float]) -> None:
    assert stated_amounts(text) == amounts


def answer(**changes: object) -> SalaryAnswer:
    values: dict[str, object] = {
        "found": True,
        "quote": "Salary: £85k–£110k per year plus equity.",
        "min": 85000,
        "max": 110000,
        "currency": "gbp",
        "period": "year",
    }
    return SalaryAnswer.model_validate(values | changes)


def test_salary_backed_by_its_quote_is_used() -> None:
    got = _salary(answer(), TEXT)
    assert got is not None
    assert (got.min, got.max, got.currency, got.period) == (85000, 110000, "GBP", "year")


@pytest.mark.parametrize(
    "changes",
    [
        {"found": False},
        {"quote": None},
        # A sentence the job text does not contain.
        {"quote": "Salary: £90k–£120k per year."},
        # Amounts the quote does not state (e.g. copied from the instructions).
        {"min": 85000, "max": 3500000},
        # Funding is not pay, even when the amount matches.
        {"quote": "We raised over $300 million.", "min": 300000000, "max": 300000000},
        {"currency": "pounds"},
        {"min": 110000, "max": 85000, "quote": "Salary: £85k–£110k per year plus equity."},
    ],
)
def test_salary_answers_that_fail_a_check_are_dropped(changes: dict[str, object]) -> None:
    assert _salary(answer(**changes), TEXT) is None


def test_pay_snippet_only_when_pay_is_mentioned() -> None:
    assert pay_snippet("We build payments for Africa.") is None
    snippet = pay_snippet("x " * 400 + TEXT)
    assert snippet is not None and "£85k" in snippet


def test_location_answer_checks() -> None:
    from erio_core.ai.tasks import LocationAnswer

    lagos = _location(
        LocationAnswer(countries=["ng"], city="Lagos", work_type="onsite", worldwide=False)
    )
    assert lagos is not None and (lagos.country_code, lagos.city) == ("NG", "Lagos")
    assert lagos.lat is not None
    unknown = LocationAnswer(countries=["XX"], city=None, work_type="onsite", worldwide=False)
    assert _location(unknown) is None
    anywhere = LocationAnswer(countries=[], city=None, work_type="remote", worldwide=True)
    assert _location(anywhere).remote_scope == "worldwide"  # type: ignore[union-attr]
    remote_eu = LocationAnswer(
        countries=["DE", "FR"], city=None, work_type="remote", worldwide=False
    )
    result = _location(remote_eu)
    assert result is not None and result.country_code is None
    assert result.eligible_country_codes == ["DE", "FR"]
