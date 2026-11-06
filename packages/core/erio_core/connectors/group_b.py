"""Connectors for BrassRing, Taleo, Phenom People, Oracle Recruiting, CSOD and TriNet Hire."""

from erio_core.connectors.base import Connector
from erio_core.connectors.brassring import BrassRingConnector
from erio_core.connectors.csod import CsodConnector
from erio_core.connectors.oracle_recruiting import OracleRecruitingConnector
from erio_core.connectors.phenom import PhenomConnector
from erio_core.connectors.taleo import TaleoConnector
from erio_core.connectors.trinet import TriNetConnector

GROUP_B_CONNECTORS: list[Connector] = [
    BrassRingConnector(),
    TaleoConnector(),
    PhenomConnector(),
    OracleRecruitingConnector(),
    CsodConnector(),
    TriNetConnector(),
]
