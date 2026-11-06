"""Platforms read from HTML pages, sitemaps and embedded job data."""

from erio_core.connectors.avature import AvatureConnector
from erio_core.connectors.base import Connector
from erio_core.connectors.jobvite import JobviteConnector
from erio_core.connectors.successfactors import SuccessFactorsConnector
from erio_core.connectors.ultipro import UltiProConnector
from erio_core.connectors.werecruit import WeRecruitConnector
from erio_core.connectors.zohorecruit import ZohoRecruitConnector

GROUP_C_CONNECTORS: list[Connector] = [
    AvatureConnector(),
    JobviteConnector(),
    SuccessFactorsConnector(),
    UltiProConnector(),
    WeRecruitConnector(),
    ZohoRecruitConnector(),
]
