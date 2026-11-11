"""Source connectors: one small adapter per ATS behind one interface (spec section 5)."""

from erio_core.connectors.ashby import AshbyConnector
from erio_core.connectors.ats_extra import ATS_EXTRA_CONNECTORS
from erio_core.connectors.bamboohr import BambooHRConnector
from erio_core.connectors.base import (
    BoardFetch,
    Connector,
    Fetcher,
    FetchError,
    FetchResponse,
    HeaderGetter,
    JsonPoster,
    header_getter,
    poster,
)
from erio_core.connectors.breezy import BreezyConnector
from erio_core.connectors.gem import GemConnector
from erio_core.connectors.gohire import GoHireConnector
from erio_core.connectors.greenhouse import GreenhouseConnector
from erio_core.connectors.group_a import GROUP_A_CONNECTORS
from erio_core.connectors.group_b import GROUP_B_CONNECTORS
from erio_core.connectors.group_c import GROUP_C_CONNECTORS
from erio_core.connectors.group_d import GROUP_D_CONNECTORS
from erio_core.connectors.group_e import GROUP_E_CONNECTORS
from erio_core.connectors.group_f import GROUP_F_CONNECTORS
from erio_core.connectors.hibob import HiBobConnector
from erio_core.connectors.hirehive import HireHiveConnector
from erio_core.connectors.hireology import HireologyConnector
from erio_core.connectors.json_boards import (
    JobboardlyConnector,
    JobKitConnector,
    JoinConnector,
    WPJobManagerConnector,
)
from erio_core.connectors.jsonld_platforms import JSONLD_CONNECTORS
from erio_core.connectors.lever import LeverConnector
from erio_core.connectors.manatal import ManatalConnector
from erio_core.connectors.personio import PersonioConnector
from erio_core.connectors.pinpoint import PinpointConnector
from erio_core.connectors.polymer import PolymerConnector
from erio_core.connectors.public_feeds import PUBLIC_FEED_CONNECTORS
from erio_core.connectors.public_services import PUBLIC_SERVICE_CONNECTORS
from erio_core.connectors.recruitee import RecruiteeConnector
from erio_core.connectors.reference_platforms import REFERENCE_CONNECTORS
from erio_core.connectors.regional import REGIONAL_CONNECTORS
from erio_core.connectors.rippling import RipplingConnector
from erio_core.connectors.smartrecruiters import SmartRecruitersConnector
from erio_core.connectors.teamtailor import TeamtailorConnector
from erio_core.connectors.trakstar import TrakstarConnector
from erio_core.connectors.wave2_3 import WAVE2_3_CONNECTORS
from erio_core.connectors.workable import WorkableConnector
from erio_core.connectors.workday import WorkdayConnector
from erio_core.connectors.xml_boards import (
    HiringThingConnector,
    JazzHRConnector,
    JobBoardIoConnector,
    MadgexConnector,
    PageUpConnector,
    SmartJobBoardConnector,
)

ALL_CONNECTORS: list[Connector] = [
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
    BambooHRConnector(),
    BreezyConnector(),
    GemConnector(),
    GoHireConnector(),
    HiBobConnector(),
    HireHiveConnector(),
    HireologyConnector(),
    HiringThingConnector(),
    JazzHRConnector(),
    PageUpConnector(),
    JoinConnector(),
    JobKitConnector(),
    JobboardlyConnector(),
    WPJobManagerConnector(),
    MadgexConnector(),
    SmartJobBoardConnector(),
    JobBoardIoConnector(),
    WorkdayConnector(),
    *JSONLD_CONNECTORS,
    *GROUP_A_CONNECTORS,
    *GROUP_B_CONNECTORS,
    *GROUP_C_CONNECTORS,
    *GROUP_D_CONNECTORS,
    *GROUP_E_CONNECTORS,
    *GROUP_F_CONNECTORS,
    *PUBLIC_FEED_CONNECTORS,
    *PUBLIC_SERVICE_CONNECTORS,
    *REFERENCE_CONNECTORS,
    *REGIONAL_CONNECTORS,
    *ATS_EXTRA_CONNECTORS,
    *WAVE2_3_CONNECTORS,
]

CONNECTORS: dict[str, Connector] = {connector.slug: connector for connector in ALL_CONNECTORS}


def get_connector(slug: str) -> Connector:
    return CONNECTORS[slug]


__all__ = [
    "CONNECTORS",
    "BoardFetch",
    "Connector",
    "FetchError",
    "FetchResponse",
    "Fetcher",
    "HeaderGetter",
    "JsonPoster",
    "get_connector",
    "header_getter",
    "poster",
]
