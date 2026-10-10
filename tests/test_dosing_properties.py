"""Property-based tests for the dosing core.

Hypothesis tries many random inputs and checks rules that must hold for every one of them:
no negative doses, every dose a whole number of steps, the max bolus always holds, IOB never
exceeds what was taken, and no suggestion moves a setting by more than the cap.
"""

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from hypothesis import given
from hypothesis import strategies as st

from glucobalance.adjustments import MAX_CHANGE, suggest_adjustments
from glucobalance.bolus import BolusResult, calculate_bolus
from glucobalance.iob import insulin_on_board
from glucobalance.models import DoseKind, InsulinDose, InsulinType
from glucobalance.patterns import Evidence, Finding, PatternKind
from glucobalance.settings_service import ALLOWED_DOSE_STEPS, TimeBlockInput

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def decimals(low: str, high: str, places: int) -> st.SearchStrategy[Decimal]:
    return st.decimals(Decimal(low), Decimal(high), places=places)


@dataclass(frozen=True)
class Case:
    carbs_g: Decimal
    glucose_mgdl: int
    target_mgdl: int
    icr: Decimal
    isf_mgdl: int
    iob_units: Decimal
    step: Decimal
    max_bolus: Decimal


cases = st.builds(
    Case,
    decimals("0", "300", 0),
    st.integers(70, 600),
    st.integers(62, 195),
    decimals("1", "150", 1),
    st.integers(5, 400),
    decimals("0", "30", 2),
    st.sampled_from(ALLOWED_DOSE_STEPS),
    decimals("0.05", "50", 2),
)


def calc(case: Case) -> BolusResult:
    return calculate_bolus(**asdict(case))


@given(cases)
def test_a_bolus_is_never_negative_and_never_above_the_max(case: Case) -> None:
    assert Decimal(0) <= calc(case).units <= case.max_bolus


@given(cases)
def test_a_bolus_is_a_whole_number_of_steps(case: Case) -> None:
    assert calc(case).units % case.step == 0


@given(cases)
def test_rounding_moves_a_dose_by_at_most_half_a_step(case: Case) -> None:
    result = calc(case)
    if result.capped:
        return
    exact = max(Decimal(0), result.meal_units + result.correction_units - result.iob_units)
    assert abs(result.units - exact) <= case.step / 2


@given(cases, decimals("0", "10", 2))
def test_more_insulin_on_board_never_raises_the_dose(case: Case, extra: Decimal) -> None:
    more = replace(case, iob_units=case.iob_units + extra)
    assert calc(more).units <= calc(case).units


doses = st.lists(
    st.builds(
        lambda minutes, units, rapid, kind: InsulinDose(
            user_id=1,
            taken_at=NOW - timedelta(minutes=minutes),
            units=units,
            insulin_type=InsulinType.RAPID if rapid else InsulinType.LONG,
            kind=kind,
        ),
        st.integers(-120, 600),
        decimals("0.05", "30", 2),
        st.booleans(),
        st.sampled_from(DoseKind),
    ),
    max_size=10,
)


@given(doses, st.integers(120, 480))
def test_iob_is_between_zero_and_the_rapid_insulin_taken(
    taken: list[InsulinDose], action: int
) -> None:
    iob = insulin_on_board(taken, NOW, action)
    rapid = sum(
        (d.units for d in taken if d.insulin_type is InsulinType.RAPID and d.taken_at <= NOW),
        Decimal(0),
    )
    assert Decimal(0) <= iob <= rapid


blocks = st.lists(
    st.builds(
        TimeBlockInput,
        st.sampled_from([time(h) for h in range(0, 24, 3)]),
        decimals("1", "150", 1),
        st.integers(5, 400),
    ),
    min_size=1,
    max_size=6,
    unique_by=lambda b: b.start_time,
).map(
    lambda bs: [
        TimeBlockInput(time(0), bs[0].icr_grams_per_unit, bs[0].isf_mgdl),
        *(b for b in bs[1:] if b.start_time != time(0)),
    ]
)

findings = st.lists(st.sampled_from(PatternKind), unique=True).map(
    lambda kinds: [
        Finding(k, "t", "d", 100.0, (Evidence(NOW.replace(hour=9), 250),)) for k in kinds
    ]
)


@given(findings, blocks)
def test_suggestions_stay_within_the_cap(found: list[Finding], bs: list[TimeBlockInput]) -> None:
    for s in suggest_adjustments(found, bs, [], now=NOW, zone=ZoneInfo("UTC")):
        assert s.proposed != s.current
        assert abs(s.proposed - s.current) <= s.current * MAX_CHANGE


@given(findings, blocks)
def test_at_most_one_suggestion_per_block_setting(
    found: list[Finding], bs: list[TimeBlockInput]
) -> None:
    suggestions = suggest_adjustments(found, bs, [], now=NOW, zone=ZoneInfo("UTC"))
    keys = [(s.block_start, s.setting) for s in suggestions]
    assert len(keys) == len(set(keys))
