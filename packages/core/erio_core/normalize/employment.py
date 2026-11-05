"""Employment type from however a source words it (spec: keep it when given)."""

import re

from erio_core.schemas import EmploymentType

# Checked in order: "part-time contract" is a contract, "full-time intern" an internship.
RULES: list[tuple[EmploymentType, re.Pattern[str]]] = [
    ("internship", re.compile(r"intern|trainee|apprentic|werkstudent|stage|practicum", re.I)),
    ("volunteer", re.compile(r"volunt", re.I)),
    ("temporary", re.compile(r"temp|seasonal|fixed[ _-]?term|casual", re.I)),
    ("contract", re.compile(r"contract|freelance|consult|per diem", re.I)),
    ("part_time", re.compile(r"part[ _-]?time|parttime|teilzeit", re.I)),
    ("full_time", re.compile(r"full[ _-]?time|fulltime|permanent|regular|vollzeit|cdi", re.I)),
]


def employment_type(text: str | None) -> EmploymentType | None:
    """ "FULL_TIME" and "Full-time, permanent" are full_time; unknown wording is None."""
    if not text:
        return None
    return next((kind for kind, pattern in RULES if pattern.search(text)), None)
