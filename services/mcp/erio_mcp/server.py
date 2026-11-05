"""ERIO's read-only MCP server (spec section 13: inbound).

AI assistants that speak the Model Context Protocol (Claude, and a growing
number of other assistants and agent tools) can search ERIO's jobs with
four tools: ``search_jobs``, ``get_job``, ``list_countries`` and
``list_platforms``. Every tool calls the public ``/v1`` API, so the same
tokens, rate limits and logging apply: a caller's ``Authorization`` header
is passed on as it is. Nothing here writes anything.

The same tool definitions are published for OpenAI function calling and
Gemini function declarations at ``/tools/openai.json`` and
``/tools/gemini.json``; the website's API page shows them.

    python -m erio_mcp            # streamable HTTP on port 8100, path /mcp
    python -m erio_mcp --stdio    # for assistants that start the server themselves
"""

from collections.abc import Mapping
from typing import Annotated, Any, Literal

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from erio_core.schemas import RemoteStatus, RoleCategory
from erio_core.settings import get_settings

DESCRIPTION_LIMIT = 6000
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)

server = MCPServer(
    name="ERIO",
    title="ERIO job index",
    instructions=(
        "ERIO indexes open jobs from employers' own job boards in every country. Use "
        "search_jobs to find jobs (filter by ISO country codes, remote work, role and "
        "salary), get_job for one job's full description, list_countries for country codes "
        "and job counts, and list_platforms for the sources ERIO reads. Only mention jobs "
        "these tools return, and link each one with its url."
    ),
    version="0.1.0",
)


class ApiError(ToolError):
    """The public API refused or failed; the assistant sees the message."""


def _caller_headers(ctx: Context | None) -> Mapping[str, str]:
    """The HTTP headers the assistant's request came with; none over stdio."""
    try:
        return (ctx.headers if ctx is not None else None) or {}
    except ValueError:  # called outside a request, e.g. directly in tests
        return {}


def api_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=get_settings().api_url, timeout=15.0)


async def _get(path: str, params: dict[str, Any], ctx: Context | None) -> dict[str, Any]:
    headers = {}
    if "authorization" in (caller := _caller_headers(ctx)):
        headers["Authorization"] = caller["authorization"]
    async with api_client() as client:
        try:
            response = await client.get(
                path, params={k: v for k, v in params.items() if v is not None}, headers=headers
            )
        except httpx.HTTPError as error:
            raise ApiError(f"ERIO API unreachable ({type(error).__name__})") from error
    if response.status_code >= 400:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text[:200]
        raise ApiError(f"ERIO API answered {response.status_code}: {message}")
    data: dict[str, Any] = response.json()
    return data


def _salary(job: dict[str, Any]) -> str | None:
    low, high, currency = job.get("salary_min"), job.get("salary_max"), job.get("salary_currency")
    if low is None and high is None:
        return None
    amounts = "–".join(f"{n:,}" for n in (low, high) if n is not None)
    period = job.get("salary_period")
    return f"{currency or ''} {amounts}{f' a {period}' if period else ''}".strip()


def _job(job: dict[str, Any]) -> dict[str, Any]:
    """A job as assistants see it: what a person needs to decide, plus links."""
    return {
        "id": job["canonical_id"],
        "title": job["title"],
        "company": job["company"]["name"],
        "location": job.get("location_text"),
        "country_code": job.get("country_code"),
        "remote_status": job.get("remote_status"),
        "open_to_countries": job.get("eligible_country_codes") or [],
        "role": job.get("role_category"),
        "salary": _salary(job),
        "posted_at": job.get("posted_at"),
        "url": f"{get_settings().site_url.rstrip('/')}/jobs/{job['canonical_id']}",
        "apply_url": job.get("apply_url"),
        "sources": job.get("sources") or [],
    }


def _codes(values: list[str] | None) -> str | None:
    return ",".join(v.strip() for v in values) if values else None


