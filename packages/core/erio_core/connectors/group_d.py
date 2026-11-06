"""Job-board software platforms: Exenzo, jobBoardHQ and eJobSiteSoftware."""

from erio_core.connectors.base import Connector
from erio_core.connectors.ejobsite import EJobSiteConnector
from erio_core.connectors.exenzo import ExenzoConnector
from erio_core.connectors.jobboardhq import JobBoardHQConnector

GROUP_D_CONNECTORS: list[Connector] = [
    ExenzoConnector(),
    JobBoardHQConnector(),
    EJobSiteConnector(),
]
