"""The normalizer's AI fallback tasks: role, location and salary (spec section 13).

Each task asks for a small JSON answer and checks it before use: a country
code must be one of the 233, a currency three letters, a range low before
high. A salary must come with the sentence it was read from, which must be
in the job text and contain both amounts, so a model cannot invent a pay
range or mistake funding for pay. The rules engine always runs first; these
run only where it found nothing, and their answers replace nothing it did
find.
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from erio_core.ai.gateway import Gateway
from erio_core.ai.types import Message
from erio_core.normalize.gazetteer import gazetteer
from erio_core.normalize.location import LocationResult, resolve_location
from erio_core.schemas import RemoteStatus, RoleCategory, SalaryHint, SalaryPeriod

ROLE_HELP = (
    "engineering: software, hardware, infrastructure, security, QA. "
    "product: product and program managers. design: product, UX, graphic and brand design. "
    "data: data science, analytics, machine learning research, BI. "
    "operations: finance, legal, people, recruiting, risk, compliance, customer support "
    "and success, admin, supply chain. sales: account executives, business development, "
    "sales engineers, partnerships. marketing: marketing, communications, content, growth. "
    "healthcare: nurses, doctors, clinicians, caregivers, pharmacy, dental, lab and therapy. "
    "education: teachers, lecturers, tutors, coaches, instructors. "
    "hospitality: cooks, chefs, servers, baristas, hotel and restaurant staff. "
    "retail: store staff, cashiers, store managers, merchandisers. "
    "logistics: drivers, warehouse, delivery, courier, cabin crew. "
    "trades: mechanics, electricians, construction, production, maintenance, cleaning. "
    "security: guards and protective services. "
    "other: anything else."
)

# A sentence that talks about pay, for deciding whether a salary is worth asking for.
PAY_CUE = re.compile(
    r"(salary|compensation|pay range|base pay|per (?:year|annum|month|hour)|"
    r"[$€£₦₹¥]\s?\d|\b(?:USD|EUR|GBP|NGN|INR|KES|ZAR|BRL|MXN|CAD|AUD)\s?\d)",
    re.IGNORECASE,
)
PAY_WINDOW = 600


class RoleAnswer(BaseModel):
    role: RoleCategory


class LocationAnswer(BaseModel):
    countries: list[str] = Field(
        description="ISO 3166-1 alpha-2 codes of the countries the job is in or open to"
    )
    city: str | None = None
    work_type: RemoteStatus
    worldwide: bool = Field(description="A remote job open to people in any country")


class SalaryAnswer(BaseModel):
    found: bool
    quote: str | None = Field(
        default=None, description="The sentence stating the salary, copied exactly from the text"
    )
    min: int | None = None
    max: int | None = None
    currency: str | None = Field(default=None, description="ISO 4217 code")
    period: SalaryPeriod | None = None


@dataclass(frozen=True)
class Outcome[T]:
    """Whether a model answered at all, and the usable value it gave (if any).

    ``answered`` False means no model was available (switched off, over
    budget, every provider down): the job should be tried again later.
    """

    answered: bool
    value: T | None = None


def _ask(instructions: str, text: str) -> list[Message]:
    return [Message("system", instructions), Message("user", text)]


def role_messages(title: str, departments: list[str]) -> list[Message]:
    return _ask(
        "Classify the job into one role category. Categories: " + ROLE_HELP,
        f"Title: {title}\nDepartments: {', '.join(departments) or 'none'}",
    )


def location_messages(location_text: str, title: str) -> list[Message]:
    return _ask(
        "Read where a job is. Give the countries it is in (or, for a remote job, the "
        "countries it accepts) as ISO 3166-1 alpha-2 codes, the city if one is named, and "
        "whether it is remote, hybrid or onsite. A remote job open anywhere is worldwide "
        "with no countries. If the text names no place at all, give no countries and "
        "worldwide false. Never guess a country the text does not support.",
        f"Location: {location_text}\nJob title: {title}",
    )


def salary_messages(snippet: str) -> list[Message]:
    return _ask(
        "Does this job ad excerpt state the pay for the job itself? If it does, copy the "
        "sentence that states it exactly as written, and give the minimum and maximum as "
        "whole numbers with any k or million written out, the ISO 4217 currency and the "
        "period (year, month or hour). Company funding, revenue, deal sizes, budgets and "
        "market sizes are not pay. If the excerpt states no pay for the job, found is "
        "false. Never estimate.",
        snippet,
    )


def ai_role(gateway: Gateway, title: str, departments: list[str]) -> Outcome[RoleCategory]:
    answer = gateway.complete("role", role_messages(title, departments), RoleAnswer)
    return Outcome(True, answer.value.role) if answer else Outcome(False)


def ai_location(gateway: Gateway, location_text: str, title: str) -> Outcome[LocationResult]:
    answer = gateway.complete("location", location_messages(location_text, title), LocationAnswer)
    if answer is None:
        return Outcome(False)
    return Outcome(True, _location(answer.value))


def _location(value: LocationAnswer) -> LocationResult | None:
    """The answer as a resolved location, or None when it names no usable place."""
    if value.worldwide and value.work_type == "remote":
        return LocationResult(None, None, None, None, None, "remote", "worldwide", [])
    countries = gazetteer().countries
    codes = list(dict.fromkeys(c.upper() for c in value.countries if c.upper() in countries))
    if not codes:
        return None
    # The gazetteer fills the city's region and coordinates, as for rule results.
    hint = ", ".join(part for part in (value.city, countries[codes[0]].name) if part)
    result = resolve_location(hint, workplace_type=value.work_type)
    if result.review_reason or result.country_code not in (codes[0], None):
        return None
    if len(codes) > 1:
        scope = "region" if value.work_type == "remote" else result.remote_scope
        return LocationResult(
            None if value.work_type == "remote" else codes[0],
            result.city,
            result.region,
            result.lat,
            result.lon,
            result.remote_status,
            scope,
            codes,
        )
    return result


def pay_snippet(description_text: str | None) -> str | None:
    """The part of a description that talks about pay, or None if none does."""
    found = PAY_CUE.search(description_text or "")
    if not found or description_text is None:
        return None
    start = max(found.start() - PAY_WINDOW // 3, 0)
    return description_text[start : start + PAY_WINDOW]


def ai_salary(gateway: Gateway, description_text: str | None) -> Outcome[SalaryHint]:
    """Asks only when the text talks about pay; otherwise answered with nothing."""
    snippet = pay_snippet(description_text)
    if snippet is None:
        return Outcome(True)
    answer = gateway.complete("salary", salary_messages(snippet), SalaryAnswer)
    if answer is None:
        return Outcome(False)
    return Outcome(True, _salary(answer.value, snippet))


AMOUNT = re.compile(
    r"(\d+(?:[.,]\d+)*)\s*(k|m|mn|million|thousand|lakhs?|lacs?|l|cr|crores?)?\b",
    re.IGNORECASE,
)
MULTIPLIERS = {
    "k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
    "l": 1e5, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "cr": 1e7, "crore": 1e7,
    "crores": 1e7,
}  # fmt: skip


def stated_amounts(text: str) -> list[float]:
    """Every amount written in ``text``, with k, million, lakh and crore applied."""
    found = []
    for digits, unit in AMOUNT.findall(text):
        # "85,000" and "85.000" are thousands; "3.5" is a decimal.
        last = re.split(r"[.,]", digits)[-1]
        number = (
            digits.replace(",", "").replace(".", "") if len(last) == 3 else digits.replace(",", "")
        )
        try:
            found.append(float(number) * MULTIPLIERS.get(unit.lower(), 1))
        except ValueError:
            continue
    return found


# A sentence that states pay names it: "salary", "base pay", "per year", "/hr"...
PAY_WORDS = re.compile(
    r"\b(salary|salaries|pay|paid|compensation|wage|wages|remuneration|stipend|ote|"
    r"per (?:year|annum|month|hour)|annual|annually|monthly|hourly|a year|a month|an hour)\b"
    r"|/\s?(?:yr|year|mo|month|hr|hour|h)\b",
    re.IGNORECASE,
)


def _squash(text: str) -> str:
    return " ".join(text.split()).casefold()


def _salary(value: SalaryAnswer, snippet: str) -> SalaryHint | None:
    if not value.found or not value.quote or _squash(value.quote) not in _squash(snippet):
        return None
    if not PAY_WORDS.search(value.quote):
        return None
    amounts = stated_amounts(value.quote)
    for amount in (value.min, value.max):
        if amount is not None and not any(abs(a - amount) <= 0.005 * amount for a in amounts):
            return None
    low, high = value.min, value.max
    currency = (value.currency or "").upper()
    if (low is None and high is None) or not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    if low is not None and high is not None and low > high:
        return None
    return SalaryHint(min=low, max=high, currency=currency, period=value.period or "year")
