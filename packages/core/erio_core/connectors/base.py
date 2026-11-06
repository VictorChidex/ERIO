"""The connector interface every source adapter implements.

Adapters never touch the network or the database themselves. The crawl
pipeline hands them a ``Fetcher`` (which applies the user agent, robots.txt,
per-host rate limits and the host allow-list) and stores what they return.
That keeps every adapter a pure function of its input, testable against
recorded fixtures.
"""

import re
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from erio_core.schemas import PartialJob, RawPosting

FailureOutcome = Literal["http_error", "timeout", "parse_error", "rate_limited"]


@dataclass(frozen=True)
class FetchResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class Fetcher(Protocol):
    def get(self, url: str, etag: str | None = None) -> FetchResponse: ...


@runtime_checkable
class HeaderGetter(Protocol):
    """A fetcher that can GET with extra request headers, for sources whose
    public career sites send one (HiBob's ``companyIdentifier``)."""

    def get_with(self, url: str, headers: dict[str, str]) -> FetchResponse: ...


def header_getter(fetcher: Fetcher) -> HeaderGetter:
    if not isinstance(fetcher, HeaderGetter):
        raise FetchError("http_error", "this fetcher cannot send request headers")
    return fetcher


@runtime_checkable
class JsonPoster(Protocol):
    """A fetcher that can also POST a JSON body, for sources whose public
    career sites search jobs that way (Workday, for example)."""

    def post_json(self, url: str, payload: Any) -> FetchResponse: ...


def poster(fetcher: Fetcher) -> JsonPoster:
    if not isinstance(fetcher, JsonPoster):
        raise FetchError("http_error", "this fetcher cannot POST")
    return fetcher


class FetchError(Exception):
    """A fetch that must not change any job's status (spec section 5, rule 2)."""

    def __init__(self, outcome: FailureOutcome, message: str, http_status: int | None = None):
        super().__init__(message)
        self.outcome: FailureOutcome = outcome
        self.http_status = http_status


@dataclass(frozen=True)
class BoardFetch:
    """A successful fetch: HTTP 200 with a payload that parsed, or 304.

    ``unchanged`` means the source answered 304 Not Modified to our ETag:
    every posting seen last time is still listed, and ``postings`` is empty.

    ``complete`` is False when the connector stopped before the end of a large
    board (a page or detail cap). Postings it did not list are then unknown,
    not gone: the status rules never close anything on an incomplete fetch.
    """

    postings: list[RawPosting]
    http_status: int
    body: bytes
    etag: str | None = None
    unchanged: bool = False
    complete: bool = True


def _fold(name: str) -> str:
    """Fold a name for loose comparison: "Hugging Face, Inc." -> "huggingfaceinc"."""
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", name).lower())


class Connector(ABC):
    slug: str
    #: Hosts this connector may contact; the fetcher refuses anything else.
    hosts: frozenset[str]

    @abstractmethod
    def board_url(self, board_token: str) -> str:
        """URL of the endpoint that lists every posting on one board."""

    @abstractmethod
    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        """Split a board response into postings; raise ValueError if malformed."""

    @abstractmethod
    def parse(self, raw: RawPosting) -> PartialJob:
        """Read what this source says about one posting."""

    def discover(
        self, fetcher: Fetcher, candidates: list[str], company: str | None = None
    ) -> str | None:
        """First candidate token whose board lists postings, if any.

        An empty board is not enough: some sources answer for placeholder
        accounts under well-known names. When the source names the employer
        on its postings, that name must also match ``company``.
        """
        for token in candidates:
            try:
                postings = self.list_postings(fetcher, token).postings
            except (FetchError, ValueError):  # ValueError: not a valid token here
                continue
            if postings and (company is None or self._names_company(postings, company)):
                return token
        return None

    def _names_company(self, postings: list[RawPosting], company: str) -> bool:
        named = set()
        for raw in postings[:5]:
            try:
                named.add(self.parse(raw).company_name)
            except Exception:  # noqa: S112 (an unparseable posting names no one)
                continue
        named.discard(None)
        if not named:
            return True  # the source does not say: the token is all we have
        want = _fold(company)
        return any(want in _fold(n) or _fold(n) in want for n in named if n and _fold(n))

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        response = fetcher.get(self.board_url(board_token), etag)
        if response.status == 304 and etag:
            return BoardFetch([], 304, b"", etag=etag, unchanged=True)
        if response.status == 429:
            raise FetchError("rate_limited", "source rate limit", response.status)
        if response.status != 200:
            raise FetchError("http_error", f"HTTP {response.status}", response.status)
        try:
            postings = self.extract(response.body, board_token)
        except (ValueError, KeyError, TypeError) as error:
            raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
        etag_header = {k.lower(): v for k, v in response.headers.items()}.get("etag")
        return BoardFetch(postings=postings, http_status=200, body=response.body, etag=etag_header)
