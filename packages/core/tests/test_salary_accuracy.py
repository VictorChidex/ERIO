"""Salary parsing against the labeled set (spec section 6: at least 95%)."""

import csv
from pathlib import Path

from erio_core.normalize.salary import parse_salary

LABELED = Path(__file__).resolve().parents[3] / "fixtures" / "labeled" / "salaries.tsv"
GATE = 0.95


def load() -> list[list[str]]:
    lines = [
        line
        for line in LABELED.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    return [row for row in csv.reader(lines[1:], delimiter="\t", quoting=csv.QUOTE_NONE)]


def score() -> tuple[float, list[str]]:
    rows = load()
    correct, misses = 0, []
    for row in rows:
        text, expected = row[0], row[1:]
        got = parse_salary(text)
        if expected[0] == "NONE":
            ok = got is None
        else:
            low, high, currency, period = expected
            ok = got is not None and (
                got.min == round(float(low)),
                got.max == round(float(high)),
                got.currency,
                got.period,
            ) == (True, True, currency, period)
        correct += ok
        if not ok:
            found = None if got is None else (got.min, got.max, got.currency, got.period)
            misses.append(f"{text[:90]!r}: expected {expected}, got {found}")
    return correct / len(rows), misses


def test_labeled_set_size() -> None:
    rows = load()
    assert len(rows) >= 120
    assert sum(row[1] == "NONE" for row in rows) >= 15  # traps: market sizes, funding, budgets


def test_salary_accuracy_meets_the_gate() -> None:
    accuracy, misses = score()
    assert accuracy >= GATE, f"salary accuracy {accuracy:.1%}; misses:\n" + "\n".join(misses)
