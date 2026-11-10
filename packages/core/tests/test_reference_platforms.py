"""Connectors for the platforms found by comparing ERIO with the reference index.

The postings come from ``fixtures/coverage/{slug}.json``: three real jobs per platform, saved
from live boards by ``python -m erio_ingest.coverage verify --record``.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from erio_core.connectors import CONNECTORS, FetchResponse
from erio_core.connectors.csod import clean_description
from erio_core.connectors.jsonld import job_postings
from erio_core.connectors.reference_platforms import (
    EmplyConnector,
    HiringRoomConnector,
    MyJobMagConnector,
    TraffitConnector,
)
from erio_core.schemas import RawPosting

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "coverage"


def recorded(slug: str) -> list[RawPosting]:
    data = json.loads((FIXTURES / f"{slug}.json").read_text(encoding="utf-8"))
    return [RawPosting.model_validate(item) for item in data]


class FakeFetcher:
    """Answers GETs and POSTs from a table; remembers what was asked."""

    def __init__(self, pages: dict[str, bytes], answers: dict[str, bytes] | None = None):
        self.pages = pages
        self.answers = answers or {}
        self.asked: list[tuple[str, str, Any]] = []

    def get(self, url: str, etag: str | None = None) -> FetchResponse:
        self.asked.append(("GET", url, None))
        body = self.pages.get(url)
        return FetchResponse(200, body) if body is not None else FetchResponse(404, b"")

    def post_json(self, url: str, payload: Any) -> FetchResponse:
        self.asked.append(("POST", url, payload))
        return FetchResponse(200, self.answers[url])


# -------------------------------------------------------------------- TRAFFIT


def test_traffit_reads_title_place_and_apply_link() -> None:
    connector = TraffitConnector()
    job = connector.parse(recorded("traffit")[0])
    assert job.title
    assert job.apply_url.host.endswith(".traffit.com")  # type: ignore[union-attr]
    assert job.country_hint == "PL" and job.city
    assert job.posted_at is not None
    assert job.description_html and "<" in job.description_html


def test_traffit_board_url_refuses_a_token_that_is_not_a_subdomain() -> None:
    with pytest.raises(ValueError):
        TraffitConnector().board_url("evil.example.org/x")
    assert TraffitConnector().board_url("hrhub").startswith("https://hrhub.traffit.com/")


def test_traffit_ignores_an_empty_list_and_rejects_anything_else() -> None:
    connector = TraffitConnector()
    assert connector.extract(b"[]", "acme") == []
    with pytest.raises(ValueError):
        connector.extract(b'{"error": "x"}', "acme")


# ---------------------------------------------------------------------- Emply


def emply_answer(*vacancies: dict[str, Any]) -> bytes:
    return json.dumps({"vacancies": list(vacancies), "count": len(vacancies)}).encode()


def test_emply_reads_a_vacancy_and_builds_the_ad_link() -> None:
    job = EmplyConnector().parse(recorded("emply")[0])
    assert job.title
    assert str(job.apply_url).startswith("https://ohly.career.emply.com/ad/")
    assert job.description_html and job.posted_at is not None
    assert job.location_text and " / " not in job.location_text  # the site name is dropped


def test_emply_skips_the_open_application_entry() -> None:
    body = emply_answer(
        {"shortId": "aaa111", "title": "Open", "titleAsUrl": "open", "talentPool": True},
        {"shortId": "bbb222", "title": "Nurse", "titleAsUrl": "nurse", "talentPool": False},
    )
    found = EmplyConnector().extract(body, "acme")
    assert [p.external_id for p in found] == ["bbb222"]


def test_emply_finds_the_list_section_on_the_page_and_calls_the_search() -> None:
    page = (
        b"<script>var languageKey = 'da-DK'; var config = {sectionId: "
        b"'c1cb99f0-34cd-4498-a36f-89ebe2100d04', count: 6};</script>"
    )
    url = "https://acme.career.emply.com/api/integration/vacancy/get-page"
    fetcher = FakeFetcher(
        {"https://acme.career.emply.com/": page},
        {url: emply_answer({"shortId": "x1", "title": "Nurse", "titleAsUrl": "nurse"})},
    )
    result = EmplyConnector().list_postings(fetcher, "acme")  # type: ignore[arg-type]
    assert [p.external_id for p in result.postings] == ["x1"] and result.complete
    post = next(a for a in fetcher.asked if a[0] == "POST")
    assert post[1] == url
    assert post[2]["sectionId"] == "c1cb99f0-34cd-4498-a36f-89ebe2100d04"
    assert post[2]["langCode"] == "da-DK"


@pytest.mark.parametrize("token", ["a b", "../x", "evil.example.org/x", "http://169.254.169.254"])
def test_emply_refuses_a_token_that_is_not_a_career_site(token: str) -> None:
    with pytest.raises(ValueError):
        EmplyConnector().board_url(token)


# ----------------------------------------------------------------- HiringRoom

VACANCY_PAGE = """
<div class="hero__title"><h2 class="commonstxt">
  Accounts Payable Coordinator   </h2></div>
<div class="hero__area-ubication hideOnMoible">
  <p class="commonstxt" title="Argentina"><span class="hr-Location-pin"></span>
      Argentina     </p>
  <p class="commonstxt"><span class="hr-Work-area"></span>
      Administraci&#xF3;n/Contabilidad   </p></div>
