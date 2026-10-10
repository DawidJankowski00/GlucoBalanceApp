"""The output check: every dose or setting number in a reply must come from a tool result."""

from decimal import Decimal

import pytest

from glucobalance.output_check import check_reply, dose_numbers, numbers_in


def test_numbers_are_collected_from_nested_tool_results() -> None:
    data = {"units": "4.50", "parts": [{"meal": 6, "note": "after 15 minutes"}], "ok": True}
    assert numbers_in(data) == {Decimal("4.5"), Decimal(6), Decimal(15)}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Take 4 units now.", [Decimal(4)]),
        ("Take 4.5 U with the meal.", [Decimal("4.5")]),
        ("A bolus of 3.5 is suggested.", [Decimal("3.5")]),
        ("Inject 2U.", [Decimal(2)]),
        ("Your ICR is 10 g per unit.", [Decimal(10)]),
        ("Your ISF is 40 mg/dL per unit.", [Decimal(40)]),
        ("Your ISF is 40 mg/dL.", [Decimal(40)]),
        ("Your carb ratio is 1:12.", [Decimal(12)]),
        ("1 unit per 12 g of carbs.", [Decimal(1), Decimal(12)]),
        ("Take four units.", [Decimal(4)]),
        ("Take twelve units.", [Decimal(12)]),
        ("Your sensitivity factor of 45 should drop.", [Decimal(45)]),
        ("ISF from 00:00: 40 mg/dL per unit.", [Decimal(40)]),
        ("The ISF is 40.", [Decimal(40)]),
    ],
)
def test_dose_numbers_are_found(text: str, expected: list[Decimal]) -> None:
    assert [value for value, _ in dose_numbers(text)] == expected


@pytest.mark.parametrize(
    "text",
    [
        "Your glucose is 120 mg/dL.",
        "You had 60 g of carbs at 12:30.",
        "Insulin acts for about 4 hours.",
        "The correction was made 20 minutes ago.",
        "Your time in range is 70%.",
        "The bolus calculator uses 60 g of carbs.",
        "Check again in 15 minutes.",
        "Unit tests are great.",
        "Your ISF from 00:00 is shown on the settings page.",
        "Take your bolus at 13:00.",
        "Lunch at 1:30 pm.",
    ],
)
def test_other_numbers_are_not_dose_numbers(text: str) -> None:
    assert dose_numbers(text) == []


def test_a_reply_with_only_verified_numbers_passes() -> None:
    allowed = {Decimal("4.5"), Decimal(10)}
    result = check_reply("The calculator says 4.5 units. Your ICR is 10 g per unit.", allowed)
    assert result.ok
    assert result.unverified == ()


def test_a_decimal_matches_regardless_of_trailing_zeros() -> None:
    assert check_reply("Take 4.0 units.", {Decimal("4.00")}).ok


def test_an_invented_dose_is_caught() -> None:
    result = check_reply("Take 6 units for the pizza.", {Decimal("4.5")})
    assert not result.ok
    assert result.unverified == ("6",)


def test_a_dose_with_no_tool_results_is_caught() -> None:
    assert not check_reply("I'd say 3 units.", set()).ok


def test_a_reply_without_dose_numbers_passes_with_no_tool_results() -> None:
    assert check_reply("I can't give a dose. Please ask your care team.", set()).ok
