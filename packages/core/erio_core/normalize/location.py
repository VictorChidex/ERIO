"""Resolve a job's location: country, city, remote status and remote scope.

Order of evidence (spec section 6): the location text first, then the
source's structured hints (offices), all against the offline gazetteer.
Remote roles get the countries they accept: one country, a region's
countries, or worldwide. Anything that cannot be resolved is flagged for
the review queue and is not shown under any country.

A location string is split into segments (";", "•", "|", " or ", ...),
each segment into tokens (",", " - ", parentheses). Countries named anywhere
in a segment guide the city lookup, so "Victoria, Australia" is the
Australian state, not Victoria in Hong Kong.
"""

import re
from dataclasses import dataclass, field

from erio_core.normalize.gazetteer import City, Gazetteer, fold, gazetteer
from erio_core.schemas import RemoteScope, RemoteStatus

SEGMENT_SPLIT = re.compile(r"\s*(?:;|•|·|\||\s/\s|\bor\b|&|\n)\s*", re.IGNORECASE)
TOKEN_SPLIT = re.compile(r"\s*(?:,|\(|\)|/|\s[-\N{EN DASH}\N{EM DASH}:]\s)\s*")
# "US-Remote", "Remote-UK", "US-Chicago": a short code or work word joined by
# a hyphen. Hyphens inside names ("Tel Aviv-Yafo", "Winston-Salem") stay.
PREFIXED = re.compile(r"^([A-Z]{2,3}|remote|hybrid)-(.+)$|^(.+)-([A-Z]{2,3}|remote|hybrid)$", re.I)

REMOTE = re.compile(
    r"\b(remote|anywhere|distributed|work from home|wfh|home[- ]based|virtual|telecommute)\b",
    re.IGNORECASE,
)
HYBRID = re.compile(r"\bhybrid\b", re.IGNORECASE)
NOISE = re.compile(
    r"\b(remote|hybrid|on[- ]?site|in[- ]office|office[- ]based|in person|anywhere|distributed|"
    r"work from home|wfh|home[- ]based|virtual|telecommute|only|based|first|friendly|"
    r"metro area|area|metropolitan|greater|hq|headquarters|office|n/?a|tbd|multiple locations?)\b",
    re.IGNORECASE,
)

# Region phrases a location can name, and the country group each means.
REGIONS = {
    "emea": "EMEA", "europe": "EUROPE", "eu": "EU", "european union": "EU",
    "latam": "LATAM", "latin america": "LATAM", "south america": "LATAM",
    "apac": "APAC", "asia pacific": "APAC", "asia-pacific": "APAC",
    "africa": "AFRICA", "north america": "NORTH_AMERICA", "americas": "AMERICAS",
}  # fmt: skip
WORLDWIDE = {"worldwide", "global", "globally", "international", "anywhere", "world", "earth"}

# A name that is both a city and a state means the city when the city is big
# (Lagos, Mexico City) and the state otherwise (Victoria, Bauchi).
BIG_CITY = 500_000


@dataclass
class Place:
    country: str
    city: City | None = None
    region: str | None = None


@dataclass
class Segment:
    places: list[Place] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    remote: bool = False
    hybrid: bool = False
    worldwide: bool = False


@dataclass(frozen=True)
class LocationResult:
    country_code: str | None
    city: str | None
    region: str | None
    lat: float | None
    lon: float | None
    remote_status: RemoteStatus
    remote_scope: RemoteScope | None
    eligible_country_codes: list[str]
    review_reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.review_reason is None


def _tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_SPLIT.split(text):
        raw = raw.strip(" .-\t")
        match = PREFIXED.match(raw)
        if match:
            tokens.extend(part for part in match.groups() if part)
        elif raw:
            tokens.append(raw)
    return tokens


# "Remote in the US", "Remote within Nigeria": the place follows a preposition.
LEADING_PREPOSITION = re.compile(r"^(?:in|within|across|from)\s+(?:the\s+)?", re.IGNORECASE)


