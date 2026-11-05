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


class Api:
    """Records requests and answers like /v1 does."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/jobs":
            meta = {"total": 41, "next_cursor": "c2", "facets": {}}
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
    assert [t.name for t in tools] == ["search_jobs", "get_job", "list_countries", "list_platforms"]
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
