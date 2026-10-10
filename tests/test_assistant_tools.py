"""The assistant's tools: thin, read-only wrappers around tested code (plus saving suggestions)."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.assistant_tools import TOOLS, Toolbox, ToolError
from glucobalance.models import DisplayUnit, SuggestionStatus, User
from glucobalance.weekly_review import pending
from test_adjustment_service import add_night_lows, backdate
from test_dosing_service import NOW, add_reading, user  # noqa: F401  (fixture)


@pytest.fixture
def tools(session: Session, user: User) -> Toolbox:  # noqa: F811
    return Toolbox(session, user, NOW)


def test_there_are_exactly_the_five_planned_tools() -> None:
    assert [t.name for t in TOOLS] == [
        "get_recent_glucose",
        "get_patterns",
        "get_settings",
        "calculate_bolus",
        "propose_adjustment",
    ]
    for tool in TOOLS:
        assert tool.parameters["type"] == "object"


def test_unknown_tools_are_an_error(tools: Toolbox) -> None:
    with pytest.raises(ToolError, match="no tool"):
        tools.run("set_basal", {})


def test_recent_glucose_without_readings(tools: Toolbox) -> None:
    result = tools.run("get_recent_glucose", {})
    assert result["latest"] is None


def test_recent_glucose_lists_the_window_newest_first(
    session: Session,
    user: User,  # noqa: F811
    tools: Toolbox,
) -> None:
    for minutes, value in ((5, 140), (65, 120), (300, 200)):
        add_reading(session, user, value, minutes_ago=minutes)
    result = tools.run("get_recent_glucose", {"hours": 2})
    assert result["latest"]["value"] == 140
    assert result["latest"]["minutes_ago"] == 5
    assert [r["value"] for r in result["readings"]] == [140, 120]
    assert result["latest"]["at"] == "Fri 09 Oct 13:55"  # Warsaw time


def test_recent_glucose_in_mmol(session: Session, user: User, tools: Toolbox) -> None:  # noqa: F811
    assert user.settings is not None
    user.settings.display_unit = DisplayUnit.MMOLL
    add_reading(session, user, 180)
    result = tools.run("get_recent_glucose", {})
    assert result["unit"] == "mmol/L"
    assert result["latest"]["value"] == 10.0
    assert result["latest"]["value_mgdl"] == 180


@pytest.mark.parametrize("hours", [0, 25, "lots", True])
def test_recent_glucose_rejects_bad_hours(tools: Toolbox, hours: object) -> None:
    with pytest.raises(ToolError):
        tools.run("get_recent_glucose", {"hours": hours})


def test_settings_lists_every_block(tools: Toolbox) -> None:
    result = tools.run("get_settings", {})
    assert result["max_bolus_units"] == 10
    assert result["dose_step_units"] == 0.5
    assert result["time_blocks"] == [
        {"from": "00:00", "icr_grams_per_unit": 10, "isf_per_unit": 40, "isf_mgdl_per_unit": 40},
        {"from": "13:00", "icr_grams_per_unit": 15, "isf_per_unit": 50, "isf_mgdl_per_unit": 50},
    ]


def test_bolus_comes_from_the_calculator(session: Session, user: User, tools: Toolbox) -> None:  # noqa: F811
    add_reading(session, user, 125)
    result = tools.run("calculate_bolus", {"carbs_g": 45})
    assert result["status"] == "ok"
    assert result["units"] == 3
    assert result["meal_units"] == 3
    assert result["icr_grams_per_unit"] == 15


def test_bolus_refusal_has_no_number(session: Session, user: User, tools: Toolbox) -> None:  # noqa: F811
    add_reading(session, user, 60)
    result = tools.run("calculate_bolus", {"carbs_g": 45})
    assert result["status"] == "refused"
    assert result["reason"] == "low_glucose"
    assert "units" not in result


@pytest.mark.parametrize("carbs", [None, -5, 301, "pizza", "NaN", True, [1]])
def test_bolus_rejects_bad_carbs(
    session: Session,
    user: User,  # noqa: F811
    tools: Toolbox,
    carbs: object,
) -> None:
    add_reading(session, user, 125)
    with pytest.raises(ToolError):
        tools.run("calculate_bolus", {"carbs_g": carbs})


def test_bolus_accepts_carbs_sent_as_text(session: Session, user: User, tools: Toolbox) -> None:  # noqa: F811
    add_reading(session, user, 125)
    assert tools.run("calculate_bolus", {"carbs_g": "45"})["units"] == 3


def test_patterns_without_data(tools: Toolbox) -> None:
    result = tools.run("get_patterns", {})
    assert result["statistics"] is None
    assert result["patterns"] == []


def test_patterns_show_night_lows_with_examples(
    session: Session,
    user: User,  # noqa: F811
    tools: Toolbox,
) -> None:
    add_night_lows(session, user)
    result = tools.run("get_patterns", {"days": 14})
    [pattern] = result["patterns"]
    assert pattern["kind"] == "night_lows"
    assert pattern["supporting_readings"] == 4
    assert pattern["examples"][0]["value"] == 60


def test_patterns_reject_other_periods(tools: Toolbox) -> None:
    with pytest.raises(ToolError):
        tools.run("get_patterns", {"days": 7})


def test_propose_adjustment_only_stores_a_pending_suggestion(
    session: Session,
    user: User,  # noqa: F811
    tools: Toolbox,
) -> None:
    backdate(session, NOW - timedelta(days=60))
    add_night_lows(session, user)
    result = tools.run("propose_adjustment", {})
    [suggestion] = result["suggestions"]
    assert suggestion["setting"] == "isf"
    assert suggestion["time_block_from"] == "00:00"
    assert (suggestion["current"], suggestion["proposed"]) == (40, 44)
    assert "review page" in result["next_step"]
    [row] = pending(session, user)
    assert row.status is SuggestionStatus.PENDING
    assert user.settings is not None
    assert user.settings.time_blocks[0].isf_mgdl == 40  # nothing changed


def test_propose_adjustment_filters_by_pattern(
    session: Session,
    user: User,  # noqa: F811
    tools: Toolbox,
) -> None:
    backdate(session, NOW - timedelta(days=60))
    add_night_lows(session, user)
    assert tools.run("propose_adjustment", {"pattern": "high_fasting"})["suggestions"] == []
    with pytest.raises(ToolError):
        tools.run("propose_adjustment", {"pattern": "everything"})


def test_without_settings_tools_say_so(session: Session) -> None:
    bare = register(session, "bob@example.com", "Bob", "correct horse battery")
    with pytest.raises(ToolError, match="settings"):
        Toolbox(session, bare, NOW).run("get_settings", {})
