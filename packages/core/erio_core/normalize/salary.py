"""Find the salary a job description states (spec section 6).

Reads ranges in any currency and period: "$190,400 - $285,600/yr",
"£85k–£110k", "€50.000 — €60.000 EUR", "₦3.5M–₦5M/mo", "₹45L–₹65L".
A range counts only when a pay word ("salary", "pay range", "compensation",
"base", ...) comes shortly before it, which keeps out market sizes, funding
rounds and deal sizes. The original values are kept for display; the USD
value is computed separately from daily FX rates.
"""

import html
import re
from dataclasses import dataclass

from erio_core.schemas import SalaryHint, SalaryPeriod

# Symbols and codes, longest first so "CA$" wins over "$".
SYMBOLS = {
    "US$": "USD", "C$": "CAD", "CA$": "CAD", "A$": "AUD", "AU$": "AUD", "NZ$": "NZD",
    "S$": "SGD", "HK$": "HKD", "R$": "BRL", "MX$": "MXN", "$": "USD",
    "€": "EUR", "£": "GBP", "₦": "NGN", "₹": "INR", "¥": "JPY", "₩": "KRW", "₱": "PHP",
    "₺": "TRY", "₪": "ILS", "KSh": "KES", "Ksh": "KES", "GH₵": "GHS", "₵": "GHS",
}  # fmt: skip
CODES = {
    "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "SGD", "HKD", "BRL", "MXN", "NGN", "INR",
    "JPY", "KRW", "PHP", "TRY", "ILS", "KES", "GHS", "ZAR", "EGP", "MAD", "CHF", "SEK",
    "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "AED", "SAR", "QAR", "PKR", "BDT", "IDR",
    "MYR", "THB", "VND", "CNY", "TWD", "COP", "CLP", "ARS", "PEN", "UYU", "UGX", "TZS", "RWF",
}  # fmt: skip
CODE_ALIASES = {"EURO": "EUR", "EUROS": "EUR", "DOLLARS": "USD", "POUNDS": "GBP"}

_SYMBOL = "|".join(re.escape(s) for s in sorted(SYMBOLS, key=len, reverse=True))
_CODE = "|".join(sorted(CODES | set(CODE_ALIASES), key=len, reverse=True))
# Thousands with "," "." or a space ("£200, 000" too), Indian lakh grouping
# ("12,00,000"), or a plain number.
_AMOUNT = (
    r"\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d{1,2})?"
    r"|\d{1,3}(?:(?:[,.]\s?|\s)\d{3})+(?:[.,]\d{1,2})?"
    r"|\d+(?:[.,]\d+)?"
)
# "$22/hr - $26/hr": a period may follow each amount.
_PER = r"(?:\s?/\s?(?:hr|hour|h|yr|year|mo|month|annum))?"
_MULT = r"k|K|m|M|mn|million|L|lakhs?|lacs?|Cr|crores?"
_DASH = r"\s*(?:-|\N{EN DASH}|\N{EM DASH}|to|and)\s*"

RANGE = re.compile(
    rf"(?:(?P<code1>{_CODE})\s?)?(?P<sym1>{_SYMBOL})?\s?(?P<a1>{_AMOUNT})\s?(?P<m1>{_MULT})?\b"
    rf"(?:\s?(?P<sym1b>{_SYMBOL}))?{_PER}\s?"
    rf"(?:(?P<code_mid>{_CODE})\b)?"
    rf"{_DASH}"
    rf"(?:(?P<code2>{_CODE})\s?)?(?P<sym2>{_SYMBOL})?\s?(?P<a2>{_AMOUNT})\s?(?P<m2>{_MULT})?\b"
    rf"(?:\s?(?P<sym2b>{_SYMBOL}))?{_PER}"
    rf"(?:\s?(?P<code3>{_CODE})\b)?"
)
# Pay words in the languages job ads commonly use, and the money-bag emoji
# some boards put before the range.
PAY_WORDS = re.compile(
    r"\b(salary|salaries|pay|compensation|base|wage|wages|remuneration|ote|earnings|stipend|"
    r"hourly rate|pay range|pay band|package|ctc|sal[aá]rio|salario|sueldo|gehalt|salaire|"
    r"r[eé]mun[eé]ration|remunera[cç][aã]o|maa[sş])\b|\N{MONEY BAG}",
    re.IGNORECASE,
)
NOT_PAY = re.compile(
    r"^\s*\+?\s*(?:billion|bn|b\b|in (?:annual|payment|assets|revenue)|market|valuation|"
    r"revenue|arr|deals?|of (?:payment|transaction))",
    re.IGNORECASE,
)
HOUR = re.compile(r"(/\s?(?:hr|hour|h)\b|per hour|an hour|hourly|/hora)", re.IGNORECASE)
MONTH = re.compile(
    r"(/\s?(?:mo|month)\b|per month|a month|monthly|p\.?m\.?\b|/mes|por m[eê]s|al mes|mensual|"
    r"mensal|monatlich|par mois|ayl[ıi]k)",
    re.IGNORECASE,
)
YEAR = re.compile(
    r"(/\s?(?:yr|year|annum)\b|per (?:year|annum)|a year|annual|annually|yearly|p\.?a\.?\b|"
    r"pro jahr|j[aä]hrlich|par an|al a[nñ]o|anual|por ano|y[ıi]ll[ıi]k)",
    re.IGNORECASE,
)
MULTIPLIERS = {
    "k": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "l": 1e5, "lakh": 1e5, "lakhs": 1e5,
    "lac": 1e5, "lacs": 1e5, "cr": 1e7, "crore": 1e7, "crores": 1e7,
}  # fmt: skip
TAGS = re.compile(r"<[^>]+>")
PAY_WINDOW = 160


