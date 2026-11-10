"""Which company a posting belongs to.

A single-employer board (Greenhouse, Lever, ...) belongs to one company, registered with it. Its
name may be a placeholder made from the board token ("Acme" from ``acme``); the first postings
that carry the employer's own name replace it (``adopt_source_name``). A multi-employer job
board lists many employers' jobs, so each job takes the company its posting names, found or
created by slug (``resolve_company``).

Two spellings of one employer must land on one company: "Acme Ltd.", "ACME" and "Acme, Inc"
share the key ``acme``. The key is the slug of the name with legal-form words (Ltd, GmbH, Inc,
S.A. ...) dropped from its end; it never leaves a name empty.
"""

import re
import unicodedata

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from erio_core.db.models import Company
from erio_core.slugs import slugify

NAME_MAX = 200
# Legal forms and the words around them, dropped from the end of a name for its key.
LEGAL_SUFFIXES = frozenset(
    "ltd limited llc llp lp lc inc incorporated corp corporation co company gmbh ag kg ug se sa "
    "sas sarl srl spa bv nv plc pty pvt ltda sl oy oyj ab as aps ohg ev pllc pc".split()
)
# What boards print when the employer hides its name; such a job keeps the board's company.
UNNAMED = frozenset(
    "confidential anonymous anonym undisclosed unknown private hidden various company employer "
    "recruiter agency n/a na none tbd tba null undefined not specified".split()
)


def clean_company_name(name: str | None) -> str | None:
    """A company name as written, tidied; None when it names no one."""
    if not name:
        return None
    text = re.sub(r"\s+", " ", name).strip(" \t\r\n,;|-")
    if not re.search(r"[^\W_]", text) or text.lower() in UNNAMED:
        return None
    return text[:NAME_MAX].strip()


def company_key(name: str) -> str:
    """The slug under which every spelling of a company's name meets."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    # "S.A." and "Pvt." lose their dots first, so they read as the words sa and pvt.
    words = re.findall(r"[a-z0-9]+", re.sub(r"(?<=\w)\.", "", folded))
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return slugify(" ".join(words)) if words else slugify(name)


def resolve_company(session: Session, name: str | None) -> int | None:
    """The company a multi-employer posting names, created on first sight; None if it names none.

    Safe against two workers meeting a new employer at once: the slug is unique, the second
    insert does nothing and both read the one row.
    """
    clean = clean_company_name(name)
    if clean is None:
        return None
    slug = company_key(clean)
    found = session.execute(select(Company.id, Company.name_source).where(Company.slug == slug))
    row = found.one_or_none()
    if row is None:
        company_id = session.scalar(
            insert(Company)
            .values(name=clean, slug=slug, name_source="source")
            .on_conflict_do_nothing(index_elements=["slug"])
            .returning(Company.id)
        )
        if company_id is not None:
            return int(company_id)
        row = session.execute(
            select(Company.id, Company.name_source).where(Company.slug == slug)
        ).one()
    company_id, name_source = row
    if name_source == "placeholder":
        adopt_source_name(session, company_id, clean)
    return int(company_id)


def adopt_source_name(session: Session, company_id: int, name: str | None) -> bool:
    """Replace a placeholder company name by the one a posting carries; never a seed name.

    The condition is in the statement, so a name another worker already set is not overwritten.
    """
    clean = clean_company_name(name)
    if clean is None:
        return False
    values: dict[str, str] = {"name": clean, "name_source": "source"}
    # A placeholder's slug was made from the board token ("talentreef-board-22144"), and no
    # page has been indexed under it that anyone relies on: it follows the real name, unless
    # another company already has that slug.
    slug = company_key(clean)
    if not session.scalar(select(Company.id).where(Company.slug == slug)):
        values["slug"] = slug
    result = session.execute(
        update(Company)
        .where(Company.id == company_id, Company.name_source == "placeholder")
        .values(**values)
    )
    return bool(getattr(result, "rowcount", 0))
