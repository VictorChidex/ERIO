"""Turn one parsed posting into the fields of a canonical job (spec section 6)."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from erio_core.normalize.fx import usd_annual
from erio_core.normalize.location import LocationResult, resolve_location
from erio_core.normalize.roles import classify_role
from erio_core.normalize.salary import parse_salary
from erio_core.normalize.text import clean_title, html_to_text, sanitize_html
from erio_core.schemas import PartialJob, RoleCategory, SalaryHint


def canonical_id(source_slug: str, external_id: str) -> str:
    """Stable job ID for a posting; dedup (step 8) may later merge several into one."""
    digest = hashlib.sha256(f"{source_slug}:{external_id}".encode()).hexdigest()
    return f"j_{digest[:20]}"


@dataclass(frozen=True)
class NormalizedJob:
    canonical_id: str
    title: str
    role_category: RoleCategory
    location_text: str | None
    location: LocationResult
    salary: SalaryHint | None
    salary_usd_annual_min: int | None
    description_html: str | None
    description_text: str | None
    apply_url: str

    def columns(self) -> dict[str, object]:
        """Values for the ``jobs`` table (company and status are set by the caller)."""
        loc, pay = self.location, self.salary
        return {
            "canonical_id": self.canonical_id,
            "title": self.title,
            "role_category": self.role_category,
            "location_text": self.location_text,
            "city": loc.city,
            "region": loc.region,
            "country_code": loc.country_code,
            "lat": loc.lat,
            "lon": loc.lon,
            "remote_status": loc.remote_status,
            "remote_scope": loc.remote_scope,
            "eligible_country_codes": loc.eligible_country_codes,
            "salary_min": pay.min if pay else None,
            "salary_max": pay.max if pay else None,
            "salary_currency": pay.currency if pay else None,
            "salary_period": pay.period if pay else None,
            "salary_usd_annual_min": self.salary_usd_annual_min,
            "apply_url": self.apply_url,
            "description_html": self.description_html,
            "description_text": self.description_text,
            "review_reason": loc.review_reason,
        }


def normalize(partial: PartialJob, usd_per_unit: Mapping[str, float]) -> NormalizedJob:
    location = resolve_location(
        partial.location_text,
        city_hint=partial.city,
        country_hint=partial.country_hint,
        workplace_type=partial.workplace_type,
    )
    salary = partial.salary or parse_salary(partial.description_html)
    low = salary.min if salary and salary.min is not None else (salary.max if salary else None)
    title = clean_title(partial.title)
    return NormalizedJob(
        canonical_id=canonical_id(partial.source_slug, partial.external_id),
        title=title,
        role_category=classify_role(title, partial.departments),
        location_text=(partial.location_text or "").strip() or None,
        location=location,
        salary=salary,
        salary_usd_annual_min=usd_annual(
            low,
            salary.currency if salary else None,
            salary.period if salary else None,
            usd_per_unit,
        ),
        description_html=sanitize_html(partial.description_html)
        if partial.description_html
        else None,
        description_text=html_to_text(partial.description_html)
        if partial.description_html
        else None,
        apply_url=str(partial.apply_url),
    )
