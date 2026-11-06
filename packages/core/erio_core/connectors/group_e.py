"""Platforms whose career pages load jobs through an anonymous visitor session."""

from erio_core.connectors.base import Connector
from erio_core.connectors.dayforce import DayforceConnector
from erio_core.connectors.talentreef import TalentReefConnector

GROUP_E_CONNECTORS: list[Connector] = [
    DayforceConnector(),
    TalentReefConnector(),
]
