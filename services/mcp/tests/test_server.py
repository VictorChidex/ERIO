"""MCP tools against a stand-in for the public API."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from erio_mcp import server as mcp_server
from erio_mcp.server import _get, gemini_tools, openai_tools, server

JOB = {
    "canonical_id": "j_lagos",
    "title": "Backend Engineer",
    "company": {"name": "Paystack", "domain": "paystack.com", "logo_url": None},
    "location_text": "Lagos, Nigeria",
    "country_code": "NG",
    "city": "Lagos",
    "remote_status": "hybrid",
    "remote_scope": None,
    "eligible_country_codes": [],
    "role_category": "engineering",
    "salary_min": 3500000,
    "salary_max": 5000000,
    "salary_currency": "NGN",
    "salary_period": "month",
    "posted_at": "2026-11-01T09:00:00Z",
    "status": "open",
    "apply_url": "https://boards.greenhouse.io/paystack/jobs/1",
    "sources": ["greenhouse", "ashby"],
    "description_text": "x" * 7000,
}


PAY = [
    {
        "currency": "NGN",
        "period": "year",
        "roles": 4,
        "lower": 1.0,
        "median": 2.0,
        "upper": 3.0,
    }
]
COMPANY = {
    "slug": "paystack",
    "name": "Paystack",
    "domain": "paystack.com",
    "logo_url": None,
    "country_code": "NG",
    "tracked_since": "2026-10-01T00:00:00Z",
    "last_checked_at": "2026-11-09T08:00:00Z",
    "open_roles": 12,
    "added_30d": 5,
    "removed_30d": 2,
    "remote_pct": 25.0,
    "pay_stated_pct": 50.0,
    "flow": {"days": [{"date": "2026-11-09", "added": 1, "removed": 0}] * 30},
    "roles": [{"key": "engineering", "label": "Engineering", "count": 9}],
    "countries": [{"key": "NG", "label": "Nigeria", "count": 12}],
    "locations": [{"key": "Lagos", "label": "Lagos", "count": 12}],
    "work_mode": [{"key": "remote", "label": "Remote", "count": 3}],
    "contracts": [{"key": "full_time", "label": "Full time", "count": 12}],
    "posted": [],
    "pay": PAY,
    "platforms": [{"slug": "greenhouse", "name": "Greenhouse", "kind": "ats", "roles": 12}],
    "latest": [
        {
            "canonical_id": "j_lagos",
            "title": "Backend Engineer",
            "location_text": "Lagos, Nigeria",
            "country_code": "NG",
            "remote_status": "hybrid",
            "employment_type": "full_time",
            "posted_at": "2026-11-01T09:00:00Z",
            "indexed_at": "2026-11-01T09:05:00Z",
        }
    ],
}
PULSE = {
    "roles": [{"key": "engineering", "label": "Engineering", "count": 30}],
    "work_mode": [{"key": "remote", "label": "Remote", "count": 10}],
    "pay": PAY,
}
COVERAGE = [
    {
        "slug": slug,
        "name": slug.title(),
        "kind": "ats",
        "status": status,
        "boards_verified": 2,
        "jobs_read": 100,
        "partial_read": False,
        "checked_at": None,
        "note": "",
    }
    for slug, status in [("lever", "Verified"), ("ashby", "Verified"), ("workday", "Blocked")]
]


class Api:
    """Records requests and answers like /v1 does."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/jobs":
            facets = {
                "country": {"DE": 11, "NG": 30},
                "role": {"engineering": 25},
                "remote_status": {"remote": 41},
            }
            meta = {"total": 41, "next_cursor": "c2", "facets": facets}
            return httpx.Response(200, json={"data": [JOB], "meta": meta})
        if path == "/v1/jobs/j_lagos":
            return httpx.Response(200, json={"data": JOB})
        if path == "/v1/countries":
            keys = ("code", "name", "region", "job_count", "local_job_count")
            rows = [
                dict(zip(keys, row, strict=True))
                for row in [
                    ("NG", "Nigeria", "Africa", 12, 9),
                    ("TD", "Chad", "Africa", 0, 0),
                    ("DE", "Germany", "Europe", 80, 70),
                ]
            ]
            return httpx.Response(200, json={"data": rows})
        if path == "/v1/platforms":
            rows = [
                {"slug": "lever", "name": "Lever", "status": "live", "boards": 6, "job_count": 610}
            ]
            return httpx.Response(200, json={"data": rows})
        if path == "/v1/companies":
            rows = [
                {
                    "slug": "paystack",
                    "name": "Paystack",
                    "domain": "paystack.com",
                    "logo_url": None,
                    "country_code": "NG",
                    "open_roles": 12,
                }
            ]
            meta = {"total": 1, "page": 1, "per_page": 10}
            return httpx.Response(200, json={"data": rows, "meta": meta})
        if path == "/v1/companies/paystack":
            return httpx.Response(200, json={"data": COMPANY})
        if path == "/v1/insights/pulse":
            return httpx.Response(200, json={"data": PULSE})
        if path == "/v1/coverage":
            return httpx.Response(200, json={"data": COVERAGE})
        error = {"error": {"code": "not_found", "message": f"no job {path.rsplit('/', 1)[-1]}"}}
        return httpx.Response(404, json=error)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Api:
    recorder = Api()
    factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(  # noqa: E731
        base_url="http://api.test", transport=httpx.MockTransport(recorder)
    )
    monkeypatch.setattr(mcp_server, "api_client", factory)
    return recorder