@dataclass(frozen=True)
class _Candidate:
    low: float
    high: float
    currency: str | None
    period: SalaryPeriod | None
    stated: bool
    text: str


def html_to_text(content: str) -> str:
    text = html.unescape(TAGS.sub(" ", html.unescape(content)))
    return re.sub(r"\s+", " ", text).strip()


def _amount(raw: str, multiplier: str | None, euro_style: bool) -> float:
    raw = re.sub(r"\s", "", raw)
    if euro_style:
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):
        raw = raw.replace(".", "")  # "60.000": thousands, not a decimal
    else:
        raw = raw.replace(",", "")
    value = float(raw)
    return value * MULTIPLIERS.get((multiplier or "").lower(), 1.0)


def _currency(match: re.Match[str]) -> str | None:
    for group in ("code1", "code_mid", "code2", "code3"):
        code = match.group(group)
        if code:
            return CODE_ALIASES.get(code.upper(), code.upper())
    for group in ("sym1", "sym2", "sym1b", "sym2b"):
        symbol = match.group(group)
        if symbol:
            return SYMBOLS[symbol]
    return None


def _period(text: str, start: int, end: int, high: float) -> tuple[SalaryPeriod | None, bool]:
    """The period and whether the text states it (False: guessed from a small number)."""
    inside, after = text[start:end], text[end : end + 40]
    before = text[max(0, start - 80) : start]
    for window in (inside, after, before):
        if HOUR.search(window):
            return "hour", True
        if MONTH.search(window):
            return "month", True
        if YEAR.search(window):
            return "year", True
    if high < 300:
        return "hour", False
    return None, False


def _candidates(text: str) -> list[_Candidate]:
    found = []
    for match in RANGE.finditer(text):
        currency = _currency(match)
        if currency is None:
            continue  # bare numbers ("5 - 10 years") are not pay
        if NOT_PAY.match(text[match.end() : match.end() + 30]):
            continue
        if not PAY_WORDS.search(text[max(0, match.start() - PAY_WINDOW) : match.start()]):
            continue
        euro_style = currency in {"EUR", "BRL"} and bool(re.search(r"\d\.\d{3},\d", match.group(0)))
        m1, m2 = match.group("m1"), match.group("m2")
        try:
            # "$235–$317k": a multiplier on the second amount applies to both.
            low = _amount(match.group("a1"), m1 or m2, euro_style)
            high = _amount(match.group("a2"), m2 or m1, euro_style)
        except ValueError:
            continue
        if low <= 0 or high <= 0:
            continue
        low, high = min(low, high), max(low, high)
        period, stated = _period(text, match.start(), match.end(), high)
        found.append(_Candidate(low, high, currency, period, stated, match.group(0).strip()))
    return found


def parse_salary(description: str | None) -> SalaryHint | None:
    """The first stated salary range in a description, or None."""
    if not description:
        return None
    text = html_to_text(description) if "<" in description or "&" in description else description
    candidates = _candidates(text)
    if not candidates:
        return None
    best = candidates[0]
    return SalaryHint(
        min=round(best.low),
        max=round(best.high),
        currency=best.currency,
        period=best.period or "year",
        period_stated=best.stated,
        text=best.text,
    )
