"""Place formats that left thousands of real jobs without a country, one case each.

They came from Taleo ("Massachusetts-Acton"), Workday ("3 Locations"), BrassRing
("0201 - PORT CHARLOTTE FL (R)"), WP Job Manager (the place sits in ``all_meta``) and
recruiter boards on a country domain (Nodex on ".co.uk").
"""

import pytest

from erio_core.connectors import CONNECTORS
from erio_core.connectors._util import host_country
from erio_core.connectors.brassring import clean_place
from erio_core.connectors.workday import WorkdayConnector, path_place
from erio_core.normalize.job import normalize
from erio_core.normalize.location import resolve_location
from erio_core.schemas import RawPosting


@pytest.mark.parametrize(
    ("text", "country", "city", "region"),
    [
        ("Massachusetts-Acton", "US", "Acton", "Massachusetts"),
        ("United States-Florida-Tampa", "US", "Tampa", "Florida"),
        ("Florida-Tampa", "US", "Tampa", "Florida"),  # not the Colombian town of Floridablanca
        ("North Carolina-Winston-Salem", "US", "Winston-Salem", "North Carolina"),
        ("Canada-Ontario-Toronto", "CA", "Toronto", "Ontario"),
        ("Tel Aviv-Yafo", "IL", "Tel Aviv", "Tel Aviv"),  # a hyphen inside a name stays
    ],
)
def test_a_place_written_broad_to_narrow_with_hyphens_resolves(
    text: str, country: str, city: str, region: str
) -> None:
    result = resolve_location(text)

    assert (result.country_code, result.city, result.region) == (country, city, region)
    assert result.review_reason is None


@pytest.mark.parametrize("text", ["Part-time", "Acme-Corp", "Back-office"])
def test_ordinary_hyphenated_words_are_not_read_as_places(text: str) -> None:
    result = resolve_location(text)

    assert result.country_code is None and result.review_reason


@pytest.mark.parametrize(
    ("path", "place"),
    [
        ("/job/US-CA-Santa-Clara/Senior-Engineer_JR2025628-1", "Santa Clara, CA, US"),
        ("/job/DE-Munich/Engineer_JR1", "Munich, DE"),
        ("/job/USA---Florida---Tampa/Nurse_JR2", "USA-Florida-Tampa"),
        ("/job/Singapore/Analyst_JR3", "Singapore"),
        ("/job/x", None),
        ("/other/US-CA/x/y", None),
    ],
)
def test_workday_names_a_jobs_first_place_in_its_address(path: str, place: str | None) -> None:
    assert path_place(path) == place


def workday_posting(**item: object) -> RawPosting:
    return RawPosting(
        source_slug="workday",
        board_token="acme.wd5/Careers",
        external_id="JR1",
        payload={
            "title": "Applications Engineer",
            "bulletFields": ["JR1"],
            "externalPath": "/job/US-CA-Santa-Clara/Applications-Engineer_JR1",
            **item,
        },
    )


def test_a_workday_job_listing_only_a_count_gets_the_place_from_its_address() -> None:
    partial = WorkdayConnector().parse(workday_posting(locationsText="3 Locations"))

    assert partial.location_text == "Santa Clara, CA, US"
    assert normalize(partial, {}).columns()["country_code"] == "US"


def test_a_workday_job_with_a_real_place_keeps_it() -> None:
    partial = WorkdayConnector().parse(workday_posting(locationsText="Singapore"))

    assert partial.location_text == "Singapore"


@pytest.mark.parametrize(
    ("written", "clean"),
    [
        ("0201 - PORT CHARLOTTE FL (R)", "PORT CHARLOTTE, FL"),
        ("0909 - ROXBURY", "ROXBURY"),
        ("1234 - SEATTLE WA", "SEATTLE, WA"),
        ("Tampa, FL", "Tampa, FL"),
        ("Washington DC", "Washington, DC"),
    ],
)
def test_a_store_sites_place_loses_its_number_and_flag(written: str, clean: str) -> None:
    assert clean_place(written) == clean


def test_wp_job_manager_reads_the_place_and_employer_from_all_meta() -> None:
    raw = RawPosting(
        source_slug="wp_job_manager",
        board_token="https://sportyjob.example.org",
        external_id="9",
        payload={
            "title": {"rendered": "Marketing Manager"},
            "content": {"rendered": "<p>Join us</p>"},
            "link": "https://sportyjob.example.org/job/marketing-manager/",
            "date_gmt": "2026-11-05T10:00:00",
            "meta": {"_application": "https://ats.example.org/apply/9"},
            "all_meta": {
                "_job_location": ["Paris"],
                "_company_name": ["Amer Sports"],
                "geolocation_formatted_address": ["Paris, France"],
                "geolocation_city": ["Paris"],
                "geolocation_country_short": ["FR"],
            },
        },
    )

    partial = CONNECTORS["wp_job_manager"].parse(raw)

    assert (partial.location_text, partial.city, partial.country_hint) == (
        "Paris, France",
        "Paris",
        "FR",
    )
    assert partial.company_name == "Amer Sports"
    assert normalize(partial, {}).columns()["country_code"] == "FR"


def test_wp_job_manager_prefers_the_registered_meta_when_it_has_the_place() -> None:
    raw = RawPosting(
        source_slug="wp_job_manager",
        board_token="https://jobs.example.org",
        external_id="1",
        payload={
            "title": {"rendered": "Editor"},
            "link": "https://jobs.example.org/job/editor/",
            "meta": {"_job_location": "Lagos, Nigeria"},
            "all_meta": {"_job_location": ["Elsewhere"]},
        },
    )

    assert CONNECTORS["wp_job_manager"].parse(raw).location_text == "Lagos, Nigeria"


@pytest.mark.parametrize(
    ("url", "country"),
    [
        ("https://www.antellarecruitment.co.uk/sitemap.xml", "GB"),
        ("https://jobs.example.com.au/job/1", "AU"),
        ("https://careers.example.nl/", "NL"),
        ("https://jobs.example.io/", None),  # ".io" is not a country in practice
        ("https://example.com/", None),
        ("not a url", None),
    ],
)
def test_a_country_domain_names_its_country(url: str, country: str | None) -> None:
    assert host_country(url) == country


def test_a_recruiters_town_on_a_country_domain_gets_that_country() -> None:
    raw = RawPosting(
        source_slug="nodex",
        board_token="https://www.antellarecruitment.co.uk/sitemap.xml",
        external_id="1",
        payload={
            "page_url": "https://www.antellarecruitment.co.uk/job/support-worker",
            "posting": {
                "title": "Support Worker",
                "jobLocation": {"address": {"addressLocality": "Heathrow"}},
            },
        },
    )

    partial = CONNECTORS["nodex"].parse(raw)

    assert partial.country_hint == "GB"
    assert normalize(partial, {}).columns()["country_code"] == "GB"


def test_other_json_ld_boards_do_not_guess_a_country_from_their_domain() -> None:
    raw = RawPosting(
        source_slug="jboard",
        board_token="https://jobs.example.co.uk/sitemap.xml",
        external_id="1",
        payload={
            "page_url": "https://jobs.example.co.uk/jobs/1",
            "posting": {"title": "Cook", "jobLocation": {"address": {"addressLocality": "Paris"}}},
        },
    )

    assert CONNECTORS["jboard"].parse(raw).country_hint is None
