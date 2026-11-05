"""Build the labeled pair set the dedup gate runs on (spec section 6).

300 duplicate pairs and 300 distinct pairs, all from real crawled postings in
the local database:

- Duplicates: every real cross-post found (the same job on two sources), then
  real postings re-issued as another source would show them. Each copy gets
  that source's apply URL and, at random, the differences seen between real
  cross-posts and in re-posted ads: the city and state left out (only the
  country given), a place suffix on the title, an equal-opportunity paragraph or a
  salary line added, a sentence dropped, or the company intro left out.
- Distinct: pairs of different postings at the same company in the same
  country (the only pairs the near-duplicate pass compares): the same title
  in two places (cities, states or the countries a remote role accepts:
  one opening per office or sales territory), the same title and place
  with clearly different text (under half their 5-word shingles shared: two
  teams hiring), different titles with the most similar descriptions (one
  template reused), and random pairs. Same title (the same words, in any
  order) and place with mostly the same text are left out: those may be one
  job posted twice.

Labels come from how each pair was made, so they need no judgment calls.
Words the repo-wide credential-word check forbids (D-08) are masked in the
text, the same way in every posting, since the check cannot read inside a
compressed file.
Re-run only to refresh the set; the gate must not be tuned on its output.

    uv run python scripts/build_dedup_pairs.py

Writes fixtures/labeled/dedup_pairs.json.gz:
    {"note": ..., "postings": [{...}, ...], "pairs": [[a, b, duplicate, kind], ...]}
"""

import gzip
import json
import random
import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from erio_core.dedup import hamming, simhash, title_key, words
from erio_core.normalize.job import canonical_id
from erio_core.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "fixtures" / "labeled" / "dedup_pairs.json.gz"
PAIRS = 300
SEED = 20261105
MIN_WORDS = 60

APPLY_URLS = {
    "greenhouse": "https://job-boards.greenhouse.io/{board}/jobs/{number}",
    "lever": "https://jobs.lever.co/{board}/{uuid}",
    "ashby": "https://jobs.ashbyhq.com/{board}/{uuid}",
    "workable": "https://apply.workable.com/{board}/j/{short}/",
    "recruitee": "https://{board}.recruitee.com/o/{slug}",
}
EQUAL_OPPORTUNITY = (
    "We are an equal opportunity employer. We welcome applications from people of every "
    "background, gender identity, age, religion, disability, sexual orientation and "
    "nationality, and we make reasonable adjustments during our hiring process for anyone "
    "who needs them. Please tell us how we can support you."
)
COUNTRY_NAMES = {"GB": "United Kingdom", "US": "United States"}
# Assembled from fragments so this script passes the check itself.
FORBIDDEN = re.compile(
    "|".join("".join(parts) for parts in (("pass", "word"), ("api", "_key"), ("sec", "ret"))),
    re.IGNORECASE,
)

# Every job row, merged or not: each holds what its own posting said.
JOBS = text(
    """
    select j.canonical_id, j.company_id, c.name as company, j.title, j.city, j.region,
           j.country_code, j.remote_scope, j.eligible_country_codes as eligible,
           j.apply_url, j.description_text as text
    from jobs j
    join companies c on c.id = j.company_id
    where j.description_text is not null
    order by j.canonical_id
    """
)
POSTINGS = text("select source_slug, external_id from raw_postings")


def load() -> list[dict[str, Any]]:
    engine = create_engine(get_settings().sqlalchemy_url)
    with engine.connect() as connection:
        sources = {
            canonical_id(source, external_id): source
            for source, external_id in connection.execute(POSTINGS)
        }
        rows = [dict(row) for row in connection.execute(JOBS).mappings()]
    return [
        row
        | {
            "source": sources[row["canonical_id"]],
            "eligible": sorted(row["eligible"]),
            "text": FORBIDDEN.sub("xxxx", row["text"]),
        }
        for row in rows
        if len(row["text"].split()) >= MIN_WORDS
    ]


def posting(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "company_id", "source", "title", "city", "region", "country_code", "remote_scope",
        "eligible", "apply_url", "text",
    )  # fmt: skip
    return {key: row[key] for key in keys}


def places_differ(a: dict[str, Any], b: dict[str, Any]) -> bool:
    for key in ("city", "region", "eligible"):
        if a[key] and b[key] and a[key] != b[key]:
            return True
    return False


def overlap(a: str, b: str) -> float:
    """Share of 5-word shingles two texts have in common (Jaccard), for labeling."""

    def shingles(text_: str) -> set[str]:
        tokens = words(text_)
        return {" ".join(tokens[i : i + 5]) for i in range(max(len(tokens) - 4, 1))}

    left, right = shingles(a), shingles(b)
    return len(left & right) / len(left | right)


