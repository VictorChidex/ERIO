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
from erio_core.connectors.json_ats import (
    ComeetConnector,
    FreshteamConnector,
    GenericJsonAtsConnector,
    JoinConnector,
    WorkdayConnector,
)
from erio_core.connectors.jsonld import JsonLdConnector
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

ALL_CONNECTORS: list[Connector] = [
    # 1. First-release and dedicated ATS connectors
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
    ComeetConnector(),
    FreshteamConnector(),
    JoinConnector(),
    WorkdayConnector(),
    # 2. JSON-based ATS
    GenericJsonAtsConnector("gohire", frozenset({"*.gohire.io"}), "https://{token}.gohire.io/jobs.json"),
    GenericJsonAtsConnector("hirehive", frozenset({"*.hirehive.com"}), "https://{token}.hirehive.com/api/v1/jobs"),
    GenericJsonAtsConnector("hiringthing", frozenset({"*.hiringthing.com"}), "https://{token}.hiringthing.com/api/v1/jobs"),
    GenericJsonAtsConnector("hibob", frozenset({"*.hibob.com"}), "https://{token}.hibob.com/api/jobs"),
    GenericJsonAtsConnector("gem", frozenset({"jobs.gem.com"}), "https://jobs.gem.com/{token}/jobs.json"),
    GenericJsonAtsConnector("dover", frozenset({"api.dover.io"}), "https://api.dover.io/jobs/{token}"),
    GenericJsonAtsConnector("deel", frozenset({"jobs.deel.com"}), "https://jobs.deel.com/api/jobs/{token}"),
    # 3. Feed-based ATS
    FeedConnector("jazzhr", frozenset({"*.applytojob.com"}), "https://{token}.applytojob.com/feed"),
    FeedConnector("jobvite", frozenset({"jobs.jobvite.com"}), "https://jobs.jobvite.com/{token}/jobs/rss"),
    FeedConnector("careerplug", frozenset({"*.careerplug.com"}), "https://{token}.careerplug.com/jobs.rss"),
    FeedConnector("zoho_recruit", frozenset({"*.zohorecruit.com", "*.zohorecruit.eu"}), "https://{token}.zohorecruit.com/jobs/rss"),
    FeedConnector("recooty", frozenset({"*.recooty.com"}), "https://{token}.recooty.com/feed"),
    FeedConnector("applicantpro", frozenset({"*.applicantpro.com"}), "https://{token}.applicantpro.com/jobs/rss"),
    FeedConnector("hirebridge", frozenset({"*.hirebridge.com"}), "https://{token}.hirebridge.com/v3/jobs/rss"),
    FeedConnector("hireology", frozenset({"*.hireology.com"}), "https://{token}.hireology.com/jobs/rss"),
    FeedConnector("isolvedhire", frozenset({"*.isolvedhire.com"}), "https://{token}.isolvedhire.com/jobs/rss"),
    FeedConnector("rival", frozenset(), "https://{token}/jobs/rss"),
    FeedConnector("trinet", frozenset({"*.trinet.com"}), "https://{token}.trinet.com/jobs/rss"),
    FeedConnector("ultipro", frozenset({"*.ultipro.com"}), "https://{token}.ultipro.com/jobs/rss"),
    FeedConnector("werecruit", frozenset({"*.werecruit.io"}), "https://{token}.werecruit.io/jobs/rss"),
    # 4. Schema.org JSON-LD ATS
    JsonLdConnector("icims", r"/jobs/\d+", hosts=frozenset({"*.icims.com"})),
    JsonLdConnector("taleo", r"/careersection/", hosts=frozenset({"*.taleo.net"})),
    JsonLdConnector("csod", r"/careers/", hosts=frozenset({"*.csod.com"})),
    JsonLdConnector("brassring", r"/TGnewUI/", hosts=frozenset({"*.brassring.com"})),
    JsonLdConnector("avature", r"/job/", hosts=frozenset({"*.avature.net"})),
    JsonLdConnector("adp", r"/career/", hosts=frozenset({"*.adp.com", "workforcenow.adp.com"})),
    JsonLdConnector("dayforce", r"/CandidatePortal/", hosts=frozenset({"*.dayforcehcm.com"})),
    JsonLdConnector("oracle_recruiting", r"/candidateExperience/", hosts=frozenset({"*.oraclecloud.com"})),
    JsonLdConnector("successfactors", r"/career", hosts=frozenset({"*.successfactors.com", "*.successfactors.eu"})),
    JsonLdConnector("eightfold", r"/careers", hosts=frozenset({"*.eightfold.ai"})),
    JsonLdConnector("phenom", r"/job/", hosts=frozenset({"*.phenompeople.com"})),
    JsonLdConnector("paradox", r"/jobs?", hosts=frozenset({"*.paradox.ai"})),
    JsonLdConnector("firststage", r"/jobs?", hosts=frozenset({"*.firststage.co"})),
    JsonLdConnector("kula", r"/jobs?", hosts=frozenset({"*.kula.ai"})),
    JsonLdConnector("pageup", r"/job/", hosts=frozenset({"*.pageuppeople.com"})),
    JsonLdConnector("paylocity", r"/jobs?", hosts=frozenset({"*.paylocity.com", "recruiting.paylocity.com"})),
    # 5. Job-Board platforms
    FeedConnector("niceboard", frozenset({"*.niceboard.co"}), "https://{token}.niceboard.co/rss"),
    FeedConnector("wp_job_manager", frozenset(), "https://{token}/feed/?post_type=job_listing"),
    FeedConnector("jobkit", frozenset({"*.jobkit.io"}), "https://{token}.jobkit.io/rss"),
    FeedConnector("jobboardly", frozenset({"*.jobboardly.com"}), "https://{token}.jobboardly.com/feed.xml"),
    FeedConnector("jobiqo", frozenset(), "https://{token}/jobs/feed"),
    FeedConnector("jboard", frozenset({"*.jboard.io"}), "https://{token}.jboard.io/rss"),
    FeedConnector("jobboardfire", frozenset({"*.jobboardfire.com"}), "https://{token}.jobboardfire.com/rss"),
    FeedConnector("smartjobboard", frozenset(), "https://{token}/rss/jobs"),
    FeedConnector("jobboard_io", frozenset({"*.jobboard.io"}), "https://{token}.jobboard.io/jobs.rss"),
    FeedConnector("madgex", frozenset(), "https://{token}/jobs/rss"),
    FeedConnector("jobmount", frozenset(), "https://{token}/jobs/rss"),
    FeedConnector("careersitecloud", frozenset(), "https://{token}/rss"),
    FeedConnector("jobboard_com", frozenset(), "https://{token}/feed"),
    FeedConnector("artha", frozenset(), "https://{token}/feed"),
    FeedConnector("jobboardsoftware", frozenset(), "https://{token}/feed"),
    FeedConnector("jobboardhq", frozenset(), "https://{token}/feed"),
    FeedConnector("nodex", frozenset(), "https://{token}/rss"),
    FeedConnector("ejobboard", frozenset(), "https://{token}/rss"),
    FeedConnector("ejobsitesoftware", frozenset(), "https://{token}/rss"),
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
    "JsonPoster",
    "get_connector",
    "poster",
]
