"""The connector interface every source adapter implements.

Adapters never touch the network or the database themselves. The crawl
pipeline hands them a ``Fetcher`` (which applies the user agent, robots.txt,
per-host rate limits and the host allow-list) and stores what they return.
That keeps every adapter a pure function of its input, testable against
recorded fixtures.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from erio_core.schemas import PartialJob, RawPosting

FailureOutcome = Literal["http_error", "timeout", "parse_error", "rate_limited"]


@dataclass(frozen=True)
class FetchResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class Fetcher(Protocol):
    def get(self, url: str, etag: str | None = None) -> FetchResponse: ...


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
    """

    postings: list[RawPosting]
    http_status: int
    body: bytes
    etag: str | None = None
    unchanged: bool = False


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

    def discover(self, fetcher: Fetcher, candidates: list[str]) -> str | None:
        """First candidate board token that answers with a valid board, if any."""
        for token in candidates:
            try:
                self.list_postings(fetcher, token)
            except FetchError:
                continue
            return token
        return None

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
