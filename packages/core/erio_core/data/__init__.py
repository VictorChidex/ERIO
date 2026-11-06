"""Reference data shipped with erio_core (countries, gazetteer, boards, platforms)."""

import json
from importlib.resources import files
from pathlib import Path


def platforms_path() -> Path:
    """The platform registry: the 78 platforms of the coverage brief."""
    return Path(str(files("erio_core").joinpath("data/platforms.json")))


def example_boards() -> dict[str, list[str]]:
    """Each platform's known live example boards (board tokens), by platform slug."""
    rows = json.loads(platforms_path().read_text(encoding="utf-8"))
    return {row["slug"]: row["examples"] for row in rows if row["examples"]}
