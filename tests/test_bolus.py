"""Tests for the bolus calculator: carbs / ICR + (glucose - target) / ISF - IOB, then rounded."""

from decimal import Decimal

import pytest

from glucobalance.bolus import BolusResult, calculate_bolus

D = Decimal


def calc(
    *,
    carbs: str = "0",
    glucose: int = 100,
    target: int = 100,
    icr: str = "10",
    isf: int = 50,
    iob: str = "0",
    step: str = "0.5",
    max_bolus: str = "15",
) -> BolusResult:
    return calculate_bolus(
        carbs_g=D(carbs),
        glucose_mgdl=glucose,
        target_mgdl=target,
        icr=D(icr),
        isf_mgdl=isf,
        iob_units=D(iob),
        step=D(step),
        max_bolus=D(max_bolus),
    )


def test_meal_only() -> None:
    result = calc(carbs="60", icr="10")
    assert result.meal_units == D("6")
    assert result.correction_units == D("0")
    assert result.units == D("6")


def test_correction_only() -> None:
    result = calc(glucose=200, target=100, isf=50)
    assert result.correction_units == D("2")
    assert result.units == D("2")


def test_meal_plus_correction() -> None:
    assert calc(carbs="30", icr="10", glucose=200, target=100, isf=50).units == D("5")


def test_iob_is_subtracted() -> None:
    result = calc(carbs="30", icr="10", glucose=200, target=100, isf=50, iob="1.5")
    assert result.iob_units == D("1.5")
    assert result.units == D("3.5")


def test_no_negative_correction_below_target() -> None:
    result = calc(carbs="30", icr="10", glucose=60, target=100, isf=50)
    assert result.correction_units == D("0")
    assert result.units == D("3")


def test_iob_larger_than_the_need_gives_zero_never_negative() -> None:
    assert calc(carbs="10", icr="10", iob="5").units == D("0")


@pytest.mark.parametrize(
    ("carbs", "expected"),
    [("24", "2.5"), ("26", "2.5"), ("28", "3"), ("22", "2")],  # 2.4, 2.6, 2.8, 2.2 at ICR 10
)
def test_rounds_to_the_nearest_step(carbs: str, expected: str) -> None:
    assert calc(carbs=carbs, icr="10", step="0.5").units == D(expected)


def test_pen_step_of_one_unit() -> None:
    assert calc(carbs="26", icr="10", step="1").units == D("3")


def test_pump_step_of_a_tenth() -> None:
    assert calc(carbs="26", icr="10", step="0.1").units == D("2.6")


def test_the_max_bolus_caps_the_dose_and_says_so() -> None:
    result = calc(carbs="200", icr="10", max_bolus="10")
    assert result.units == D("10")
    assert result.capped is True


def test_not_capped_when_under_the_max() -> None:
    assert calc(carbs="30", icr="10", max_bolus="10").capped is False


def test_a_dose_that_rounds_up_past_the_max_is_held_at_the_max() -> None:
    result = calc(carbs="104", icr="10", step="1", max_bolus="10")  # 10.4 rounds to 10
    assert result.units == D("10")


@pytest.mark.parametrize("icr", ["0", "-5"])
def test_rejects_a_non_positive_icr(icr: str) -> None:
    with pytest.raises(ValueError, match="ICR"):
        calc(carbs="30", icr=icr)


def test_rejects_a_non_positive_isf() -> None:
    with pytest.raises(ValueError, match="ISF"):
        calc(isf=0)


def test_rejects_negative_carbs() -> None:
    with pytest.raises(ValueError, match="carbs"):
        calc(carbs="-1")