def _clean(token: str) -> str:
    return LEADING_PREPOSITION.sub("", fold(NOISE.sub(" ", token)))


class _SegmentReader:
    """Reads the tokens of one segment left to right, building places."""

    def __init__(self, text: str, g: Gazetteer):
        self.g = g
        self.segment = Segment(remote=bool(REMOTE.search(text)), hybrid=bool(HYBRID.search(text)))
        self.tokens = _tokens(text)
        self.current: Place | None = None
        self.countries = self._find_countries()
        # Countries named anywhere in the segment, for city lookups.
        self.named = [code for code in self.countries if code is not None]

    def _find_countries(self) -> list[str | None]:
        """The country each token names, if any.

        A name that is also a state of another country named in the same
        segment means the state: "Georgia, USA" is the US state.
        """
        found = [
            None if self._state_code(i) else self.g.country(t.strip()) or self.g.country(_clean(t))
            for i, t in enumerate(self.tokens)
        ]
        for i, code in enumerate(found):
            if code is None:
                continue
            others = {other for j, other in enumerate(found) if j != i and other}
            state = next((self.g.admin1(_clean(self.tokens[i]), c) for c in others), None)
            if state:
                found[i] = None
        return found

    def read(self) -> Segment:
        for i in range(len(self.tokens)):
            self._read(i)
        return self.segment

    def _state_code(self, i: int) -> tuple[str, str] | None:
        """(country, state name) if token i is a state code after a city in it."""
        code = self.tokens[i].strip()
        if i == 0 or not 2 <= len(code) <= 3 or not code.isupper():
            return None
        previous = _clean(self.tokens[i - 1])
        for country, states in self.g.state_codes.items():
            if code in states:
                city = self.g.city(previous, country)
                if city and city.admin1 == self.g.admin1_code(country, code):
                    return country, states[code]
        return None

    def _as_country(self, i: int) -> str | None:
        return self.countries[i]

    def _add(self, place: Place) -> None:
        self.segment.places.append(place)
        self.current = place

    def _lookup(self, name: str, i: int) -> tuple[City | None, tuple[str, str] | None]:
        """City and state matching ``name``, searched where the context points."""
        current = self.current
        if current and current.city is None:
            # A bare country just before narrows the search ("Nigeria, Lagos").
            countries: list[str | None] = [current.country]
        elif state := self._state_code(i + 1) if i + 1 < len(self.tokens) else None:
            countries = [state[0]]  # "Cambridge, MA": the state picks the country
        else:
            countries = [*self.named, None]  # "Victoria, Australia", then anywhere
        for country in countries:
            # Aliases first ("San Francisco Bay Area"), then the cleaned name.
            for key in dict.fromkeys((fold(self.tokens[i]), name)):
                city, admin = self.g.city(key, country), self.g.admin1(key, country)
                if city or admin:
                    return city, admin
        return None, None

    def _read(self, i: int) -> None:
        token, current = self.tokens[i], self.current
        folded = fold(token)
        if folded in WORLDWIDE:
            self.segment.worldwide = True
            return
        cleaned = _clean(token)
        if not cleaned:
            return
        if cleaned in REGIONS:
            self.segment.groups.append(REGIONS[cleaned])
            return
        if self._state_code(i):
            return  # "Austin, TX": the city already carries its state

        country = self._as_country(i)
        if country:
            if not (current and current.country == country):
                self._add(Place(country))
            return

        city, admin = self._lookup(cleaned, i)
        if city and admin and admin[0] == city.country and city.population < BIG_CITY:
            city = None
        if not city and not admin and self._split_trailing_country(cleaned):
            return

        if city:
            if current and current.city == city:
                return  # "New York, New York"
            if current and current.city is None and current.country == city.country:
                current.city, current.region = city, self.g.region_name(city)
                return
            self._add(Place(city.country, city, self.g.region_name(city)))
            return

        if admin:
            state_country, state_code = admin
            if current and current.country == state_country:
                if current.city is None:
                    current.region = self.g.region_label(state_country, state_code)
                    return
                if current.city.admin1 == state_code:
                    return  # "Chicago, Illinois"
            self._add(Place(state_country, region=self.g.region_label(state_country, state_code)))

    def _split_trailing_country(self, cleaned: str) -> bool:
        """'Toronto Canada', 'Lagos Nigeria': a place and its country with no comma."""
        words = cleaned.split()
        for size in (3, 2, 1):
            if len(words) <= size:
                continue
            country = self.g.country(" ".join(words[-size:]))
            if not country:
                continue
            city = self.g.city(" ".join(words[:-size]), country)
            self._add(Place(country, city, self.g.region_name(city) if city else None))
            return True
        return False


