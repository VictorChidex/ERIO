"""Base for platforms whose career sites read a public JSON job list.

A platform says where page N of a board's list is, which items in the
response are jobs, whether more pages follow, and how one job reads
(``parse``). If its list leaves out descriptions, it also says where one
job's detail lives; details are fetched for up to ``max_details`` jobs a
crawl, and a failing detail never fails the board.
"""

import json
from abc import abstractmethod
from typing import Any

from erio_core.connectors.base import BoardFetch, Connector, Fetcher, FetchError, FetchResponse
from erio_core.schemas import RawPosting

MAX_PAGES = 50
MAX_DETAILS = 300


class PagedJsonConnector(Connector):
    max_pages = MAX_PAGES
    max_details = MAX_DETAILS

    @abstractmethod
    def list_url(self, board_token: str, page: int) -> str:
        """Page ``page`` (from 1) of a board's job list."""

    def board_url(self, board_token: str) -> str:
        return self.list_url(board_token, 1)

    @abstractmethod
    def items(self, data: Any) -> list[dict[str, Any]]:
        """The jobs in one page of the response."""

    def has_more(self, data: Any, items: list[dict[str, Any]], page: int) -> bool:
        """Whether page ``page + 1`` exists; one page by default."""
        return False

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item["id"])

    def detail_url(self, board_token: str, item: dict[str, Any]) -> str | None:
        """Where one job's full detail is, when the list lacks it."""
        return None

    def extract(self, body: bytes, board_token: str) -> list[RawPosting]:
        return [self._raw(board_token, item) for item in self.items(json.loads(body))]

    def _raw(self, board_token: str, item: dict[str, Any]) -> RawPosting:
        return RawPosting(
            source_slug=self.slug,
            board_token=board_token,
            external_id=self.item_id(item),
            payload=item,
        )

    def fetch_page(self, fetcher: Fetcher, board_token: str, page: int) -> FetchResponse:
        return fetcher.get(self.list_url(board_token, page))

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        jobs: list[dict[str, Any]] = []
        first: FetchResponse | None = None
        for page in range(1, self.max_pages + 1):
            response = self.fetch_page(fetcher, board_token, page)
            first = first or response
            if response.status == 429:
                raise FetchError("rate_limited", "source rate limit", 429)
            if response.status != 200:
                if page > 1 and response.status == 404:
                    break  # some sources answer 404 past the last page
                raise FetchError("http_error", f"HTTP {response.status}", response.status)
            try:
                data = json.loads(response.body)
                found = self.items(data)
            except (ValueError, KeyError, TypeError) as error:
                raise FetchError("parse_error", f"malformed payload: {error}", 200) from error
            jobs += found
            if not found or not self.has_more(data, found, page):
                break
        for item in jobs[: self.max_details]:
            url = self.detail_url(board_token, item)
            if url is None:
                break
            try:
                response = fetcher.get(url)
                if response.status == 200:
                    item["detail"] = json.loads(response.body)
            except (FetchError, ValueError):
                continue
        postings = [self._raw(board_token, item) for item in jobs]
        return BoardFetch(postings=postings, http_status=200, body=first.body if first else b"")
