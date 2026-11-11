"""Pay that failed the sanity check never reaches the search index."""

from erio_core.search.index import document


def job(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "canonical_id": "j1",
        "title": "Nurse",
        "company_name": "Acme",
        "role_category": "healthcare",
        "remote_status": "onsite",
        "status": "open",
        "apply_url": "https://example.test/j1",
        "salary_min": 45,
        "salary_max": 60,
        "salary_currency": "INR",
        "salary_period": "year",
        "salary_usd_annual_min": 2000,
    }
    return row | changes


def test_a_reliable_figure_is_indexed() -> None:
    doc = document(job())
    assert (doc["salary_min"], doc["salary_currency"], doc["salary_usd_annual_min"]) == (
        45,
        "INR",
        2000,
    )
    assert doc["salary_unreliable"] is False


def test_an_unreliable_figure_is_left_out_but_flagged() -> None:
    doc = document(job(salary_unreliable=True))
    for field in (
        "salary_min",
        "salary_max",
        "salary_currency",
        "salary_period",
        "salary_usd_annual_min",
    ):
        assert doc[field] is None, field
    assert doc["salary_unreliable"] is True
