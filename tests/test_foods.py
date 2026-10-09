"""Open Food Facts search behind a ``FoodSource`` interface, with an in-memory cache."""

import json
from decimal import Decimal

import httpx
import pytest

from glucobalance.entries import EntryError
from glucobalance.foods import (
    CachedFoodSource,
    Food,
    FoodSearchError,
    OpenFoodFacts,
    carbs_for_portion,
    clean_query,
)

PRODUCTS = {
    "products": [
        {
            "code": "111",
            "product_name": "Rolled oats",
            "brands": "Tesco, Other",
            "nutriments": {"carbohydrates_100g": 60.5},
        },
        {"code": "222", "product_name": "", "nutriments": {"carbohydrates_100g": 10}},
        {"code": "333", "product_name": "No carbs listed", "nutriments": {}},
        {
            "code": "444",
            "product_name": "  Strawberry jam ",
            "nutriments": {"carbohydrates_100g": "62.25"},
        },
        {"code": "555", "product_name": "Impossible", "nutriments": {"carbohydrates_100g": 140}},
        {"code": "666", "product_name": "Negative", "nutriments": {"carbohydrates_100g": -1}},
        {"code": "777", "product_name": "Text carbs", "nutriments": {"carbohydrates_100g": "lots"}},
    ]
}


def source(handler: httpx.MockTransport | None = None, **json_body: object) -> OpenFoodFacts:
    body = json_body or PRODUCTS
    transport = handler or httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    return OpenFoodFacts(transport=transport)


# ---------- the Open Food Facts client ----------


def test_products_with_a_name_and_plausible_carbs_are_returned() -> None:
    foods = source().search("oats")
    assert foods == [
        Food(code="111", name="Rolled oats", brand="Tesco", carbs_per_100g=Decimal("60.5")),
        Food(code="444", name="Strawberry jam", brand=None, carbs_per_100g=Decimal("62.25")),
    ]


def test_the_request_asks_for_json_with_a_small_page_and_a_polite_user_agent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=PRODUCTS)

    source(httpx.MockTransport(handler)).search("rolled oats")
    (request,) = seen
    assert request.url.host == "world.openfoodfacts.org"
    params = request.url.params
    assert params["search_terms"] == "rolled oats"
    assert params["json"] == "1"
    assert params["page_size"] == "10"
    assert {"code", "product_name", "brands", "nutriments"} <= set(params["fields"].split(","))
    assert request.headers["user-agent"].startswith("GlucoBalanceApp/")


def test_a_response_without_products_is_an_empty_result() -> None:
    assert source(products=[]).search("zzz") == []
    assert source(count=0).search("zzz") == []


@pytest.mark.parametrize("status", [429, 500, 503])
def test_http_errors_become_a_readable_error(status: int) -> None:
    client = OpenFoodFacts(transport=httpx.MockTransport(lambda r: httpx.Response(status)))
    with pytest.raises(FoodSearchError, match="not available"):
        client.search("oats")


def test_timeouts_become_a_readable_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(FoodSearchError, match="not available"):
        OpenFoodFacts(transport=httpx.MockTransport(handler)).search("oats")


def test_a_broken_response_becomes_a_readable_error() -> None:
    client = OpenFoodFacts(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>oops"))
    )
    with pytest.raises(FoodSearchError, match="not available"):
        client.search("oats")
    client = OpenFoodFacts(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=json.dumps([1, 2])))
    )
    with pytest.raises(FoodSearchError, match="not available"):
        client.search("oats")


# ---------- the search text ----------


def test_the_query_is_trimmed_and_spaces_collapsed() -> None:
    assert clean_query("  rolled    oats ") == "rolled oats"


@pytest.mark.parametrize("raw", ["", " ", "a", " a "])
def test_short_queries_are_rejected(raw: str) -> None:
    with pytest.raises(FoodSearchError, match="at least 2 letters"):
        clean_query(raw)


def test_long_queries_are_rejected() -> None:
    with pytest.raises(FoodSearchError, match="under 60 characters"):
        clean_query("x" * 61)


# ---------- the cache ----------


class CountingSource:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str) -> list[Food]:
        self.calls.append(query)
        return [Food("1", query.title(), None, Decimal(10))]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_repeat_searches_are_served_from_the_cache() -> None:
    inner = CountingSource()
    cached = CachedFoodSource(inner, ttl_seconds=3600, clock=Clock())
    first = cached.search("Oats")
    assert cached.search("  oats ") == first
    assert inner.calls == ["oats"]


def test_cache_entries_expire() -> None:
    inner, clock = CountingSource(), Clock()
    cached = CachedFoodSource(inner, ttl_seconds=3600, clock=clock)
    cached.search("oats")
    clock.now += 3599
    cached.search("oats")
    assert inner.calls == ["oats"]
    clock.now += 2
    cached.search("oats")
    assert inner.calls == ["oats", "oats"]


def test_failed_searches_are_not_cached() -> None:
    class Flaky:
        calls = 0

        def search(self, query: str) -> list[Food]:
            self.calls += 1
            if self.calls == 1:
                raise FoodSearchError("Food search is not available right now.")
            return []

    flaky = Flaky()
    cached = CachedFoodSource(flaky, ttl_seconds=3600, clock=Clock())
    with pytest.raises(FoodSearchError):
        cached.search("oats")
    assert cached.search("oats") == []
    assert flaky.calls == 2


def test_the_cache_keeps_at_most_max_entries_dropping_the_oldest() -> None:
    inner = CountingSource()
    cached = CachedFoodSource(inner, ttl_seconds=3600, clock=Clock(), max_entries=2)
    for query in ("aa", "bb", "cc"):
        cached.search(query)
    cached.search("cc")
    cached.search("bb")
    assert inner.calls == ["aa", "bb", "cc"]
    cached.search("aa")
    assert inner.calls == ["aa", "bb", "cc", "aa"]


def test_short_queries_are_rejected_before_the_cache_or_the_network() -> None:
    inner = CountingSource()
    with pytest.raises(FoodSearchError):
        CachedFoodSource(inner, ttl_seconds=3600, clock=Clock()).search("a")
    assert inner.calls == []


# ---------- carbs for a portion ----------


@pytest.mark.parametrize(
    ("per_100g", "portion", "grams"),
    [
        ("60.5", "50", "30.3"),  # 30.25 rounds half up
        ("100", "35", "35.0"),
        ("0", "200", "0.0"),
        ("12.34", "100", "12.3"),
        ("62.25", "10", "6.2"),
    ],
)
def test_carbs_scale_with_the_portion(per_100g: str, portion: str, grams: str) -> None:
    assert carbs_for_portion(Decimal(per_100g), Decimal(portion)) == Decimal(grams)


@pytest.mark.parametrize("portion", ["0", "-5", "2001"])
def test_portion_must_be_between_1_and_2000_grams(portion: str) -> None:
    with pytest.raises(EntryError, match="between 1 and 2000 g"):
        carbs_for_portion(Decimal(10), Decimal(portion))
