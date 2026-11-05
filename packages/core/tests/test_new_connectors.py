"""Unit tests for Breezy HR and BambooHR connectors."""

import json
from pydantic import HttpUrl

from erio_core.connectors.bamboohr import BambooHRConnector
from erio_core.connectors.breezy import BreezyConnector
from erio_core.schemas import RawPosting


BREEZY_SAMPLE = [
    {
        "_id": "bz-101",
        "name": "Senior Backend Engineer",
        "type": {"id": "full_time", "name": "Full-Time"},
        "location": {
            "city": "Berlin",
            "state": "Berlin",
            "country": {"name": "Germany", "code": "DE"},
            "is_remote": True,
        },
        "company": {"name": "Tech Corp"},
        "creation_date": "2026-11-01T12:00:00.000Z",
        "department": "Engineering",
        "description": "<p>Write Python services.</p>",
    }
]

BAMBOOHR_SAMPLE = {
    "result": [
        {
            "id": "bb-202",
            "jobOpeningName": "Staff Data Engineer",
            "location": {
                "city": "San Francisco",
                "state": "CA",
                "country": "United States",
            },
            "department": {"label": "Data Platform"},
            "employmentType": "Full-Time",
            "isRemote": True,
            "datePosted": "2026-11-02",
            "description": "<p>Scale pipelines.</p>",
        }
    ]
}


def test_breezy_connector_extract_and_parse() -> None:
    connector = BreezyConnector()
    assert connector.board_url("techcorp") == "https://techcorp.breezy.hr/json"

    raw_list = connector.extract(json.dumps(BREEZY_SAMPLE).encode(), "techcorp")
    assert len(raw_list) == 1
    raw = raw_list[0]
    assert raw.external_id == "bz-101"

    job = connector.parse(raw)
    assert job.title == "Senior Backend Engineer"
    assert job.company_name == "Tech Corp"
    assert job.city == "Berlin"
    assert job.country_hint == "DE"
    assert job.workplace_type == "remote"
    assert job.employment_type == "Full-Time"
    assert job.departments == ["Engineering"]
    assert str(job.apply_url) == "https://techcorp.breezy.hr/p/bz-101"


def test_bamboohr_connector_extract_and_parse() -> None:
    connector = BambooHRConnector()
    assert connector.board_url("bigco") == "https://bigco.bamboohr.com/careers/list"

    raw_list = connector.extract(json.dumps(BAMBOOHR_SAMPLE).encode(), "bigco")
    assert len(raw_list) == 1
    raw = raw_list[0]
    assert raw.external_id == "bb-202"

    job = connector.parse(raw)
    assert job.title == "Staff Data Engineer"
    assert job.city == "San Francisco"
    assert job.region == "CA"
    assert job.country_hint == "United States"
    assert job.workplace_type == "remote"
    assert job.employment_type == "Full-Time"
    assert job.departments == ["Data Platform"]
    assert str(job.apply_url) == "https://bigco.bamboohr.com/careers/bb-202"

