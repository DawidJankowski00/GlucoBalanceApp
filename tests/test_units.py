import pytest

from glucobalance.units import DisplayUnit, format_glucose, mgdl_to_mmoll, mmoll_to_mgdl


@pytest.mark.parametrize(("mgdl", "expected"), [(180.0, 10.0), (70.0, 3.9), (0.0, 0.0)])
def test_mgdl_to_mmoll(mgdl: float, expected: float) -> None:
    assert mgdl_to_mmoll(mgdl) == expected


@pytest.mark.parametrize(("mmoll", "expected"), [(10.0, 180), (3.9, 70), (5.5, 99), (0.0, 0)])
def test_mmoll_to_mgdl_rounds_to_whole_mgdl(mmoll: float, expected: int) -> None:
    assert mmoll_to_mgdl(mmoll) == expected


@pytest.mark.parametrize("mgdl", [40, 70, 99, 112, 180, 250, 400])
def test_round_trip_through_mmoll_stays_within_one_mgdl(mgdl: int) -> None:
    # mmol/L is shown with one decimal, so a round trip may drift by at most 1 mg/dL.
    assert abs(mmoll_to_mgdl(mgdl_to_mmoll(mgdl)) - mgdl) <= 1


@pytest.mark.parametrize(
    ("mgdl", "unit", "expected"),
    [
        (112, DisplayUnit.MGDL, "112 mg/dL"),
        (112, DisplayUnit.MMOLL, "6.2 mmol/L"),
        (180, DisplayUnit.MMOLL, "10.0 mmol/L"),
        (70, DisplayUnit.MMOLL, "3.9 mmol/L"),
    ],
)
def test_format_glucose(mgdl: int, unit: DisplayUnit, expected: str) -> None:
    assert format_glucose(mgdl, unit) == expected


def test_package_still_exports_mgdl_to_mmoll() -> None:
    from glucobalance import mgdl_to_mmoll as exported

    assert exported is mgdl_to_mmoll
