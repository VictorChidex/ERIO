"""Source connectors: one small adapter per ATS behind one interface (spec section 5)."""

from erio_core.connectors.ashby import AshbyConnector
from erio_core.connectors.base import (
    BoardFetch,
    Connector,
    Fetcher,
    FetchError,
    FetchResponse,
)
from erio_core.connectors.greenhouse import GreenhouseConnector
from erio_core.connectors.lever import LeverConnector
from erio_core.connectors.recruitee import RecruiteeConnector
from erio_core.connectors.smartrecruiters import SmartRecruitersConnector
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
    "get_connector",
]
