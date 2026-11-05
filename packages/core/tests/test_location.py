"""Location rules that are easy to get wrong, one case each."""

import pytest

from erio_core.normalize.location import resolve_location


@pytest.mark.parametrize(
    ("text", "country", "city", "region"),
    [
        ("Paris", "FR", "Paris", "Ile-de-France"),
        ("Paris, TX", "US", "Paris", "Texas"),
        ("London, ON", "CA", "London", "Ontario"),
        ("Cambridge, MA", "US", "Cambridge", "Massachusetts"),
        ("Cambridge, United Kingdom", "GB", "Cambridge", "England"),
        ("Victoria, Australia", "AU", None, "Victoria"),
        ("Melbourne, VIC", "AU", "Melbourne", "Victoria"),
        ("Hyderabad, Pakistan", "PK", "Hyderabad", "Sindh"),
        ("Lagos, Nigeria", "NG", "Lagos", "Lagos"),
        ("Nigeria, Lagos", "NG", "Lagos", "Lagos"),
        ("Kwara, Nigeria", "NG", None, "Kwara State"),
        ("Mexico City", "MX", "Mexico City", "Mexico City"),
        ("Bengaluru/Bangalore", "IN", "Bengaluru", "Karnataka"),
        ("Tel Aviv-Yafo, Israel", "IL", "Tel Aviv", "Tel Aviv"),
        ("Winston-Salem, NC", "US", "Winston-Salem", "North Carolina"),
        ("New York, New York, USA", "US", "New York City", "New York"),
        ("San Francisco Bay Area", "US", "San Francisco", "California"),
        ("Toronto Canada", "CA", "Toronto", "Ontario"),
    ],
)
def test_resolves_place(text: str, country: str, city: str | None, region: str | None) -> None:
    result = resolve_location(text)
    assert (result.country_code, result.city, result.region) == (country, city, region)
    assert result.lat is not None and result.lon is not None


@pytest.mark.parametrize(
    ("text", "scope", "eligible"),
    [
        ("Remote - USA", "country", ["US"]),
        ("Remote in the US", "country", ["US"]),
        ("Remote within Nigeria", "country", ["NG"]),
        ("Georgia, USA, Remote", "country", ["US"]),
        ("Remote, Canada; Remote, United States", "region", ["CA", "US"]),
        ("Remote", "worldwide", []),
        ("Global", "worldwide", []),
        ("Anywhere in the world", "worldwide", []),
    ],
)
def test_remote_scope(text: str, scope: str, eligible: list[str]) -> None:
    result = resolve_location(text)
    assert result.remote_status == "remote"
    assert (result.remote_scope, result.eligible_country_codes) == (scope, eligible)


def test_region_phrase_expands_to_its_countries() -> None:
    result = resolve_location("Remote - EMEA")
    assert result.remote_scope == "region"
    assert {"NG", "DE", "AE", "GB"} <= set(result.eligible_country_codes)
    assert "US" not in result.eligible_country_codes


def test_several_countries_on_site_are_all_filterable() -> None:
    result = resolve_location("London or Berlin")
    assert result.remote_status == "onsite"
    assert result.country_code == "GB"
    assert result.eligible_country_codes == ["GB", "DE"]


def test_office_hints_fill_in_when_the_text_names_no_place() -> None:
    result = resolve_location("Hybrid", city_hint="London", country_hint="United Kingdom")
    assert (result.country_code, result.city, result.remote_status) == ("GB", "London", "hybrid")


def test_unresolvable_text_goes_to_review() -> None:
    result = resolve_location("N/A")
    assert not result.resolved
    assert result.country_code is None and result.eligible_country_codes == []
