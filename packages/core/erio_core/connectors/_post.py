"""A fetcher that can POST JSON with extra request headers.

Taleo needs a ``tz`` header and BrassRing an anti-forgery header that its own
public search page issues. ``PoliteFetcher.post_json`` sends none, so these
connectors need a fetcher that also offers ``post_json_with``.
"""

from typing import Any, Protocol, runtime_checkable

from erio_core.connectors.base import Fetcher, FetchError, FetchResponse


@runtime_checkable
class HeaderPoster(Protocol):
    def post_json_with(self, url: str, payload: Any, headers: dict[str, str]) -> FetchResponse: ...


def header_poster(fetcher: Fetcher) -> HeaderPoster:
    if not isinstance(fetcher, HeaderPoster):
        raise FetchError("http_error", "this fetcher cannot POST with headers")
    return fetcher
