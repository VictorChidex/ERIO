"""Small readers shared by the connectors."""

import html
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import HttpUrl

from erio_core.schemas import SalaryHint, SalaryPeriod

PERIOD_WORDS: dict[str, SalaryPeriod] = {
    "year": "year", "annual": "year", "month": "month", "hour": "hour"
}  # fmt: skip

BOLD = re.compile(r"\*\*(.+?)\*\*")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
BULLET = re.compile(r"[-*+] (.*)")
HEADING = re.compile(r"#{1,6}\s+(.*)")
AMOUNT = re.compile(r"\d[\d,]*(?:\.\d+)?")


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


def epoch_seconds(value: Any) -> datetime | None:
    """Unix seconds, as a number or a numeric string."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(seconds, tz=UTC) if seconds > 0 else None


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


# Country-code domains whose sites hire in their own country. Others (".io", ".co", ".ai") are
# not country domains in practice and are left out on purpose.
COUNTRY_DOMAINS = {
    "uk": "GB", "ie": "IE", "au": "AU", "nz": "NZ", "ca": "CA", "de": "DE", "fr": "FR",
    "nl": "NL", "be": "BE", "es": "ES", "pt": "PT", "it": "IT", "ch": "CH", "at": "AT",
    "se": "SE", "no": "NO", "dk": "DK", "fi": "FI", "pl": "PL", "in": "IN", "sg": "SG",
    "za": "ZA", "ng": "NG", "ke": "KE", "br": "BR", "mx": "MX", "ae": "AE",
}  # fmt: skip


def host_country(url: str) -> str | None:
    """The country a site's domain names ("www.example.co.uk" is GB), or None."""
    host = (urlsplit(url).hostname or "").lower()
    return COUNTRY_DOMAINS.get(host.rsplit(".", 1)[-1]) if "." in host else None


def as_url(value: str) -> HttpUrl:
    """An apply link as a URL. ERIO links candidates only to https pages, so a source
    that publishes ``http://`` gets its https twin (sites redirect there anyway)."""
    text = value.strip()
    if text[:7].lower() == "http://":
        text = "https://" + text[7:]
    return HttpUrl(text)


def numbers_in(text: str | None, limit: int = 2) -> list[float]:
    """The first amounts written in a string: "160,000–200,000 + equity" is 160000, 200000."""
    return [float(n.replace(",", "")) for n in AMOUNT.findall(text or "")][:limit]


def markdown_to_html(text: str | None) -> str | None:
    """Headings, bullets, bold, links and paragraphs: the Markdown job boards store."""
    if not text or not text.strip():
        return None

    def inline(line: str) -> str:
        line = html.escape(line, quote=False)
        line = BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", line)
        return LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', line)

    out: list[str] = []
    bullets = False
    for line in text.splitlines():
        stripped = line.strip()
        item = BULLET.match(stripped)
        if bullets and not item:
            out.append("</ul>")
            bullets = False
        if item:
            if not bullets:
                out.append("<ul>")
                bullets = True
            out.append(f"<li>{inline(item.group(1))}</li>")
        elif heading := HEADING.match(stripped):
            out.append(f"<h3>{inline(heading.group(1))}</h3>")
        elif stripped:
            out.append(f"<p>{inline(stripped)}</p>")
    if bullets:
        out.append("</ul>")
    return "".join(out)


def join_html(*parts: str | None) -> str | None:
    joined = "".join(part for part in parts if part)
    return joined or None
