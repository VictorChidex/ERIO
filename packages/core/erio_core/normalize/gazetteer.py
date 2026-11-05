"""Offline place lookups: countries, regions, states and cities.

Countries come from erio_core/data/countries.json (the 233 the globe draws);
cities and states from the GeoNames gazetteer (gazetteer.json.gz, CC BY 4.0).
No paid geocoding API is used (spec section 6).
"""

import gzip
import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Any

from erio_core.db.seed import load_countries


def fold(text: str) -> str:
    """Lowercase, strip accents and punctuation noise for matching."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[.\N{RIGHT SINGLE QUOTATION MARK}']", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True)
class City:
    name: str
    country: str
    admin1: str
    lat: float
    lon: float
    population: int


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    lat: float
    lon: float
    region_groups: tuple[str, ...]


# Names job ads use for countries that differ from the globe's names.
COUNTRY_ALIASES = {
    "usa": "US", "us": "US", "united states of america": "US", "u s": "US",
    "uk": "GB", "united kingdom of great britain and northern ireland": "GB",
    "great britain": "GB", "britain": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "northern ireland": "GB",
    "uae": "AE", "emirates": "AE", "ksa": "SA", "saudi": "SA",
    "holland": "NL", "the netherlands": "NL", "czech republic": "CZ",
    "korea": "KR", "republic of korea": "KR", "viet nam": "VN", "russian federation": "RU",
    "turkiye": "TR", "ivory coast": "CI", "cote divoire": "CI", "drc": "CD",
    "hong kong sar": "HK", "macau": "MO", "cape verde": "CV", "vatican city": "VA",
    "deutschland": "DE", "brasil": "BR", "espana": "ES", "schweiz": "CH",
    "the philippines": "PH", "phillipines": "PH", "the bahamas": "BS",
    "republic of ireland": "IE", "mainland china": "CN", "prc": "CN",
}  # fmt: skip

# Two-letter codes accepted as countries when they stand alone in a location.
# Words such as "IN" or "IT" are only read as codes when written in capitals.
COUNTRY_CODES_AS_WORDS = {
    "US", "UK", "GB", "CA", "MX", "BR", "AR", "CO", "CL", "PE", "DE", "FR", "ES", "IT", "NL",
    "BE", "IE", "PT", "PL", "SE", "DK", "NO", "FI", "CH", "AT", "CZ", "RO", "GR", "IL", "AE",
    "SA", "EG", "NG", "KE", "GH", "ZA", "MA", "IN", "PK", "BD", "SG", "MY", "ID", "PH", "TH",
    "VN", "JP", "KR", "CN", "HK", "TW", "AU", "NZ", "TR", "UA",
}  # fmt: skip

CITY_ALIASES = {
    "nyc": ("New York City", "US"), "new york": ("New York City", "US"),
    "sf": ("San Francisco", "US"), "bay area": ("San Francisco", "US"),
    "sf bay area": ("San Francisco", "US"), "silicon valley": ("San Jose", "US"),
    "la": ("Los Angeles", "US"), "dc": ("Washington", "US"),
    "washington dc": ("Washington", "US"), "washington d c": ("Washington", "US"),
    "washington dc metro area": ("Washington", "US"), "greater london": ("London", "GB"),
    "cdmx": ("Mexico City", "MX"), "ciudad de mexico": ("Mexico City", "MX"),
    "gurgaon": ("Gurugram", "IN"), "bombay": ("Mumbai", "IN"), "sao paulo": ("São Paulo", "BR"),
    "tel aviv": ("Tel Aviv", "IL"), "tel aviv-yafo": ("Tel Aviv", "IL"),
    "kyiv": ("Kyiv", "UA"), "kiev": ("Kyiv", "UA"), "the hague": ("The Hague", "NL"),
    "san francisco bay area": ("San Francisco", "US"),
}  # fmt: skip

# States and provinces looked up by name, for the countries where job ads
# commonly name them instead of a city.
ADMIN1_COUNTRIES = {"US", "CA", "AU", "IN", "BR", "MX", "NG", "DE", "ZA", "KE"}

# Canadian postal abbreviations to GeoNames admin1 codes (US codes are the
# postal codes already).
CA_POSTAL = {
    "AB": "01", "BC": "02", "MB": "03", "NB": "04", "NL": "05", "NS": "07", "ON": "08",
    "PE": "09", "QC": "10", "SK": "11", "YT": "12", "NT": "13", "NU": "14",
}  # fmt: skip
AU_POSTAL = {
    "ACT": "01", "NSW": "02", "NT": "03", "QLD": "04", "SA": "05", "TAS": "06", "VIC": "07",
    "WA": "08",
}  # fmt: skip
POSTAL = {"CA": CA_POSTAL, "AU": AU_POSTAL}


class Gazetteer:
    def __init__(self, raw: dict[str, Any]):
        self.countries: dict[str, Country] = {}
        self.country_names: dict[str, str] = {}
        for row in load_countries():
            country = Country(
                row["code"], row["name"], row["lat"], row["lon"], tuple(row["region_groups"])
            )
            self.countries[country.code] = country
            self.country_names[fold(country.name)] = country.code
        for alias, code in COUNTRY_ALIASES.items():
            self.country_names.setdefault(alias, code)

        self.admin1_labels: dict[str, str] = raw["admin1"]
        self.admin1_names: dict[str, list[tuple[str, str]]] = {}
        for key, name in self.admin1_labels.items():
            country, code = key.split(".", 1)
            if country in ADMIN1_COUNTRIES:
                # "Kwara State" is written "Kwara" as often as not.
                folded = fold(name)
                short = re.sub(r" (state|province|region|territory)$", "", folded)
                for key in {folded, short}:
                    self.admin1_names.setdefault(key, []).append((country, code))
        # State and province codes as written in job ads, to their names.
        self.us_states = {
            key.split(".", 1)[1]: name
            for key, name in self.admin1_labels.items()
            if key.startswith("US.")
        }
        # State codes as written after a city ("Austin, TX", "Toronto, ON", "Perth, WA").
        self.state_codes: dict[str, dict[str, str]] = {
            "US": self.us_states,
            **{
                country: {
                    written: self.admin1_labels[f"{country}.{code}"]
                    for written, code in codes.items()
                }
                for country, codes in POSTAL.items()
            },
        }

        self.cities: dict[str, list[City]] = {}
        for name, others, country, admin1, lat, lon, population in raw["cities"]:
            city = City(name, country, admin1, lat, lon, population)
            for key in {fold(name), *(fold(other) for other in others)}:
                self.cities.setdefault(key, []).append(city)

    def country(self, text: str) -> str | None:
        stripped = text.strip()
        if stripped in COUNTRY_CODES_AS_WORDS:
            return "GB" if stripped == "UK" else stripped
        return self.country_names.get(fold(stripped))

    def city(self, text: str, country: str | None = None) -> City | None:
        key = fold(text)
        if key in CITY_ALIASES:
            name, alias_country = CITY_ALIASES[key]
            if country in (None, alias_country):
                key, country = fold(name), alias_country
        candidates = self.cities.get(key, [])
        if country:
            candidates = [c for c in candidates if c.country == country]
        # Most populous first: "Paris" is Paris, France unless told otherwise.
        return candidates[0] if candidates else None

    def region_name(self, city: City) -> str | None:
        return self.admin1_labels.get(f"{city.country}.{city.admin1}")

    def region_label(self, country: str, admin1: str) -> str | None:
        return self.admin1_labels.get(f"{country}.{admin1}")

    def admin1(self, text: str, country: str | None = None) -> tuple[str, str] | None:
        """(country, admin1 code) for a state or province name."""
        for candidate in self.admin1_names.get(fold(text), []):
            if country in (None, candidate[0]):
                return candidate
        return None

    def admin1_code(self, country: str, written: str) -> str:
        """GeoNames admin1 code for a state code as written ("ON" -> "08")."""
        return POSTAL.get(country, {}).get(written, written)


@lru_cache
def gazetteer() -> Gazetteer:
    raw = files("erio_core").joinpath("data/gazetteer.json.gz").read_bytes()
    return Gazetteer(json.loads(gzip.decompress(raw)))
