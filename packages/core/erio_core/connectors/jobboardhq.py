"""jobBoardHQ boards: ASP.NET job boards on their own domains.

``/search`` lists the first 20 jobs and nothing else is public: further pages
and the board's other jobs need form postbacks, which are not read. Each job
page (``/job/{key}/{title}/...``) carries schema.org JobPosting data. Every
crawl is therefore an incomplete fetch, so a job leaving the first page is
never taken as the job closing. The token is ``https://{board}/search``.
"""

from erio_core.connectors.base import BoardFetch, Fetcher
from erio_core.connectors.jsonld import JsonLdConnector


class JobBoardHQConnector(JsonLdConnector):
    def __init__(self) -> None:
        super().__init__("jobboardhq", r"^/job/[a-z0-9]{6}/")

    def list_postings(
        self, fetcher: Fetcher, board_token: str, etag: str | None = None
    ) -> BoardFetch:
        fetched = super().list_postings(fetcher, board_token, etag)
        return BoardFetch(fetched.postings, fetched.http_status, fetched.body, complete=False)
