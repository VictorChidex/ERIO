"""CV match, stateless and explainable (no AI model): POST /v1/match and friends.

The CV text (or the skill ids already read from it) is used for this one request and never
stored or logged. Skills come from a curated lexicon (``erio_core/data/skills.json``); each
job is scored by how much of what it asks for the CV covers, and every score comes with the
words behind it.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from opensearchpy import OpenSearch
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from erio_api.access import Caller, rate_limit, redis_client
from erio_api.deps import engine, run_search, search_alias, search_client
from erio_api.errors import ApiError
from erio_api.routes.workspace import bucket_limit
from erio_api.search import record_from_source
from erio_core import skills
from erio_core.db.models import Company, Job
from erio_core.schemas import JobRecord
from erio_core.search.params import SearchParams
from erio_core.search.query import build_search

MATCH_PER_MINUTE = 60
MAX_CV_CHARS = 30_000
CANDIDATES = 200

router = APIRouter(prefix="/v1/match", tags=["cv-match"], dependencies=[Depends(rate_limit)])


class SkillOut(BaseModel):
    id: str
    label: str
    cat: str


class CvIn(BaseModel):
    """A CV as text, or the skill ids a previous call read from it (one is enough)."""

    model_config = ConfigDict(extra="forbid")

    cv_text: str | None = Field(default=None, max_length=MAX_CV_CHARS)
    skills: list[str] | None = Field(default=None, max_length=150)


class MatchIn(CvIn):
    filters: SearchParams = Field(default_factory=SearchParams)
    limit: int = Field(default=20, ge=1, le=50)


class RankedJob(BaseModel):
    job: JobRecord
    score: int
    matched: list[SkillOut]
    missing: list[SkillOut]
    explanation: str


class MatchOut(BaseModel):
    skills: list[SkillOut]
    data: list[RankedJob]
    meta: dict[str, int]


class JobMatchOut(BaseModel):
    score: int
    matched: list[SkillOut]
    missing: list[SkillOut]
    required: list[SkillOut]
    explanation: str
    kit: str


class SkillsOut(BaseModel):
    skills: list[SkillOut]


def _out(ids: list[str]) -> list[SkillOut]:
    return [SkillOut(id=s.id, label=s.label, cat=s.cat) for i in ids if (s := skills.skill_for(i))]


def _cv_skills(body: CvIn) -> list[str]:
    if body.cv_text and body.cv_text.strip():
        found = skills.extract_skills(body.cv_text)
    elif body.skills:
        found = skills.known_ids(body.skills)
    else:
        raise ApiError(400, "invalid_parameter", "send cv_text or skills")
    if not found:
        raise ApiError(
            422,
            "no_skills_found",
            "no skills, tools, licences or languages were recognised; add more detail",
        )
    return found


def _limit_matches(redis: Redis, caller: Caller) -> None:
    bucket_limit(redis, f"match:{caller.key}", MATCH_PER_MINUTE, "CV matches")


@router.post("/skills", response_model=SkillsOut, summary="Skills found in a CV (nothing stored)")
def read_skills(
    body: CvIn,
    caller: Annotated[Caller, Depends(rate_limit)],
    redis: Annotated[Redis, Depends(redis_client)],
) -> dict[str, Any]:
    _limit_matches(redis, caller)
    return {"skills": _out(_cv_skills(body))}


@router.post("", response_model=MatchOut, summary="Rank open jobs by overlap with a CV")
def match_jobs(
    body: MatchIn,
    caller: Annotated[Caller, Depends(rate_limit)],
    redis: Annotated[Redis, Depends(redis_client)],
    client: Annotated[OpenSearch, Depends(search_client)],
    alias: Annotated[str, Depends(search_alias)],
) -> dict[str, Any]:
    _limit_matches(redis, caller)
    cv = _cv_skills(body)
    phrases = skills.search_phrases(cv)
    search = build_search(body.filters.to_query(per_page=CANDIDATES))
    search.pop("aggs", None)
    search.pop("search_after", None)
    # Candidates: open jobs (and the caller's filters) that mention any of the CV's skills,
    # best text match first. The ranking below uses the lexicon, not the text score.
    search["query"]["bool"]["should"] = [
        {"multi_match": {"query": p, "type": "phrase", "fields": ["title^2", "description_text"]}}
        for p in phrases
    ]
    search["query"]["bool"]["minimum_should_match"] = 1
    search["sort"] = [{"_score": "desc"}, {"canonical_id": "asc"}]
    search["_source"] = True
    search["track_total_hits"] = False
    hits = run_search(client, alias, search)["hits"]["hits"]

    ranked: list[tuple[int, int, dict[str, Any], skills.Match]] = []
    for position, hit in enumerate(hits):
        source = hit["_source"]
        job_skills = skills.extract_skills(
            f"{source.get('title', '')}\n{source.get('description_text') or ''}"
        )
        result = skills.compare(cv, job_skills)
        if result.matched:
            ranked.append((result.score, -position, source, result))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    data = [
        {
            "job": record_from_source(source),
            "score": result.score,
            "matched": _out(result.matched),
            "missing": _out(skills.by_weight(result.missing)),
            "explanation": result.explanation(),
        }
        for _, _, source, result in ranked[: body.limit]
    ]
    return {
        "skills": _out(cv),
        "data": data,
        "meta": {"candidates": len(hits), "matched": len(ranked)},
    }


@router.post(
    "/job/{canonical_id}",
    response_model=JobMatchOut,
    summary="One job's requirements against a CV, with an apply kit",
)
def match_one(
    canonical_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,40}$")],
    body: CvIn,
    caller: Annotated[Caller, Depends(rate_limit)],
    redis: Annotated[Redis, Depends(redis_client)],
    db: Annotated[Engine, Depends(engine)],
) -> dict[str, Any]:
    _limit_matches(redis, caller)
    cv = _cv_skills(body)
    with Session(db) as session:
        job = session.get(Job, canonical_id)
        if job is None or job.review_reason is not None or job.merged_into is not None:
            raise ApiError(404, "not_found", f"no job {canonical_id}")
        company = session.get(Company, job.company_id)
        title = job.title
        employer = company.name if company else "the employer"
        text = f"{job.title}\n{job.description_text or ''}"
    required = skills.by_weight(skills.extract_skills(text))
    result = skills.compare(cv, required)
    return {
        "score": result.score,
        "matched": _out(result.matched),
        "missing": _out(skills.by_weight(result.missing)),
        "required": _out(required),
        "explanation": result.explanation(),
        "kit": skills.apply_kit(
            title=title,
            company=employer,
            matched=result.matched,
            missing=result.missing,
            required=required,
        ),
    }