async def call(name: str, arguments: dict[str, Any]) -> Any:
    result = await server.call_tool(name, arguments)
    assert not result.is_error, result.content
    return result.structured_content


async def test_search_jobs_by_country(api: Api) -> None:
    found = await call(
        "search_jobs",
        {
            "countries": ["NG", "KE"],
            "include_worldwide": False,
            "roles": ["engineering"],
            "limit": 5,
        },
    )

    params = dict(api.requests[0].url.params)
    assert params == {
        "country": "NG,KE",
        "include_worldwide": "false",
        "role": "engineering",
        "sort": "recent",
        "per_page": "5",
    }
    assert (found["total"], found["next_cursor"]) == (41, "c2")
    [job] = found["jobs"]
    assert job["id"] == "j_lagos" and job["company"] == "Paystack"
    assert job["salary"] == "NGN 3,500,000–5,000,000 a month"
    assert job["url"].endswith("/jobs/j_lagos")
    assert job["sources"] == ["greenhouse", "ashby"]
    assert "description_text" not in job


async def test_get_job_has_a_capped_description(api: Api) -> None:
    job = await call("get_job", {"job_id": "j_lagos"})
    assert len(job["description"]) == 6000 and job["description_truncated"]
    assert job["status"] == "open"


async def test_api_errors_come_back_as_tool_errors(api: Api) -> None:
    # Over MCP this becomes an error result the assistant can read.
    with pytest.raises(ToolError, match="404: no job j_missing"):
        await server.call_tool("get_job", {"job_id": "j_missing"})


async def test_list_countries_and_platforms(api: Api) -> None:
    africa = await call("list_countries", {"region": "africa"})
    assert [c["code"] for c in africa["countries"]] == ["NG"]
    every = await call("list_countries", {"with_jobs_only": False})
    assert len(every["countries"]) == 3
    platforms = await call("list_platforms", {})
    assert platforms["platforms"] == [
        {"slug": "lever", "name": "Lever", "status": "live", "boards": 6, "jobs": 610}
    ]


async def test_caller_token_is_passed_to_the_api(api: Api) -> None:
    class Ctx:
        def __init__(self) -> None:
            self.headers = {"authorization": "Bearer erio_test_token"}

    await _get("/v1/platforms", {}, Ctx())  # type: ignore[arg-type]
    await _get("/v1/platforms", {}, None)
    assert api.requests[0].headers["authorization"] == "Bearer erio_test_token"
    assert "authorization" not in api.requests[1].headers


