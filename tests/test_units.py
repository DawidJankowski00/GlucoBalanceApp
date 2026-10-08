import pytest

from glucobalance import mgdl_to_mmoll


@pytest.mark.parametrize(("mgdl", "expected"), [(180.0, 10.0), (70.0, 3.9), (0.0, 0.0)])
def test_mgdl_to_mmoll(mgdl: float, expected: float) -> None:
    assert mgdl_to_mmoll(mgdl) == expected
