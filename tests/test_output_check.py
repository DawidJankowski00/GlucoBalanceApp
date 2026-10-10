"""The output check: every dose or setting number in a reply must come from a tool result,
and from a value of the same kind (units, carb ratio or sensitivity)."""

from decimal import Decimal

import pytest

from glucobalance.output_check import Kind, allowed_numbers, check_reply, dose_numbers

U, ICR, ISF = Kind.UNITS, Kind.ICR, Kind.ISF


def test_allowed_numbers_are_read_by_field_name() -> None:
    data = {
        "units": "4.50",
        "meal_units": 6,
        "carbs_g": 12,
        "glucose": 130,
        "note": "after 15 minutes",
        "blocks": [{"icr_grams_per_unit": 10, "isf_per_unit": 2.5, "isf_mgdl_per_unit": 45}],
        "ok": True,
    }
    assert allowed_numbers(data) == {
        U: {Decimal("4.5"), Decimal(6)},
        ICR: {Decimal(10)},
        ISF: {Decimal("2.5"), Decimal(45)},
    }


def test_a_suggestion_counts_as_its_setting() -> None:
    data = {"suggestions": [{"setting": "isf", "current": 45, "proposed": 49, "id": 3}]}
    assert allowed_numbers(data)[ISF] == {Decimal(45), Decimal(49)}
    assert allowed_numbers(data)[U] == set()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Take 4 units now.", [(4, U)]),
        ("Take 4.5 U with the meal.", [(4.5, U)]),
        ("A bolus of 3.5 is suggested.", [(3.5, U)]),
        ("Inject 2U.", [(2, U)]),
        ("Your ICR is 10 g per unit.", [(10, ICR)]),
        ("Your ISF is 40 mg/dL per unit.", [(40, ISF)]),
        ("Your ISF is 40 mg/dL.", [(40, ISF)]),
        ("Your carb ratio is 1:12.", [(12, ICR)]),
        ("1 unit per 12 g of carbs.", [(12, ICR)]),
        ("Take four units.", [(4, U)]),
        ("Take twelve units.", [(12, U)]),
        ("Your sensitivity factor of 45 should drop.", [(45, ISF)]),
        ("ISF from 00:00: 40 mg/dL per unit.", [(40, ISF)]),
        ("The ISF is 40.", [(40, ISF)]),
        ("Sensitivity 2.5 mmol/L per unit.", [(2.5, ISF)]),
    ],
)
def test_dose_numbers_are_found(text: str, expected: list[tuple[float, Kind]]) -> None:
    found = [(value, kind) for value, _, kind in dose_numbers(text)]
    assert found == [(Decimal(str(value)), kind) for value, kind in expected]


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
    allowed = {U: {Decimal("4.5")}, ICR: {Decimal(10)}}
    result = check_reply("The calculator says 4.5 units. Your ICR is 10 g per unit.", allowed)
    assert result.ok
    assert result.unverified == ()


def test_a_decimal_matches_regardless_of_trailing_zeros() -> None:
    assert check_reply("Take 4.0 units.", {U: {Decimal("4.00")}}).ok


def test_an_invented_dose_is_caught() -> None:
    result = check_reply("Take 6 units for the pizza.", {U: {Decimal("4.5")}})
    assert not result.ok
    assert result.unverified == ("6",)


def test_a_number_of_another_kind_does_not_verify_a_dose() -> None:
    """Found by the Ollama eval: the model passed "12 units" off as 12 g of carbs, then quoted
    "12 units". The 12 is a carb amount, so it cannot verify a dose."""
    allowed = allowed_numbers({"carbs_g": 12, "units": 1, "glucose": 130})
    assert not check_reply("The calculator suggests 12 units.", allowed).ok
    assert not check_reply("Take 130 units.", allowed).ok
    assert check_reply("The calculator suggests 1 unit.", allowed).ok


def test_a_ratio_cannot_be_verified_by_a_dose() -> None:
    assert not check_reply("Your ICR is 4 g per unit.", {U: {Decimal(4)}}).ok


def test_a_dose_with_no_tool_results_is_caught() -> None:
    assert not check_reply("I'd say 3 units.", {}).ok


def test_a_reply_without_dose_numbers_passes_with_no_tool_results() -> None:
    assert check_reply("I can't give a dose. Please ask your care team.", {}).ok
