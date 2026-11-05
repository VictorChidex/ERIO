"""Dedup rules (spec section 6) and the labeled pair gate: precision >= 99%, recall >= 90%."""

import dataclasses
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

from erio_core.dedup import Fingerprint, apply_key, core_title, hamming, match, simhash, title_key

LABELED = Path(__file__).resolve().parents[3] / "fixtures" / "labeled" / "dedup_pairs.json.gz"
PRECISION_GATE = 0.99
RECALL_GATE = 0.90

TEXT = (
    "We are hiring a backend engineer to build payment rails across Africa. You will design "
    "services in Python and Go, own them in production, review code and mentor others. "
    "You have shipped distributed systems, care about reliability and enjoy working with "
    "product and design to solve real problems for millions of customers every day."
)


def fingerprint(**changes: Any) -> Fingerprint:
    values: dict[str, Any] = {
        "company_id": 1,
        "title": "Backend Engineer",
        "city": "Lagos",
        "country_code": "NG",
        "remote_scope": None,
        "apply_url": "https://boards.greenhouse.io/acme/jobs/1",
        "simhash": simhash(TEXT),
    }
    return Fingerprint(**(values | changes))


def test_title_and_apply_url_are_canonicalized() -> None:
    assert title_key("Sr. Engineer (Go)") == "sr engineer go"
    assert apply_key("https://WWW.Acme.com/jobs/1/?utm_source=x&gh_src=y#apply") == (
        "acme.com/jobs/1"
    )
    # A careers page that tells jobs apart only by a query value keeps it.
    assert apply_key("https://stripe.com/jobs/search?gh_jid=82&utm_medium=a") == (
        "stripe.com/jobs/search?gh_jid=82"
    )


def test_simhash_is_signed_64_bit_and_stable() -> None:
    value = simhash(TEXT)
    assert value is not None
    assert -(2**63) <= value < 2**63
    assert value == simhash(TEXT.replace(" ", "  ").upper())
    assert simhash("") is None
    assert simhash("Short text") is not None
    assert hamming(value, value) == 0
    assert hamming(0, -1) == 64


def test_small_edits_stay_close_and_other_text_is_far() -> None:
    base = simhash(TEXT)
    edited = simhash(TEXT.replace("every day.", "every single day."))
    other = simhash("Sales lead for retail banking in Nairobi. " * 6)
    assert base is not None and edited is not None and other is not None
    assert hamming(base, edited) < hamming(base, other)
    assert hamming(base, other) > 6


def test_core_title_ignores_place_and_work_type_words() -> None:
    a = fingerprint(title="Backend Engineer - Lagos, Nigeria (Remote)")
    b = fingerprint(title="Backend Engineer", city=None)
    assert core_title(a, b) == core_title(b, a) == {"backend", "engineer"}


def test_exact_key_needs_company_title_place_and_apply_url() -> None:
    a = fingerprint(simhash=None)
    assert match(a, fingerprint(title="backend engineer!", simhash=None)) == "exact_key"
    assert match(a, fingerprint(company_id=2, simhash=None)) is None
    assert match(a, fingerprint(city="Abuja", simhash=None)) is None
    assert match(a, fingerprint(apply_url="https://jobs.lever.co/acme/2", simhash=None)) is None


def test_near_duplicate_across_sources() -> None:
    greenhouse = fingerprint()
    ashby = fingerprint(
        title="Backend Engineer - Lagos",
        city=None,
        apply_url="https://jobs.ashbyhq.com/acme/0b6e",
        simhash=simhash(TEXT + " Salary range: 40,000 - 50,000 a year."),
    )
    assert match(greenhouse, ashby) == "simhash"
    assert match(ashby, greenhouse) == "simhash"


def test_near_duplicate_guards() -> None:
    a = fingerprint()
    other = "https://jobs.ashbyhq.com/acme/0b6e"
    # Same template text, but another company, country, city or role.
    assert match(a, fingerprint(apply_url=other, company_id=2)) is None
    assert match(a, fingerprint(apply_url=other, country_code="GH", city="Accra")) is None
    assert match(a, fingerprint(apply_url=other, city="Abuja")) is None
    assert match(a, fingerprint(apply_url=other, title="Senior Backend Engineer")) is None
    assert match(a, fingerprint(apply_url=other, simhash=None)) is None
    # One remote role per sales territory: same text, different states or countries.
    texas = fingerprint(city=None, region="Texas", eligible=frozenset({"US"}))
    assert match(texas, fingerprint(city=None, region="Florida", apply_url=other)) is None
    europe = fingerprint(city=None, country_code=None, eligible=frozenset({"DE", "FR"}))
    americas = fingerprint(city=None, country_code=None, eligible=frozenset({"US", "CA"}))
    assert match(europe, dataclasses.replace(americas, apply_url=other)) is None
    assert match(texas, fingerprint(city=None, apply_url=other)) == "simhash"
    far = simhash("Sales lead for retail banking in Nairobi. " * 6)
    assert match(a, fingerprint(apply_url=other, simhash=far)) is None


def load() -> dict[str, Any]:
    with gzip.open(LABELED, "rt", encoding="utf-8") as raw:
        data: dict[str, Any] = json.load(raw)
    return data


def test_labeled_set_has_300_duplicate_and_300_distinct_pairs() -> None:
    pairs = load()["pairs"]
    labels = Counter(duplicate for _, _, duplicate, _ in pairs)
    assert labels == {True: 300, False: 300}
    kinds = Counter(kind.split(":")[0] for _, _, _, kind in pairs)
    assert kinds["real cross-post"] >= 1
    assert kinds["different title, similar text"] >= 50
    assert kinds["same title, other place"] >= 50
    assert kinds["same title and place, other text"] >= 50


def test_dedup_meets_the_gate() -> None:
    data = load()
    fingerprints = [
        Fingerprint(
            company_id=p["company_id"],
            title=p["title"],
            city=p["city"],
            country_code=p["country_code"],
            remote_scope=p["remote_scope"],
            apply_url=p["apply_url"],
            simhash=simhash(p["text"]),
            region=p["region"],
            eligible=frozenset(p["eligible"]),
        )
        for p in data["postings"]
    ]
    found = missed = false = 0
    errors = []
    for a, b, duplicate, kind in data["pairs"]:
        merged = match(fingerprints[a], fingerprints[b]) is not None
        if merged and duplicate:
            found += 1
        elif merged:
            false += 1
            errors.append(f"false merge ({kind}): {fingerprints[a].title!r}")
        elif duplicate:
            missed += 1
    precision = found / (found + false)
    recall = found / (found + missed)
    assert precision >= PRECISION_GATE, f"precision {precision:.1%}:\n" + "\n".join(errors)
    assert recall >= RECALL_GATE, f"recall {recall:.1%} ({missed} duplicates missed)"