@server.tool(annotations=READ_ONLY)
async def search_jobs(
    query: Annotated[
        str | None, Field(description="Words to find in titles and descriptions")
    ] = None,
    countries: Annotated[
        list[str] | None,
        Field(
            description=(
                "ISO 3166-1 alpha-2 codes, e.g. ['NG', 'KE']. Returns jobs located there "
                "plus remote jobs open to them"
            )
        ),
    ] = None,
    include_worldwide: Annotated[
        bool, Field(description="Also return remote jobs open to any country")
    ] = True,
    remote_status: Annotated[list[RemoteStatus] | None, Field(description="Work types")] = None,
    roles: Annotated[list[RoleCategory] | None, Field(description="Role categories")] = None,
    min_salary_usd: Annotated[
        int | None, Field(ge=0, description="Minimum yearly salary in US dollars")
    ] = None,
    posted_after: Annotated[str | None, Field(description="ISO 8601 date, e.g. 2026-10-01")] = None,
    sort: Annotated[Literal["recent", "salary", "relevance"], Field()] = "recent",
    limit: Annotated[int, Field(ge=1, le=25, description="Jobs to return")] = 10,
    cursor: Annotated[str | None, Field(description="next_cursor from a previous search")] = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Search ERIO's open jobs. Returns the matching jobs, the total and a cursor for more."""
    data = await _get(
        "/v1/jobs",
        {
            "q": query,
            "country": _codes(countries),
            "include_worldwide": str(include_worldwide).lower(),
            "remote_status": _codes(remote_status),  # type: ignore[arg-type]
            "role": _codes(roles),  # type: ignore[arg-type]
            "salary_min_usd": min_salary_usd,
            "posted_after": posted_after,
            "sort": sort,
            "per_page": limit,
            "cursor": cursor,
        },
        ctx,
    )
    return {
        "total": data["meta"]["total"],
        "next_cursor": data["meta"]["next_cursor"],
        "jobs": [_job(job) for job in data["data"]],
    }


@server.tool(annotations=READ_ONLY)
async def get_job(
    job_id: Annotated[str, Field(description="A job id from search_jobs, e.g. j_9f2c...")],
    ctx: Context | None = None,
) -> dict[str, Any]:
    """One job with its full description."""
    job = (await _get(f"/v1/jobs/{job_id}", {}, ctx))["data"]
    text = job.get("description_text") or ""
    return _job(job) | {
        "status": job.get("status"),
        "city": job.get("city"),
        "remote_scope": job.get("remote_scope"),
        "description": text[:DESCRIPTION_LIMIT],
        "description_truncated": len(text) > DESCRIPTION_LIMIT,
    }


@server.tool(annotations=READ_ONLY)
async def list_countries(
    region: Annotated[
        str | None,
        Field(description="Only this region, e.g. Africa, Asia, Europe, Americas, Oceania"),
    ] = None,
    with_jobs_only: Annotated[bool, Field(description="Skip countries with no jobs")] = True,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Countries with their ISO codes and how many jobs a search for each returns."""
    rows = (await _get("/v1/countries", {}, ctx))["data"]
    wanted = (region or "").casefold()
    return {
        "countries": [
            {
                "code": row["code"],
                "name": row["name"],
                "region": row["region"],
                "jobs": row["job_count"],
                "local_jobs": row["local_job_count"],
            }
            for row in rows
            if (not wanted or (row["region"] or "").casefold() == wanted)
            and (row["job_count"] or not with_jobs_only)
        ]
    }


@server.tool(annotations=READ_ONLY)
async def list_platforms(ctx: Context | None = None) -> dict[str, Any]:
    """The job sources ERIO reads, with their status, boards and job counts."""
    rows = (await _get("/v1/platforms", {}, ctx))["data"]
    return {
        "platforms": [
            {
                "slug": row["slug"],
                "name": row["name"],
                "status": row["status"],
                "boards": row["boards"],
                "jobs": row["job_count"],
            }
            for row in rows
        ]
    }


async def tool_definitions() -> list[dict[str, Any]]:
    """Name, description and JSON schema of every tool, as MCP lists them."""
    return [
        {"name": t.name, "description": t.description or "", "parameters": t.input_schema}
        for t in await server.list_tools()
    ]


async def openai_tools() -> list[dict[str, Any]]:
    """The tools as OpenAI function-calling definitions (Chat Completions ``tools``)."""
    return [{"type": "function", "function": tool} for tool in await tool_definitions()]


async def gemini_tools() -> list[dict[str, Any]]:
    """The tools as one Gemini ``tools`` entry of function declarations."""
    return [
        {
            "functionDeclarations": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parametersJsonSchema": tool["parameters"],
                }
                for tool in await tool_definitions()
            ]
        }
    ]


@server.custom_route("/tools/openai.json", methods=["GET"])
async def openai_route(request: Request) -> JSONResponse:
    return JSONResponse(await openai_tools())


@server.custom_route("/tools/gemini.json", methods=["GET"])
async def gemini_route(request: Request) -> JSONResponse:
    return JSONResponse(await gemini_tools())


@server.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})
