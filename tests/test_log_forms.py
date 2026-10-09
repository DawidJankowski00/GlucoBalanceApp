"""Turning the glucose form (typed in the user's unit and local time) into an entry."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from glucobalance.glucose_service import GlucoseEntryError
from glucobalance.models import DisplayUnit, GlucoseTag
from glucobalance.web.log_forms import parse_glucose_form

WARSAW = ZoneInfo("Europe/Warsaw")


def form(**values: str) -> dict[str, str]:
    return {"value": "112", "measured_at": "2026-10-09T14:30", "tag": "", "note": "", **values}


def test_mg_dl_value_and_local_time_become_utc() -> None:
    entry = parse_glucose_form(form(), DisplayUnit.MGDL, WARSAW)
    assert entry.value_mgdl == 112
    # Warsaw is UTC+2 in October (summer time).
    assert entry.measured_at == datetime(2026, 10, 9, 12, 30, tzinfo=UTC)
    assert entry.tag is None
    assert entry.note is None


@pytest.mark.parametrize(("typed", "mgdl"), [("6.2", 112), ("6,2", 112), ("3.9", 70)])
def test_mmol_values_are_converted(typed: str, mgdl: int) -> None:
    entry = parse_glucose_form(form(value=typed), DisplayUnit.MMOLL, WARSAW)
    assert entry.value_mgdl == mgdl


def test_winter_time_uses_the_winter_offset() -> None:
    entry = parse_glucose_form(form(measured_at="2026-12-01T08:00"), DisplayUnit.MGDL, WARSAW)
    assert entry.measured_at == datetime(2026, 12, 1, 7, 0, tzinfo=UTC)


def test_tag_and_note_are_read() -> None:
    entry = parse_glucose_form(form(tag="after_meal", note=" pizza "), DisplayUnit.MGDL, WARSAW)
    assert entry.tag is GlucoseTag.AFTER_MEAL
    assert entry.note == "pizza"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"value": ""}, "Enter your glucose value"),
        ({"value": "abc"}, "Enter your glucose value"),
        ({"value": "nan"}, "Enter your glucose value"),
        ({"measured_at": ""}, "Enter the time"),
        ({"measured_at": "yesterday"}, "Enter the time"),
        ({"tag": "lunch"}, "Choose a tag"),
    ],
)
def test_bad_input_gives_a_readable_error(changes: dict[str, str], message: str) -> None:
    with pytest.raises(GlucoseEntryError, match=message):
        parse_glucose_form(form(**changes), DisplayUnit.MGDL, WARSAW)