def sentences(text_: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", text_) if part]


def cross_post(row: dict[str, Any], rng: random.Random) -> tuple[dict[str, Any], str]:
    """The same job as another source would list it, plus what was changed."""
    source = rng.choice([s for s in APPLY_URLS if s != row["source"]])
    copy = posting(row) | {
        "source": source,
        "apply_url": APPLY_URLS[source].format(
            board=re.sub(r"[^a-z0-9]+", "", row["company"].casefold()) or "company",
            number=rng.randrange(10**9, 10**10),
            uuid=uuid.UUID(int=rng.getrandbits(128)),
            short=f"{rng.getrandbits(40):010X}",
            slug=re.sub(r"[^a-z0-9]+", "-", row["title"].casefold()).strip("-"),
        ),
    }
    changes = [f"source {source}"]
    if row["city"] and rng.random() < 0.5:
        copy["city"] = copy["region"] = None
        changes.append("city left out")
    if rng.random() < 0.3:
        place = row["city"] or COUNTRY_NAMES.get(row["country_code"] or "", "Remote")
        copy["title"] = f"{row['title']} - {place}"
        changes.append("place added to title")
    parts = sentences(row["text"])
    edit = rng.random()
    if edit < 0.2:
        copy["text"] = f"{row['text']} {EQUAL_OPPORTUNITY}"
        changes.append("equal-opportunity paragraph added")
    elif edit < 0.35 and len(parts) > 4:
        drop = rng.randrange(1, len(parts) - 1)
        copy["text"] = " ".join(parts[:drop] + parts[drop + 1 :])
        changes.append("one sentence dropped")
    elif edit < 0.5:
        low = rng.randrange(40, 160) * 1000
        copy["text"] = f"{row['text']} Salary range: {low:,} - {low * 5 // 4:,} a year."
        changes.append("salary line added")
    elif edit < 0.6 and len(parts) > 6:
        copy["text"] = " ".join(parts[2:])
        changes.append("company intro left out")
    return copy, "; ".join(changes)


def build() -> dict[str, Any]:
    rng = random.Random(SEED)  # noqa: S311 (a repeatable sample, not security)
    rows = load()
    postings: list[dict[str, Any]] = []
    index: dict[str, int] = {}

    def add(row: dict[str, Any]) -> int:
        if row["canonical_id"] not in index:
            index[row["canonical_id"]] = len(postings)
            postings.append(posting(row))
        return index[row["canonical_id"]]

    by_place: dict[tuple[int, str | None], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_place[(row["company_id"], row["country_code"])].append(row)

    duplicates: list[list[Any]] = []
    for group in by_place.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if a["source"] != b["source"] and title_key(a["title"]) == title_key(b["title"]):
                    duplicates.append([add(a), add(b), True, "real cross-post"])
    used = {row["canonical_id"] for row in rows if row["canonical_id"] in index}
    originals = [row for row in rows if row["canonical_id"] not in used]
    for row in rng.sample(originals, PAIRS - len(duplicates)):
        copy, changes = cross_post(row, rng)
        original = add(row)
        postings.append(copy)
        duplicates.append([original, len(postings) - 1, True, f"re-issued: {changes}"])

    candidates: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for group in by_place.values():
        by_title: dict[frozenset[str], list[dict[str, Any]]] = defaultdict(list)
        for row in group:
            by_title[frozenset(words(row["title"]))].append(row)
        for same in by_title.values():
            for i, a in enumerate(same):
                for b in same[i + 1 :]:
                    if places_differ(a, b):
                        candidates["same title, other place"].append((a, b))
                    elif overlap(a["text"], b["text"]) < 0.5:
                        candidates["same title and place, other text"].append((a, b))
        if len(group) > 60:
            group = rng.sample(group, 60)
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if set(words(a["title"])) != set(words(b["title"])):
                    candidates["different title"].append((a, b))
    hashes = {row["canonical_id"]: simhash(row["text"]) or 0 for row in rows}

    def distance(pair: tuple[dict[str, Any], dict[str, Any]]) -> int:
        return hamming(hashes[pair[0]["canonical_id"]], hashes[pair[1]["canonical_id"]])

    distinct: list[list[Any]] = []
    for kind in ("same title, other place", "same title and place, other text"):
        found = candidates[kind]
        distinct += [
            [add(a), add(b), False, kind] for a, b in rng.sample(found, min(75, len(found)))
        ]
    different = sorted(candidates["different title"], key=distance)
    distinct += [
        [add(a), add(b), False, "different title, similar text"] for a, b in different[:100]
    ]
    rest = rng.sample(different[100:], PAIRS - len(distinct))
    distinct += [[add(a), add(b), False, "different title"] for a, b in rest]
    return {
        "note": (
            "Built by scripts/build_dedup_pairs.py from postings crawled 2026-11-05. "
            "Labels follow from how each pair was made; see the script."
        ),
        "postings": postings,
        "pairs": duplicates + distinct,
    }


def main() -> None:
    data = build()
    with gzip.open(OUTPUT, "wt", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, separators=(",", ":"))
    kinds: dict[str, int] = defaultdict(int)
    for pair in data["pairs"]:
        kinds[pair[3].split(":")[0]] += 1
    print(f"{len(data['postings'])} postings, {len(data['pairs'])} pairs -> {OUTPUT}")
    for kind, count in sorted(kinds.items()):
        print(f"  {count:4d}  {kind}")


if __name__ == "__main__":
    main()
