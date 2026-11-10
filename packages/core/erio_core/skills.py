"""Skill extraction and CV matching with a curated lexicon, no AI model (workspace CV match).

``data/skills.json`` lists skills, tools, licences, certifications and languages across tech and
non-tech work, each with aliases. ``extract_skills`` finds them in any text on word boundaries,
so the same code reads a CV and a job description, and every match can be explained by pointing
at the words that produced it.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any

# What a skill is worth when judging how well a CV covers a job. A licence or certificate is a
# gate a person either holds or does not; a general skill is softer.
WEIGHTS = {
    "licence": 3,
    "certification": 3,
    "language": 2,
    "standard": 2,
    "tech": 2,
    "tool": 2,
    "trade": 2,
    "skill": 1,
}
# A job names only some of what it expects. Counting this many points of unnamed expectations
# keeps a job that asks only for English from scoring 100 when the CV mentions English.
PRIOR_WEIGHT = 2
MAX_TEXT_CHARS = 60_000
LISTED = 8


@dataclass(frozen=True)
class Skill:
    id: str
    label: str
    cat: str

    @property
    def weight(self) -> int:
        return WEIGHTS[self.cat]


# Curly quotes and long dashes, as word processors write them, become plain ones.
_PUNCTUATION = str.maketrans({0x2019: "'", 0x2018: "'", 0x2013: "-", 0x2014: "-"})


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text[:MAX_TEXT_CHARS])
    text = text.translate(_PUNCTUATION)
    return re.sub(r"\s+", " ", text)


def _trie(words: list[str]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for word in words:
        node = root
        for char in word:
            node = node.setdefault(char, {})
        node[""] = True
    return root


def _trie_pattern(node: dict[str, Any]) -> str:
    """A regex for the words in the trie. Shared prefixes keep scanning fast with 2,000 aliases."""
    branches = [
        re.escape(char) + _trie_pattern(child) for char, child in sorted(node.items()) if char
    ]
    if not branches:
        return ""
    body = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
    return f"(?:{body})?" if "" in node else body


def _compile(words: list[str], flags: int) -> re.Pattern[str] | None:
    if not words:
        return None
    # Word boundaries on both sides; an optional plural ending so "forklifts" finds "forklift".
    pattern = r"(?<!\w)" + _trie_pattern(_trie(words)) + r"(?:es|s)?(?!\w)"
    return re.compile(pattern, flags)


@dataclass(frozen=True)
class Lexicon:
    skills: dict[str, Skill]
    alias_ids: dict[str, str]  # lower-case alias -> skill id
    exact_ids: dict[str, str]  # case-sensitive alias -> skill id
    insensitive: re.Pattern[str] | None
    exact: re.Pattern[str] | None


@lru_cache
def lexicon() -> Lexicon:
    raw = json.loads(files("erio_core").joinpath("data/skills.json").read_text(encoding="utf-8"))
    skills: dict[str, Skill] = {}
    alias_ids: dict[str, str] = {}
    exact_ids: dict[str, str] = {}
    for row in raw["skills"]:
        skill = Skill(row["id"], row["label"], row["cat"])
        skills[skill.id] = skill
        for alias in row.get("aliases", []):
            alias_ids[_normalize(alias).lower()] = skill.id
        for alias in row.get("exact", []):
            exact_ids[_normalize(alias)] = skill.id
    return Lexicon(
        skills,
        alias_ids,
        exact_ids,
        _compile(sorted(alias_ids), re.IGNORECASE),
        _compile(sorted(exact_ids), 0),
    )


def _lookup(table: dict[str, str], found: str) -> str | None:
    # The pattern allows a plural ending the alias does not spell; try the word without it.
    for candidate in (found, found[:-1], found[:-2]):
        if candidate and candidate in table:
            return table[candidate]
    return None


def extract_skills(text: str) -> list[str]:
    """Skill ids found in ``text``, in order of first appearance, each once."""
    lex = lexicon()
    text = _normalize(text)
    hits: dict[str, int] = {}
    if lex.insensitive is not None:
        for match in lex.insensitive.finditer(text):
            skill_id = _lookup(lex.alias_ids, match.group(0).lower())
            if skill_id:
                hits.setdefault(skill_id, match.start())
    if lex.exact is not None:
        for match in lex.exact.finditer(text):
            skill_id = _lookup(lex.exact_ids, match.group(0))
            if skill_id:
                hits.setdefault(skill_id, match.start())
    return sorted(hits, key=lambda skill_id: hits[skill_id])


def skill_for(skill_id: str) -> Skill | None:
    return lexicon().skills.get(skill_id)


def known_ids(ids: list[str]) -> list[str]:
    """``ids`` without anything the lexicon does not list, duplicates removed, order kept."""
    skills = lexicon().skills
    return [skill_id for skill_id in dict.fromkeys(ids) if skill_id in skills]


def search_phrases(ids: list[str], limit: int = 120) -> list[str]:
    """Phrases to look for in job text for these skills (used to fetch candidate jobs)."""
    lex = lexicon()
    wanted = set(ids)
    phrases = [alias for alias, skill_id in lex.alias_ids.items() if skill_id in wanted]
    phrases += [alias.lower() for alias, skill_id in lex.exact_ids.items() if skill_id in wanted]
    return list(dict.fromkeys(phrases))[:limit]


@dataclass(frozen=True)
class Match:
    score: int  # 0..100
    matched: list[str]
    missing: list[str]

    def explanation(self) -> str:
        return explain(self.matched, self.missing)


def _names(ids: list[str]) -> str:
    labels = [s.label for skill_id in ids if (s := skill_for(skill_id))]
    shown = ", ".join(labels[:LISTED])
    return shown + (f" and {len(labels) - LISTED} more" if len(labels) > LISTED else "")


def explain(matched: list[str], missing: list[str]) -> str:
    """The reason for a match, in words: what the CV covers and what the job also asks for."""
    parts = []
    parts.append(f"matched: {_names(matched)}" if matched else "matched: nothing recognised")
    if missing:
        parts.append(f"the job also asks for: {_names(missing)}")
    return "; ".join(parts)


def compare(cv_ids: list[str], job_ids: list[str]) -> Match:
    """How well a CV's skills cover a job's. Weighted by how much each skill gates the job."""
    have = set(cv_ids)
    matched = [skill_id for skill_id in job_ids if skill_id in have]
    missing = [skill_id for skill_id in job_ids if skill_id not in have]

    def weight(ids: list[str]) -> int:
        return sum(s.weight for skill_id in ids if (s := skill_for(skill_id)))

    total = weight(job_ids)
    score = round(100 * weight(matched) / (total + PRIOR_WEIGHT)) if matched else 0
    return Match(score, matched, missing)


def by_weight(ids: list[str]) -> list[str]:
    """Most gating skills first (licences, certificates), stable within a weight."""
    return sorted(ids, key=lambda skill_id: -(s.weight if (s := skill_for(skill_id)) else 0))


def apply_kit(
    *, title: str, company: str, matched: list[str], missing: list[str], required: list[str]
) -> str:
    """A plain-text checklist and cover-note outline for one job. Nothing is sent anywhere."""
    lines = [f"Apply kit: {title} at {company}", ""]
    lines.append("Checklist")
    lines.append("[ ] Read the full posting once more and note the closing date")
    lines.append("[ ] Tailor your CV: lead with the skills below that you already have")
    for skill_id in by_weight(matched):
        if skill := skill_for(skill_id):
            lines.append(f"[ ] Show evidence of {skill.label} (a role, a result, a number)")
    for skill_id in by_weight(missing):
        if skill := skill_for(skill_id):
            kind = (
                "licence or certificate" if skill.cat in ("licence", "certification") else "skill"
            )
            lines.append(
                f"[ ] Check the {kind} {skill.label}: do you hold it? If not, say how you will"
            )
    lines.append("[ ] Proof-read, then apply on the employer's own page")
    lines += ["", "Cover note outline"]
    lines.append(f"1. Opening: why {company}, and why this {title} role, in one sentence")
    top = [s.label for skill_id in by_weight(matched)[:3] if (s := skill_for(skill_id))]
    if top:
        lines.append(f"2. Fit: your strongest overlap with the job: {', '.join(top)}")
    else:
        lines.append("2. Fit: your closest experience to what the job asks for")
    lines.append("3. One concrete result from your past work, with a number if you have one")
    gaps = [s.label for skill_id in by_weight(missing)[:3] if (s := skill_for(skill_id))]
    if gaps:
        lines.append(
            f"4. Gaps: be honest about {', '.join(gaps)} and how you are learning or covering it"
        )
    else:
        lines.append("4. Availability, location and notice period")
    lines.append("5. Close: thank them and say when you can talk")
    if required:
        lines += ["", f"Requirements ERIO recognised in the posting: {_names(required)}"]
    lines += [
        "",
        "Built from the posting and the skills you shared. ERIO stores neither and never applies.",
    ]
    return "\n".join(lines)
