"""Food search for carb counting: Open Food Facts behind a small ``FoodSource`` interface.

Open Food Facts is a free, crowd-sourced food database. Its entries can be wrong or
incomplete, so a result only fills in the carbs field; the user still checks the number
before saving. The rest of the app depends on ``FoodSource`` only, so the database can be
swapped, and tests use a fake source and never touch the network.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from glucobalance.entries import EntryError

SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
# Open Food Facts asks every app to say who it is.
USER_AGENT = "GlucoBalanceApp/0.1 (https://github.com/DawidJankowski00/GlucoBalanceApp)"
REQUEST_TIMEOUT_SECONDS = 5.0
RESULT_COUNT = 10
MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 60
MIN_PORTION_GRAMS = Decimal(1)
MAX_PORTION_GRAMS = Decimal(2000)
UNAVAILABLE = "Food search is not available right now. Enter the carbs by hand."


class FoodSearchError(Exception):
    """The search could not be done. The message is safe to show to the user."""


@dataclass(frozen=True, slots=True)
class Food:
    code: str
    name: str
    brand: str | None
    carbs_per_100g: Decimal


class FoodSource(Protocol):
    def search(self, query: str) -> list[Food]: ...


def clean_query(raw: str) -> str:
    """Trim and collapse spaces; reject text that is too short or too long to search for."""
    query = re.sub(r"\s+", " ", raw).strip()
    if len(query) < MIN_QUERY_LENGTH:
        raise FoodSearchError(f"Type at least {MIN_QUERY_LENGTH} letters to search.")
    if len(query) > MAX_QUERY_LENGTH:
        raise FoodSearchError(f"Keep the search under {MAX_QUERY_LENGTH} characters.")
    return query


def _carbs(value: Any) -> Decimal | None:
    """Carbs per 100 g from the API (a number or a numeric string), or None if unusable."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        carbs = Decimal(str(value).strip())
    except InvalidOperation:
        return None
    return carbs if carbs.is_finite() and 0 <= carbs <= 100 else None


def _food(product: Any) -> Food | None:
    if not isinstance(product, dict):
        return None
    name = str(product.get("product_name") or "").strip()
    nutriments = product.get("nutriments")
    carbs = _carbs(nutriments.get("carbohydrates_100g")) if isinstance(nutriments, dict) else None
    if not name or carbs is None:
        return None
    brand = str(product.get("brands") or "").split(",")[0].strip() or None
    return Food(code=str(product.get("code") or ""), name=name, brand=brand, carbs_per_100g=carbs)


class OpenFoodFacts:
    """Searches world.openfoodfacts.org. ``transport`` lets tests answer instead of the web."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def search(self, query: str) -> list[Food]:
        params = {
            "search_terms": query,
            "search_simple": "1",
            "action": "process",
            "json": "1",
            "page_size": str(RESULT_COUNT),
            "fields": "code,product_name,brands,nutriments",
        }
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                response = client.get(SEARCH_URL, params=params)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError):
            raise FoodSearchError(UNAVAILABLE) from None
        if not isinstance(body, dict):
            raise FoodSearchError(UNAVAILABLE)
        products = body.get("products")
        if not isinstance(products, list):
            return []
        return [food for product in products if (food := _food(product)) is not None]


class CachedFoodSource:
    """Remembers recent answers so repeat searches are fast and go easy on the free service."""

    def __init__(
        self,
        source: FoodSource,
        *,
        ttl_seconds: float = 3600,
        max_entries: int = 200,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: dict[str, tuple[float, list[Food]]] = {}

    def search(self, query: str) -> list[Food]:
        key = clean_query(query).lower()
        now = self._clock()
        cached = self._entries.get(key)
        if cached is not None and now - cached[0] <= self._ttl:
            return cached[1]
        foods = self._source.search(key)  # failures raise here and are never stored
        self._entries.pop(key, None)
        self._entries[key] = (now, foods)
        while len(self._entries) > self._max_entries:
            del self._entries[next(iter(self._entries))]
        return foods


def carbs_for_portion(carbs_per_100g: Decimal, portion_grams: Decimal) -> Decimal:
    """Grams of carbohydrate in a portion, rounded to one decimal (half up)."""
    if not MIN_PORTION_GRAMS <= portion_grams <= MAX_PORTION_GRAMS:
        raise EntryError("The portion must be between 1 and 2000 g.")
    return (carbs_per_100g * portion_grams / 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
