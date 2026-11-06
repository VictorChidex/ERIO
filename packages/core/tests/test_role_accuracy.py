"""Role classification against the labeled set (spec section 6: at least 90%)."""

import csv
from collections import Counter
from pathlib import Path
from typing import get_args

from erio_core.normalize.roles import classify_role
from erio_core.schemas import RoleCategory

LABELED = Path(__file__).resolve().parents[3] / "fixtures" / "labeled" / "roles.tsv"
GATE = 0.90


def load() -> list[dict[str, str]]:
    lines = [
        line
        for line in LABELED.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    return list(csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE))


def score() -> tuple[float, list[str]]:
    rows = load()
    misses = []
    for row in rows:
        departments = [d.strip() for d in row["departments"].split(";") if d.strip()]
        got = classify_role(row["title"], departments)
        if got != row["role"]:
            misses.append(
                f"{row['title']!r} [{row['departments']}]: expected {row['role']}, got {got}"
            )
    return 1 - len(misses) / len(rows), misses


def test_labeled_set_size_and_spread() -> None:
    rows = load()
    assert len(rows) >= 300
    roles = Counter(row["role"] for row in rows)
    assert set(roles) == set(get_args(RoleCategory))
    # Every category the website filters on is exercised by more than a stray example.
    assert min(roles.values()) >= 3, roles


def test_role_accuracy_meets_the_gate() -> None:
    accuracy, misses = score()
    assert accuracy >= GATE, f"role accuracy {accuracy:.1%}; misses:\n" + "\n".join(misses)
