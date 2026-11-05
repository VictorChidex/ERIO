"""Source connectors: one small adapter per ATS behind one interface (spec section 5)."""

from erio_core.connectors.base import (
    BoardFetch,
    Connector,
    Fetcher,
    FetchError,
    FetchResponse,
)
from erio_core.connectors.greenhouse import GreenhouseConnector

CONNECTORS: dict[str, Connector] = {
    connector.slug: connector for connector in (GreenhouseConnector(),)
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