<div class="d-flex hero__tag-items">
  <div class="commonstxt hero__tag">
    <span class="commonstxt hr-Clock hrc-black"></span>Full-time   </div>
  <div class="commonstxt hero__tag"><span class="commonstxt hr-Remote"></span>Remoto<!-- x -->
  </div></div>
<div class="hrc-fs-14 job-description-content"><p>Pay vendors on time.</p></div>
"""


def test_hiringroom_reads_the_vacancy_page() -> None:
    connector = HiringRoomConnector()
    raw = connector.extract(VACANCY_PAGE.encode(), "acme")[0]
    job = connector.parse(raw.model_copy(update={"external_id": "6adf4a57b288b080c0b2db95"}))
    assert job.title == "Accounts Payable Coordinator"
    assert job.location_text == "Argentina"
    assert job.workplace_type == "remote" and job.employment_type == "Full-time"
    assert job.departments == ["Administración/Contabilidad"]
    assert job.description_html == "<p>Pay vendors on time.</p>"
    assert str(job.apply_url) == (
        "https://acme.hiringroom.com/jobs/get_vacancy/6adf4a57b288b080c0b2db95"
    )


def test_hiringroom_lists_jobs_but_not_the_general_application_link() -> None:
    listing = (
        b'<a href="/jobs/get_vacancy/6adf4a57b288b080c0b2db95">Job</a>'
        b'<a href="https://hiringroom.com/jobs/get_vacancy/6179914765017569ab1fe35b/candidates/new">'
        b"General</a>"
    )
    fetcher = FakeFetcher(
        {
            "https://acme.hiringroom.com/jobs": listing,
            "https://acme.hiringroom.com/jobs/get_vacancy/6adf4a57b288b080c0b2db95": (
                VACANCY_PAGE.encode()
            ),
        }
    )
    result = HiringRoomConnector().list_postings(fetcher, "acme")  # type: ignore[arg-type]
    assert [p.external_id for p in result.postings] == ["6adf4a57b288b080c0b2db95"]
    assert len([a for a in fetcher.asked if "6179914765017569ab1fe35b" in a[1]]) == 0


# ------------------------------------------------------------------- MyJobMag


def test_myjobmag_reads_employer_place_and_link() -> None:
    job = MyJobMagConnector().parse(recorded("myjobmag")[0])
    assert job.company_name and job.title and job.location_text
    assert job.country_hint in {"NG", "KE", "ZA"}
    assert str(job.apply_url).startswith("https://www.myjobmag.")
    assert job.posted_at is not None


def test_myjobmag_takes_only_its_own_sites() -> None:
    connector = MyJobMagConnector()
    assert connector.board_url("https://www.myjobmag.co.ke").endswith("/aggregate_feed.xml")
    for token in ("https://evil.example.org", "https://www.myjobmag.com/x", "www.myjobmag.com"):
        with pytest.raises(ValueError):
            connector.board_url(token)
    with pytest.raises(ValueError):
        connector.extract(b"<rss><channel></channel></rss>", "https://www.myjobmag.com")


# ------------------------------------------------------ pages with JSON-LD


@pytest.mark.parametrize(
    "slug", ["pandape", "factorial", "coveto", "instaffo", "jobberman", "brightermonday", "torre"]
)
def test_json_ld_platforms_read_title_employer_and_link(slug: str) -> None:
    connector = CONNECTORS[slug]
    for raw in recorded(slug):
        job = connector.parse(raw)
        assert job.title and str(job.apply_url).startswith("https://")
    assert any(connector.parse(raw).company_name for raw in recorded(slug))
    assert not any(
        (connector.parse(raw).company_name or "").startswith("http") for raw in recorded(slug)
    )


def test_a_posting_that_names_its_employer_by_reference_gets_the_name() -> None:
    page = """<script type="application/ld+json">{"@graph": [
      {"@type": "Organization", "@id": "https://x.test/#/org/7", "name": "PC Recruit"},
      {"@type": "JobPosting", "title": "Accountant",
       "hiringOrganization": {"@id": "https://x.test/#/org/7"}}]}</script>"""
    [posting] = job_postings(page)
    assert posting["hiringOrganization"]["name"] == "PC Recruit"


def test_instaffo_and_torre_and_the_african_boards_are_multi_employer_services() -> None:
    for slug in ("instaffo", "torre", "jobberman", "brightermonday", "myjobmag"):
        assert CONNECTORS[slug].multi_employer


# ----------------------------------------------------------------------- CSOD


def test_csod_description_loses_the_career_page_style_rules() -> None:
    spinner = (
        ".wm-ab-launcher-spinner { height: 100%; left: 0; } "
        "@keyframes wm-ab-spin { 0% { transform: rotate(0deg); } "
        "100% { transform: rotate(360deg); } } "
    )
    text = f" Employment Opportunities {spinner}{spinner}If you like technology, join us."
    assert clean_description(text) == "If you like technology, join us."
    assert clean_description("<style>.a { x: y }</style><p>Plain job.</p>") == "<p>Plain job.</p>"
    assert clean_description("Build a 5.5 m bridge. Apply today.") == (
        "Build a 5.5 m bridge. Apply today."
    )


def test_csod_recorded_postings_carry_clean_descriptions() -> None:
    connector = CONNECTORS["csod"]
    for raw in recorded("csod"):
        html = connector.parse(raw).description_html or ""
        assert "wm-ab-launcher-spinner" not in html and "keyframes" not in html
