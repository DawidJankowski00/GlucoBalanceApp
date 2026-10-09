"""Validation of treatment settings and the change log."""

from dataclasses import replace
from datetime import time
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.models import (
    ChangeSource,
    DeliveryMode,
    DisplayUnit,
    MonitoringMode,
    SettingsChange,
    User,
)
from glucobalance.settings_service import (
    SettingsError,
    SettingsInput,
    TimeBlockInput,
    apply_settings,
    history,
    validate,
)


def make_input() -> SettingsInput:
    return SettingsInput(
        delivery_mode=DeliveryMode.PUMP,
        monitoring_mode=MonitoringMode.CGM,
        display_unit=DisplayUnit.MGDL,
        target_low_mgdl=70,
        target_high_mgdl=180,
        insulin_action_minutes=240,
        max_bolus_units=Decimal("10"),
        dose_step_units=Decimal("0.5"),
        clinician_contact=None,
        time_blocks=(TimeBlockInput(time(0, 0), Decimal("10"), 40),),
    )


@pytest.fixture
def user(session: Session) -> User:
    return register(session, "ann@example.com", "Ann", "correct horse battery")


def test_valid_input_passes() -> None:
    validate(make_input())


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"target_low_mgdl": 180, "target_high_mgdl": 70}, "lower"),
        ({"target_low_mgdl": 20}, "low target"),
        ({"target_high_mgdl": 400}, "high target"),
        ({"insulin_action_minutes": 30}, "action time"),
        ({"max_bolus_units": Decimal("0")}, "maximum bolus"),
        ({"max_bolus_units": Decimal("80")}, "maximum bolus"),
        ({"dose_step_units": Decimal("0.3")}, "dose step"),
        ({"time_blocks": ()}, "at least one"),
        ({"time_blocks": (TimeBlockInput(time(6, 0), Decimal("10"), 40),)}, "midnight"),
        (
            {
                "time_blocks": (
                    TimeBlockInput(time(0, 0), Decimal("10"), 40),
                    TimeBlockInput(time(0, 0), Decimal("8"), 35),
                )
            },
            "same start",
        ),
        ({"time_blocks": (TimeBlockInput(time(0, 0), Decimal("0"), 40),)}, "carb ratio"),
        ({"time_blocks": (TimeBlockInput(time(0, 0), Decimal("10"), 2),)}, "sensitivity"),
        ({"site_rest_days": 2}, "rest"),
        ({"site_rest_days": 61}, "rest"),
        ({"set_change_days": 0}, "set change"),
        ({"set_change_days": 8}, "set change"),
        ({"timezone": "Mars/Olympus_Mons"}, "time zone"),
        ({"timezone": ""}, "time zone"),
        ({"timezone": "../etc/passwd"}, "time zone"),
    ],
)
def test_invalid_input_is_rejected(changes: dict[str, object], message: str) -> None:
    with pytest.raises(SettingsError, match=message):
        validate(replace(make_input(), **changes))  # type: ignore[arg-type]


def test_first_save_creates_settings_and_logs_every_field(session: Session, user: User) -> None:
    settings = apply_settings(session, user, make_input(), ChangeSource.ONBOARDING, user)
    assert user.settings is settings
    assert settings.delivery_mode is DeliveryMode.PUMP
    assert [b.start_time for b in settings.time_blocks] == [time(0, 0)]
    changes = history(session, user)
    fields = {c.field for c in changes}
    assert {"delivery_mode", "monitoring_mode", "target_low_mgdl", "time_blocks"} <= fields
    assert all(c.old_value is None and c.source is ChangeSource.ONBOARDING for c in changes)


def test_update_logs_only_what_changed(session: Session, user: User) -> None:
    apply_settings(session, user, make_input(), ChangeSource.ONBOARDING, user)
    before = len(history(session, user))

    updated = replace(make_input(), target_high_mgdl=160, max_bolus_units=Decimal("10.0"))
    apply_settings(session, user, updated, ChangeSource.USER, user)

    new = history(session, user)[: len(history(session, user)) - before]
    assert [(c.field, c.old_value, c.new_value) for c in new] == [
        ("target_high_mgdl", "180", "160")
    ]
    assert new[0].source is ChangeSource.USER
    assert new[0].changed_by_id == user.id


def test_no_change_logs_nothing(session: Session, user: User) -> None:
    apply_settings(session, user, make_input(), ChangeSource.ONBOARDING, user)
    before = len(history(session, user))
    assert apply_settings(session, user, make_input(), ChangeSource.USER, user)
    assert len(history(session, user)) == before


def test_time_block_change_replaces_blocks_and_is_logged(session: Session, user: User) -> None:
    apply_settings(session, user, make_input(), ChangeSource.ONBOARDING, user)
    blocks = (
        TimeBlockInput(time(0, 0), Decimal("10"), 40),
        TimeBlockInput(time(7, 0), Decimal("8"), 35),
    )
    settings = apply_settings(
        session, user, replace(make_input(), time_blocks=blocks), ChangeSource.USER, user
    )
    assert [(b.start_time, b.icr_grams_per_unit, b.isf_mgdl) for b in settings.time_blocks] == [
        (time(0, 0), Decimal("10.0"), 40),
        (time(7, 0), Decimal("8.0"), 35),
    ]
    latest = history(session, user)[0]
    assert latest.field == "time_blocks"
    assert latest.old_value == "00:00 icr=10 isf=40"
    assert latest.new_value == "00:00 icr=10 isf=40; 07:00 icr=8 isf=35"


def test_invalid_update_changes_nothing(session: Session, user: User) -> None:
    apply_settings(session, user, make_input(), ChangeSource.ONBOARDING, user)
    before = len(history(session, user))
    with pytest.raises(SettingsError):
        apply_settings(
            session, user, replace(make_input(), target_low_mgdl=500), ChangeSource.USER, user
        )
    assert len(history(session, user)) == before
    assert session.query(SettingsChange).count() == before


def test_timezone_defaults_to_utc_and_changes_are_logged(session: Session, user: User) -> None:
    settings = apply_settings(session, user, make_input(), ChangeSource.ONBOARDING, user)
    assert settings.timezone == "UTC"

    warsaw = replace(make_input(), timezone="Europe/Warsaw")
    apply_settings(session, user, warsaw, ChangeSource.USER, user)
    latest = history(session, user)[0]
    assert (latest.field, latest.old_value, latest.new_value) == (
        "timezone",
        "UTC",
        "Europe/Warsaw",
    )


def test_rotation_settings_default_to_14_and_3_days() -> None:
    data = make_input()
    assert (data.site_rest_days, data.set_change_days) == (14, 3)


def test_changing_the_rest_period_is_logged(user: User, session: Session) -> None:
    apply_settings(session, user, make_input(), ChangeSource.ONBOARDING, user)
    apply_settings(
        session,
        user,
        replace(make_input(), site_rest_days=21, set_change_days=2),
        ChangeSource.USER,
        user,
    )

    assert user.settings is not None
    assert (user.settings.site_rest_days, user.settings.set_change_days) == (21, 2)
    changed = {(c.field, c.old_value, c.new_value) for c in history(session, user)[:2]}
    assert changed == {("site_rest_days", "14", "21"), ("set_change_days", "3", "2")}
