"""Company slugs: the stable, readable part of a company's page address."""

import re
import unicodedata
from collections.abc import Collection

MAX_LENGTH = 80


def slugify(name: str) -> str:
    """Lowercase ASCII words joined by hyphens: "Café Müller & Co." -> "cafe-muller-co"."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return words[:MAX_LENGTH].strip("-") or "company"


def unique_slug(name: str, taken: Collection[str]) -> str:
    """The slug of ``name``, with -2, -3 ... added until it is not in ``taken``."""
    base = slugify(name)
    slug, n = base, 1
    while slug in taken:
        n += 1
        slug = f"{base}-{n}"
    return slug