async def test_tools_are_read_only_and_published_for_openai_and_gemini() -> None:
    tools = await server.list_tools()
    assert [t.name for t in tools] == [
        "search_jobs",
        "get_job",
        "list_countries",
        "list_platforms",
        "search_companies",
        "get_company_profile",
        "list_filter_values",
        "job_market_stats",
        "salary_stats",
        "get_coverage",
    ]
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)

    openai = await openai_tools()
    assert openai[0]["type"] == "function"
    assert openai[0]["function"]["name"] == "search_jobs"
    assert "countries" in openai[0]["function"]["parameters"]["properties"]
    # Context is filled by the server, never by the model.
    assert "ctx" not in openai[0]["function"]["parameters"]["properties"]

    [gemini] = await gemini_tools()
    declarations = gemini["functionDeclarations"]
    assert [d["name"] for d in declarations] == [t.name for t in tools]
    assert declarations[1]["parametersJsonSchema"]["required"] == ["job_id"]


async def test_search_companies(api: Api) -> None:
    found = await call("search_companies", {"query": "pay", "country": "ng", "limit": 5})
    assert dict(api.requests[0].url.params) == {
        "q": "pay",
        "country": "ng",
        "sort": "roles",
        "per_page": "5",
        "page": "1",
    }
    assert found["total"] == 1
    assert found["companies"][0]["open_roles"] == 12
    assert found["companies"][0]["url"].endswith("/company/paystack")


async def test_get_company_profile(api: Api) -> None:
    profile = await call("get_company_profile", {"slug": "paystack"})
    assert (profile["added_30d"], profile["removed_30d"]) == (5, 2)
    assert profile["teams"] == [{"role": "engineering", "roles": 9}]
    assert profile["places"] == [{"name": "Lagos", "roles": 12}]
    assert profile["pay"][0]["currency"] == "NGN"
    assert profile["latest"][0]["url"].endswith("/jobs/j_lagos")
    assert "flow" not in profile  # the per-day chart is for the website


async def test_ids_cannot_reach_other_api_paths(api: Api) -> None:
    for name, arguments in [
        ("get_company_profile", {"slug": "../jobs"}),
        ("get_job", {"job_id": "../countries"}),
        ("salary_stats", {"company": "a/b"}),
    ]:
        with pytest.raises(ToolError):
            await server.call_tool(name, arguments)
    assert api.requests == []


async def test_list_filter_values(api: Api) -> None:
    countries = await call("list_filter_values", {"kind": "countries"})
    assert [v["value"] for v in countries["values"]] == ["DE", "NG"]  # most roles first
    employers = await call("list_filter_values", {"kind": "employers", "limit": 3})
    assert employers["values"] == [{"value": "paystack", "name": "Paystack", "roles": 12}]
    roles = await call("list_filter_values", {"kind": "roles"})
    assert roles["values"] == [{"value": "engineering", "name": "Engineering", "roles": 30}]
    platforms = await call("list_filter_values", {"kind": "platforms"})
    assert platforms["values"][0]["value"] == "lever"


async def test_job_market_stats(api: Api) -> None:
    stats = await call("job_market_stats", {"countries": ["NG"], "remote_status": ["remote"]})
    params = dict(api.requests[0].url.params)
    assert params["country"] == "NG" and params["remote_status"] == "remote"
    assert params["per_page"] == "1"
    assert stats["matching_jobs"] == 41
    assert stats["by_country"] == [{"code": "NG", "jobs": 30}, {"code": "DE", "jobs": 11}]
    assert stats["by_work_mode"] == {"remote": 41}


async def test_salary_stats(api: Api) -> None:
    market = await call("salary_stats", {})
    assert market["scope"] == "market" and market["quartiles"][0]["median"] == 2.0
    assert api.requests[0].url.path == "/v1/insights/pulse"
    company = await call("salary_stats", {"company": "paystack"})
    assert company["scope"] == "company:paystack"
    assert api.requests[1].url.path == "/v1/companies/paystack"


async def test_get_coverage(api: Api) -> None:
    every = await call("get_coverage", {})
    assert every["platforms_total"] == 3
    assert every["by_status"] == {"Verified": 2, "Blocked": 1}
    blocked = await call("get_coverage", {"status": "blocked"})
    assert [p["slug"] for p in blocked["platforms"]] == ["workday"]
    assert {r.url.path for r in api.requests} == {"/v1/coverage"}
