"""ADP, ApplicantPro, iSolvedHire, Comeet, Eightfold AI and Paylocity.

Dayforce is not here: its job search needs a session cookie and a CSRF header,
which the polite fetcher does not send.
"""

from erio_core.connectors.adp import ADPConnector
from erio_core.connectors.applicantpro import ApplicantProConnector
from erio_core.connectors.base import Connector
from erio_core.connectors.comeet import ComeetConnector
from erio_core.connectors.eightfold import EightfoldConnector
from erio_core.connectors.paylocity import PaylocityConnector

GROUP_A_CONNECTORS: list[Connector] = [
    ADPConnector(),
    ApplicantProConnector("applicantpro", "applicantpro.com"),
    ApplicantProConnector("isolvedhire", "isolvedhire.com"),
    ComeetConnector(),
    EightfoldConnector(),
    PaylocityConnector(),
]
