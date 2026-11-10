"""Platforms found by reading the reference site jobindex.space: each reads a public,
anonymous job source (API, widget feed or career pages); see docs/sources.md."""

from erio_core.connectors.base import Connector
from erio_core.connectors.cats import CatsConnector
from erio_core.connectors.clearcompany import ClearCompanyConnector
from erio_core.connectors.feishu import FeishuConnector
from erio_core.connectors.pyjamahr import PyjamaHRConnector
from erio_core.connectors.recruitify import RecruitifyConnector
from erio_core.connectors.schoolspring import SchoolSpringConnector
from erio_core.connectors.velora import VeloraConnector

GROUP_F_CONNECTORS: list[Connector] = [
    CatsConnector(),
    ClearCompanyConnector(),
    FeishuConnector(),
    PyjamaHRConnector(),
    RecruitifyConnector(),
    SchoolSpringConnector(),
    VeloraConnector(),
]
