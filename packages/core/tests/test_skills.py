"""The CV-match lexicon and extraction: no model, every match traceable to words."""

import json
import time
from collections import Counter
from importlib.resources import files

import pytest

from erio_core import skills
from erio_core.skills import apply_kit, compare, extract_skills, lexicon


def test_lexicon_is_well_formed() -> None:
    lex = lexicon()
    assert len(lex.skills) >= 300
    categories = {s.cat for s in lex.skills.values()}
    assert categories <= set(skills.WEIGHTS)
    assert {"licence", "certification", "language", "tech", "trade"} <= categories
    # An alias that pointed at two skills would make a match ambiguous.
    raw = json.loads(files("erio_core").joinpath("data/skills.json").read_text(encoding="utf-8"))
    ids = Counter(row["id"] for row in raw["skills"])
    assert [i for i, n in ids.items() if n > 1] == []
    seen: dict[str, str] = {}
    for row in raw["skills"]:
        for alias in row.get("aliases", []):
            key = alias.lower()
            assert seen.setdefault(key, row["id"]) == row["id"], f"alias {alias!r} is in two skills"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Experienced Registered Nurse with BLS and ACLS", {"rn", "bls", "acls"}),
        ("Holds a valid Class A CDL and forklift certificate", {"cdl", "forklift"}),
        ("We use Python, SQL and Docker on AWS", {"python", "sql", "docker", "aws"}),
        ("C++ and C# developer", {"cpp", "csharp"}),
        ("Node.js, .NET and ASP.NET", {"nodejs", "dotnet"}),
        ("Fluent in French and Spanish; basic German", {"french", "spanish", "german"}),
        (
            "ACCA part-qualified, IFRS reporting, month-end close",
            {"acca", "ifrs", "reconciliation"},
        ),
        ("MIG and TIG welding, reading blueprints", {"welding", "blueprint"}),
        ("operates forklifts and reach trucks", {"forklift"}),
        ("Driver's licence required (clean driving record)", {"drivers_licence"}),
    ],
)
def test_finds_skills_on_word_boundaries(text: str, expected: set[str]) -> None:
    assert expected <= set(extract_skills(text))


@pytest.mark.parametrize(
    "text",
    [
        "JavaScript only",  # contains "java" but it is not the word java
        "the mysql and postgresql databases",  # "sql" inside other words
        "a nurse practitioner partnered with rnd labs",  # "rn" inside words
        "they cpa-ssed it",  # case-sensitive acronym inside a word
        "scalability matters",  # "scala" inside a word
    ],
)
def test_never_matches_inside_other_words(text: str) -> None:
    found = set(extract_skills(text))
    assert "java" not in found
    assert "rn" not in found
    assert "cpa" not in found
    assert "scala" not in found
    if "sql" in text and "mysql" not in text:
        assert "sql" not in found


def test_case_sensitive_acronyms_ignore_common_words() -> None:
    assert "rn" not in extract_skills("rn is texting shorthand")
    assert "rn" in extract_skills("Licensed RN needed")
    assert "excel" not in extract_skills("you will excel at selling")
    assert "excel" in extract_skills("Strong Microsoft Excel skills")
    assert "react" not in extract_skills("you will react quickly")
    assert "react" in extract_skills("React and TypeScript")


def test_order_and_uniqueness() -> None:
    found = extract_skills("Docker first, then Python, then docker again")
    assert found == ["docker", "python"]


def test_empty_and_huge_inputs_are_safe() -> None:
    assert extract_skills("") == []
    start = time.perf_counter()
    assert "python" in extract_skills("python " + "lorem ipsum dolor sit amet " * 5000)
    assert time.perf_counter() - start < 2.0


def test_scanning_a_job_ad_is_fast() -> None:
    ad = (
        "Responsibilities include patient care, wound care and medication administration. " * 80
    ) + "RN BLS"
    start = time.perf_counter()
    for _ in range(50):
        extract_skills(ad)
    assert time.perf_counter() - start < 3.0


def test_compare_weights_licences_and_explains() -> None:
    result = compare(["python", "sql"], ["python", "sql", "docker", "aws"])
    assert result.matched == ["python", "sql"] and result.missing == ["docker", "aws"]
    assert result.explanation() == ("matched: Python, SQL; the job also asks for: Docker, AWS")
    full = compare(["rn", "bls"], ["rn", "bls"])
    partial = compare(["bls"], ["rn", "bls"])
    assert full.score > partial.score > 0
    assert compare(["python"], ["rn"]).score == 0
    # One named skill the CV has does not read as a perfect fit.
    assert compare(["english"], ["english"]).score < 70


def test_apply_kit_is_plain_text_from_the_matches() -> None:
    kit = apply_kit(
        title="Staff Nurse",
        company="Acme Hospital",
        matched=["bls"],
        missing=["rn"],
        required=["rn", "bls"],
    )
    assert "Staff Nurse at Acme Hospital" in kit
    assert "[ ] Show evidence of Basic life support (BLS)" in kit
    assert "licence or certificate Registered nurse (RN)" in kit
    assert "ERIO stores neither and never applies" in kit
