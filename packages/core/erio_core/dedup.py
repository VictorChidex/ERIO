"""How ERIO decides two postings are the same job (spec section 6).

Three passes, strictest first:

1. Exact ID: same source and external ID. The pipeline handles this by
   upserting the same raw posting, so it never reaches this module.
2. Exact key: same company, normalized title, city (or remote scope for
   remote roles) and canonical apply URL host and path.
3. Near-duplicate: 64-bit SimHash of 5-word description shingles within a
   small Hamming distance, compared only within the same company and
   country. Two guards keep it safe: the places must not differ (city,
   state or region, and the countries a remote role accepts), and the
   titles must name the same job once place words are removed, so one
   employer's template description on different roles, offices or sales
   territories does not merge them.

Everything here is pure, so the labeled pair set and the ingest pipeline
run exactly the same rules.
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit

from erio_core.db.seed import load_countries
from erio_core.normalize.gazetteer import COUNTRY_ALIASES

DedupMethod = Literal["exact_id", "exact_key", "simhash"]

SHINGLE_WORDS = 5
# Tuned on the labeled pairs (decision D-16): the spec's 3 finds only 69% of
# duplicates; 6 finds 93% with no false merge, and the first false merge is at 12.
MAX_DISTANCE = 6

WORD = re.compile(r"\w+", re.UNICODE)
# Words that say where or how a job is done, not what it is.
TITLE_PLACE_WORDS = frozenset({"remote", "hybrid", "onsite", "on", "site", "office", "based"})
# Query parameters that say where a visitor came from, not which job it is.
TRACKING_PARAMS = frozenset(
    {"gh_src", "gclid", "fbclid", "msclkid", "ref", "referrer", "source", "src", "trk",
     "lever-origin", "lever-source", "lever-source[]", "mc_cid", "mc_eid", "_hsenc", "_hsmi"}
)  # fmt: skip


def words(text: str) -> list[str]:
    return WORD.findall(text.casefold())


def title_key(title: str) -> str:
    """Lower case, punctuation dropped: "Sr. Engineer (Go)" is "sr engineer go"."""
    return " ".join(words(title))


def apply_key(url: str) -> str:
    """The apply URL canonicalized: host, path and the query values that name the job.

    Tracking parameters, scheme and fragment are dropped. Other query values
    stay: many careers pages tell jobs apart only by one
    (``stripe.com/jobs/search?gh_jid=8245230``).
    """
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").casefold().removeprefix("www.")
    query = sorted(
        (name, value)
        for name, value in parse_qsl(parts.query)
        if not (name.casefold() in TRACKING_PARAMS or name.casefold().startswith("utm_"))
    )
    return f"{host}{parts.path.rstrip('/')}" + (f"?{urlencode(query)}" if query else "")


def _hash64(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


def simhash(text: str | None) -> int | None:
    """64-bit SimHash of the text's 5-word shingles, as a signed integer.

    Signed so it fits a Postgres BIGINT. None when there is no text.
    """
    tokens = words(text or "")
    if not tokens:
        return None
    if len(tokens) < SHINGLE_WORDS:
        shingles = Counter([" ".join(tokens)])
    else:
        shingles = Counter(
            " ".join(tokens[i : i + SHINGLE_WORDS]) for i in range(len(tokens) - SHINGLE_WORDS + 1)
        )
    totals = [0] * 64
    for shingle, weight in shingles.items():
        value = _hash64(shingle)
        for bit in range(64):
            totals[bit] += weight if value >> bit & 1 else -weight
    unsigned = sum(1 << bit for bit in range(64) if totals[bit] > 0)
    return unsigned - (1 << 64) if unsigned >= 1 << 63 else unsigned


def hamming(a: int, b: int) -> int:
    return ((a ^ b) & ((1 << 64) - 1)).bit_count()


@lru_cache
def country_words() -> dict[str, frozenset[str]]:
    """Every word of each country's names, e.g. GB: united, kingdom, uk, britain..."""
    names: dict[str, set[str]] = {row["code"]: set(words(row["name"])) for row in load_countries()}
    for alias, code in COUNTRY_ALIASES.items():
        names.setdefault(code, set()).update(words(alias))
    return {code: frozenset(found) for code, found in names.items()}


@dataclass(frozen=True)
class Fingerprint:
    """What dedup compares about one posting (or the job built from it)."""

    company_id: int
    title: str
    city: str | None
    country_code: str | None
    remote_scope: str | None
    apply_url: str
    simhash: int | None
    region: str | None = None
    # Countries a remote role accepts; empty means any (or not remote).
    eligible: frozenset[str] = field(default_factory=frozenset)

    @property
    def place(self) -> str:
        return (self.city or "").casefold() or f"remote:{self.remote_scope or ''}"

    def key(self) -> str:
        """The exact-key pass as one hash, so the database can index it."""
        parts = (str(self.company_id), title_key(self.title), self.place, apply_key(self.apply_url))
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def core_title(fingerprint: Fingerprint, *others: Fingerprint) -> frozenset[str]:
    """Title words that say what the job is: place names and work-type words removed.

    "Senior Engineer - London (Remote)" and "Senior Engineer" share a core title.
    """
    place: set[str] = set(TITLE_PLACE_WORDS)
    for item in (fingerprint, *others):
        place.update(words(item.city or ""))
        place.update(country_words().get(item.country_code or "", ()))
    return frozenset(words(fingerprint.title)) - place


def places_differ(a: Fingerprint, b: Fingerprint) -> bool:
    """True when both postings name a place and the places are not the same.

    A missing city or state is no conflict: one source often gives only the
    country where another names the city.
    """
    for left, right in ((a.city, b.city), (a.region, b.region)):
        if left and right and left.casefold() != right.casefold():
            return True
    return bool(a.eligible and b.eligible and a.eligible != b.eligible)


def match(a: Fingerprint, b: Fingerprint) -> DedupMethod | None:
    """The pass that makes ``a`` and ``b`` one job, or None if they are distinct."""
    if a.company_id != b.company_id:
        return None
    if a.key() == b.key():
        return "exact_key"
    if a.country_code != b.country_code or a.simhash is None or b.simhash is None:
        return None
    if places_differ(a, b):
        return None
    if core_title(a, b) != core_title(b, a):
        return None
    if hamming(a.simhash, b.simhash) <= MAX_DISTANCE:
        return "simhash"
    return None
