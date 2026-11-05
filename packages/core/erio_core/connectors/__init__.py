"""Source connectors: one small adapter per ATS behind one interface (spec section 5)."""

from erio_core.connectors.ashby import AshbyConnector
from erio_core.connectors.bamboohr import BambooHRConnector
from erio_core.connectors.base import (
    BoardFetch,
    Connector,
    Fetcher,
    FetchError,
    FetchResponse,
    JsonPoster,
    poster,
)
from erio_core.connectors.breezy import BreezyConnector
from erio_core.connectors.feed import FeedConnector
from erio_core.connectors.greenhouse import GreenhouseConnector
from erio_core.connectors.lever import LeverConnector
from erio_core.connectors.manatal import ManatalConnector
from erio_core.connectors.personio import PersonioConnector
from erio_core.connectors.pinpoint import PinpointConnector
from erio_core.connectors.polymer import PolymerConnector
from erio_core.connectors.recruitee import RecruiteeConnector
from erio_core.connectors.rippling import RipplingConnector
from erio_core.connectors.smartrecruiters import SmartRecruitersConnector
from erio_core.connectors.teamtailor import TeamtailorConnector
from erio_core.connectors.trakstar import TrakstarConnector
from erio_core.connectors.workable import WorkableConnector

CONNECTORS: dict[str, Connector] = {
    connector.slug: connector
    for connector in (
        GreenhouseConnector(),
        LeverConnector(),
        AshbyConnector(),
        SmartRecruitersConnector(),
        RecruiteeConnector(),
        WorkableConnector(),
        PinpointConnector(),
        TrakstarConnector(),
        PolymerConnector(),
        RipplingConnector(),
        TeamtailorConnector(),
        ManatalConnector(),
        PersonioConnector(),
        BreezyConnector(),
        BambooHRConnector(),
        FeedConnector("niceboard", frozenset({"*.niceboard.co"}), "https://{token}.niceboard.co/rss"),
        FeedConnector("jobboard_io", frozenset({"*.jobboard.io"}), "https://{token}.jobboard.io/jobs.rss"),
        FeedConnector("jobboardly", frozenset({"*.jobboardly.com"}), "https://{token}.jobboardly.com/feed.xml"),
        FeedConnector("wp_job_manager", frozenset(), "https://{token}/feed/?post_type=job_listing"),
        FeedConnector("smartjobboard", frozenset(), "https://{token}/rss/jobs"),
        FeedConnector("jboard", frozenset({"*.jboard.io"}), "https://{token}.jboard.io/rss"),
        FeedConnector("jobkit", frozenset({"*.jobkit.io"}), "https://{token}.jobkit.io/rss"),
        FeedConnector("jobboardfire", frozenset({"*.jobboardfire.com"}), "https://{token}.jobboardfire.com/rss"),
    )
}


def get_connector(slug: str) -> Connector:
    return CONNECTORS[slug]


__all__ = [
    "CONNECTORS",
    "BoardFetch",
    "Connector",
    "FetchError",
    "FetchResponse",
    "Fetcher",
    "JsonPoster",
    "get_connector",
    "poster",
]
