from datetime import UTC, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from glucobalance.models import (
    BodySide,
    BodySite,
    BodyView,
    CarbEntry,
    DeliveryMode,
    DisplayUnit,
    DoseKind,
    GlucoseReading,
    GlucoseTag,
    InsulinDose,
    InsulinType,
    MonitoringMode,
    Note,
    ReadingSource,
    Reminder,
    ReminderKind,
    SettingsTimeBlock,
    SitePurpose,
    SiteRegion,
    SiteUse,
    Trend,
    User,
    UserSettings,
)

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)


def make_user(session: Session, email: str = "demo@example.com") -> User:
    user = User(email=email, display_name="Demo")
    session.add(user)
    session.flush()
    return user


def make_settings(user: User, **overrides: object) -> UserSettings:
    values: dict[str, object] = {
        "delivery_mode": DeliveryMode.PENS,
        "monitoring_mode": MonitoringMode.GLUCOMETER,
        "max_bolus_units": Decimal("10"),
    }
    values.update(overrides)
    return UserSettings(user=user, **values)


def test_user_settings_round_trip_with_defaults(session: Session) -> None:
    user = make_user(session)
    settings = make_settings(user)
    settings.time_blocks = [
        SettingsTimeBlock(start_time=time(0, 0), icr_grams_per_unit=Decimal("10"), isf_mgdl=40),
        SettingsTimeBlock(start_time=time(6, 0), icr_grams_per_unit=Decimal("8"), isf_mgdl=35),
    ]
    session.add(settings)
    session.commit()
    session.expunge_all()

    loaded = session.scalars(select(User)).one()
    assert loaded.settings is not None
    assert loaded.settings.delivery_mode is DeliveryMode.PENS
    assert loaded.settings.display_unit is DisplayUnit.MGDL
    assert (loaded.settings.target_low_mgdl, loaded.settings.target_high_mgdl) == (70, 180)
    assert loaded.settings.insulin_action_minutes == 240
    assert loaded.settings.dose_step_units == Decimal("0.5")
    assert [b.start_time for b in loaded.settings.time_blocks] == [time(0, 0), time(6, 0)]


def test_enums_are_stored_as_readable_strings(session: Session) -> None:
    session.add(make_settings(make_user(session), delivery_mode=DeliveryMode.PUMP))
    session.commit()
    stored = session.execute(text("SELECT delivery_mode FROM user_settings")).scalar_one()
    assert stored == "pump"


def test_target_low_must_be_below_target_high(session: Session) -> None:
    session.add(make_settings(make_user(session), target_low_mgdl=180, target_high_mgdl=70))
    with pytest.raises(IntegrityError):
        session.commit()


def test_user_email_is_unique(session: Session) -> None:
    make_user(session)
    with pytest.raises(IntegrityError):
        make_user(session)


def test_glucose_reading_keeps_mgdl_and_utc(session: Session) -> None:
    user = make_user(session)
    warsaw_summer = timezone(timedelta(hours=2))
    session.add(
        GlucoseReading(
            user=user,
            measured_at=datetime(2026, 10, 1, 10, 0, tzinfo=warsaw_summer),
            value_mgdl=112,
            source=ReadingSource.CGM,
            trend=Trend.RISING,
        )
    )
    session.commit()
    session.expunge_all()

    reading = session.scalars(select(GlucoseReading)).one()
    assert reading.value_mgdl == 112
    assert reading.measured_at == T0
    assert reading.measured_at.tzinfo is UTC
    assert reading.tag is None


def test_naive_datetimes_are_rejected(session: Session) -> None:
    user = make_user(session)
    session.add(
        GlucoseReading(
            user=user,
            measured_at=datetime(2026, 10, 1, 8, 0),
            value_mgdl=100,
            source=ReadingSource.MANUAL,
        )
    )
    with pytest.raises(StatementError):
        session.commit()


def test_one_reading_per_user_source_and_time(session: Session) -> None:
    user = make_user(session)
    for _ in range(2):
        session.add(
            GlucoseReading(user=user, measured_at=T0, value_mgdl=100, source=ReadingSource.CGM)
        )
    with pytest.raises(IntegrityError):
        session.commit()


def test_glucose_value_must_be_positive(session: Session) -> None:
    user = make_user(session)
    session.add(
        GlucoseReading(user=user, measured_at=T0, value_mgdl=0, source=ReadingSource.MANUAL)
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_insulin_dose_links_to_its_injection_site(session: Session) -> None:
    user = make_user(session)
    site = BodySite(
        code="abdomen-left-1", region=SiteRegion.ABDOMEN, side=BodySide.LEFT, view=BodyView.FRONT
    )
    use = SiteUse(user=user, site=site, used_at=T0, purpose=SitePurpose.RAPID_INJECTION)
    session.add(
        InsulinDose(
            user=user,
            taken_at=T0,
            units=Decimal("4.5"),
            insulin_type=InsulinType.RAPID,
            kind=DoseKind.BOLUS,
            site_use=use,
        )
    )
    session.commit()
    session.expunge_all()

    dose = session.scalars(select(InsulinDose)).one()
    assert dose.units == Decimal("4.5")
    assert dose.site_use is not None
    assert dose.site_use.site.code == "abdomen-left-1"


def test_insulin_units_must_be_positive(session: Session) -> None:
    user = make_user(session)
    session.add(
        InsulinDose(
            user=user,
            taken_at=T0,
            units=Decimal("0"),
            insulin_type=InsulinType.LONG,
            kind=DoseKind.BASAL,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_carb_entry_note_and_reminder_round_trip(session: Session) -> None:
    user = make_user(session)
    session.add_all(
        [
            CarbEntry(user=user, eaten_at=T0, grams=Decimal("45"), description="Porridge"),
            Note(user=user, noted_at=T0, text="Sport in the afternoon"),
            Reminder(user=user, kind=ReminderKind.SET_CHANGE, title="Change set", interval_days=3),
        ]
    )
    session.commit()
    assert session.scalars(select(CarbEntry)).one().grams == Decimal("45")
    assert session.scalars(select(Note)).one().text == "Sport in the afternoon"
    reminder = session.scalars(select(Reminder)).one()
    assert reminder.active is True
    assert reminder.interval_days == 3


def test_reading_with_unknown_user_is_rejected(session: Session) -> None:
    session.add(
        GlucoseReading(user_id=999, measured_at=T0, value_mgdl=100, source=ReadingSource.MANUAL)
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_a_user_deletes_their_data(session: Session) -> None:
    user = make_user(session)
    session.add(make_settings(user))
    session.add(
        GlucoseReading(user=user, measured_at=T0, value_mgdl=100, source=ReadingSource.MANUAL)
    )
    session.add(
        GlucoseReading(
            user=user,
            measured_at=T0 + timedelta(minutes=5),
            value_mgdl=105,
            source=ReadingSource.MANUAL,
            tag=GlucoseTag.FASTING,
        )
    )
    session.commit()

    session.delete(user)
    session.commit()
    assert session.scalars(select(GlucoseReading)).all() == []
    assert session.scalars(select(UserSettings)).all() == []
