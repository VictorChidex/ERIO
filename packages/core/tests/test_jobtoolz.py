"""Jobtoolz career sites: which sitemap pages are job openings."""

import pytest

from erio_core.connectors import CONNECTORS


@pytest.mark.parametrize(
    ("path", "is_job"),
    [
        ("/nl/teamcoach-productie-op-locatie", True),
        ("/en/chauffeur-c-ce-flexi-job-nationaal-internationaal-transport", True),
        ("/nl", False),  # the language home
        ("/nl/spontaan-solliciteren", False),
        ("/en/apply-spontaneously", False),
        ("/fr/candidature-spontanee", False),
    ],
)
def test_only_job_pages_count(path: str, is_job: bool) -> None:
    assert bool(CONNECTORS["jobtoolz"].job_path.match(path)) is is_job  # type: ignore[attr-defined]