def _countries_for(groups: list[str], g: Gazetteer) -> list[str]:
    codes: list[str] = []
    for group in groups:
        for code, country in g.countries.items():
            in_group = group in country.region_groups or (
                group == "AMERICAS" and ("LATAM" in country.region_groups or code in {"US", "CA"})
            )
            if in_group and code not in codes:
                codes.append(code)
    return codes


def resolve_location(
    text: str | None,
    city_hint: str | None = None,
    country_hint: str | None = None,
    workplace_type: RemoteStatus | None = None,
) -> LocationResult:
    g = gazetteer()
    parts = [part for part in SEGMENT_SPLIT.split(text or "") if part and part.strip()]
    segments = [_SegmentReader(part, g).read() for part in parts]

    remote = workplace_type == "remote" or any(s.remote for s in segments)
    hybrid = workplace_type == "hybrid" or any(s.hybrid for s in segments)
    worldwide = any(s.worldwide for s in segments)
    places = [p for s in segments for p in s.places]
    groups = [grp for s in segments for grp in s.groups]

    if not places and not groups:
        # Nothing usable in the text ("Hybrid", "In-Office"): use the hints.
        hint = ", ".join(h for h in (city_hint, country_hint) if h)
        if hint:
            places = _SegmentReader(hint, g).read().places

    # "Global", "Worldwide" with no place: a remote role open anywhere.
    remote = remote or (worldwide and not places and not groups)
    status: RemoteStatus = "remote" if remote else "hybrid" if hybrid else "onsite"
    countries = list(dict.fromkeys(p.country for p in places))
    first = places[0] if places else None

    if status == "remote":
        if worldwide or (not countries and not groups):
            # Remote with no place in the text or the office hints: open worldwide.
            return LocationResult(None, None, None, None, None, "remote", "worldwide", [])
        eligible = list(dict.fromkeys(countries + _countries_for(groups, g)))
        if len(eligible) == 1:
            return _with_place(first, eligible[0], status, "country", eligible, g)
        return _with_place(first, None, status, "region", eligible, g)

    if not countries:
        reason = f"no country found in {text!r}" if text else "no location given"
        return LocationResult(None, None, None, None, None, status, None, [], review_reason=reason)
    # Several countries for an on-site or hybrid role: listed so a filter on
    # any of them finds it; country_code is the first.
    eligible = countries if len(countries) > 1 else []
    return _with_place(first, countries[0], status, None, eligible, g)


def _with_place(
    place: Place | None,
    country: str | None,
    status: RemoteStatus,
    scope: RemoteScope | None,
    eligible: list[str],
    g: Gazetteer,
) -> LocationResult:
    same_country = place is not None and country is not None and place.country == country
    city = place.city if place and same_country else None
    lat: float | None
    lon: float | None
    if city:
        lat, lon = city.lat, city.lon
    elif country:
        lat, lon = g.countries[country].lat, g.countries[country].lon
    else:
        lat = lon = None
    return LocationResult(
        country_code=country,
        city=city.name if city else None,
        region=place.region if place and same_country else None,
        lat=lat,
        lon=lon,
        remote_status=status,
        remote_scope=scope,
        eligible_country_codes=eligible,
    )
