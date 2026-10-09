"""Treatment settings: validation, saving and the change log.

Every write goes through ``apply_settings``, which validates first and then records one
``SettingsChange`` row per field that actually changed (who, when, old value, new value,
source). The onboarding wizard and the settings page both call it.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from glucobalance.models import (
    ChangeSource,
    DeliveryMode,
    DisplayUnit,
    MonitoringMode,
    SettingsChange,
    SettingsTimeBlock,
    User,
    UserSettings,
)

ALLOWED_DOSE_STEPS = (Decimal("0.05"), Decimal("0.1"), Decimal("0.5"), Decimal("1"))


class SettingsError(ValueError):
    """The settings are not acceptable. The message is safe to show to the user."""


@dataclass(frozen=True, slots=True)
class TimeBlockInput:
    start_time: time
    icr_grams_per_unit: Decimal
    isf_mgdl: int


@dataclass(frozen=True, slots=True)
class SettingsInput:
    """Everything the onboarding wizard and the settings page edit (glucose in mg/dL)."""

    delivery_mode: DeliveryMode
    monitoring_mode: MonitoringMode
    display_unit: DisplayUnit
    target_low_mgdl: int
    target_high_mgdl: int
    insulin_action_minutes: int
    max_bolus_units: Decimal
    dose_step_units: Decimal
    clinician_contact: str | None
    time_blocks: tuple[TimeBlockInput, ...]


def validate(data: SettingsInput) -> None:
    """Raise ``SettingsError`` if a value is outside what the app accepts."""
    if data.target_low_mgdl >= data.target_high_mgdl:
        raise SettingsError("The low target must be lower than the high target.")
    if not 54 <= data.target_low_mgdl <= 140:
        raise SettingsError("The low target must be between 54 and 140 mg/dL.")
    if not 100 <= data.target_high_mgdl <= 250:
        raise SettingsError("The high target must be between 100 and 250 mg/dL.")
    if not 120 <= data.insulin_action_minutes <= 480:
        raise SettingsError("The insulin action time must be between 2 and 8 hours.")
    if not Decimal(0) < data.max_bolus_units <= 50:
        raise SettingsError("The maximum bolus must be above 0 and at most 50 units.")
    if data.dose_step_units not in ALLOWED_DOSE_STEPS:
        raise SettingsError("The dose step must be 0.05, 0.1, 0.5 or 1 unit.")
    _validate_blocks(data.time_blocks)


def _validate_blocks(blocks: tuple[TimeBlockInput, ...]) -> None:
    if not blocks:
        raise SettingsError("Add at least one carb ratio and sensitivity block.")
    starts = [block.start_time for block in blocks]
    if len(set(starts)) != len(starts):
        raise SettingsError("Two blocks have the same start time.")
    if min(starts) != time(0, 0):
        raise SettingsError("The first block must start at midnight (00:00).")
    for block in blocks:
        if not Decimal(1) <= block.icr_grams_per_unit <= 150:
            raise SettingsError("The carb ratio must be between 1 and 150 g per unit.")
        if not 5 <= block.isf_mgdl <= 400:
            raise SettingsError("The sensitivity factor must be between 5 and 400 mg/dL per unit.")


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def _blocks_text(blocks: Iterable[TimeBlockInput] | Iterable[SettingsTimeBlock]) -> str:
    ordered: list[Any] = sorted(blocks, key=lambda b: b.start_time)
    return "; ".join(
        f"{b.start_time:%H:%M} icr={_text(b.icr_grams_per_unit)} isf={b.isf_mgdl}" for b in ordered
    )


_FIELDS: tuple[str, ...] = (
    "delivery_mode",
    "monitoring_mode",
    "display_unit",
    "target_low_mgdl",
    "target_high_mgdl",
    "insulin_action_minutes",
    "max_bolus_units",
    "dose_step_units",
    "clinician_contact",
)


def apply_settings(
    session: Session,
    user: User,
    data: SettingsInput,
    source: ChangeSource,
    changed_by: User | None,
) -> UserSettings:
    """Validate and save ``data`` for ``user``, logging each changed field. Never commits."""
    validate(data)
    settings = user.settings
    is_new = settings is None
    if settings is None:
        settings = UserSettings(user=user)
        session.add(settings)

    changes: list[tuple[str, str | None, str]] = []
    for name in _FIELDS:
        new = _text(getattr(data, name))
        old = None if is_new else _text(getattr(settings, name))
        if new is not None and new != old:
            changes.append((name, old, new))
        setattr(settings, name, getattr(data, name))

    new_blocks = _blocks_text(data.time_blocks)
    old_blocks = None if is_new else _blocks_text(settings.time_blocks)
    if new_blocks != old_blocks:
        changes.append(("time_blocks", old_blocks, new_blocks))
        settings.time_blocks.clear()
        session.flush()
        settings.time_blocks.extend(
            SettingsTimeBlock(
                start_time=b.start_time,
                icr_grams_per_unit=b.icr_grams_per_unit,
                isf_mgdl=b.isf_mgdl,
            )
            for b in sorted(data.time_blocks, key=lambda b: b.start_time)
        )

    session.flush()
    for field, old, new in changes:
        session.add(
            SettingsChange(
                user_id=user.id,
                changed_by_id=changed_by.id if changed_by else None,
                field=field,
                old_value=old,
                new_value=new,
                source=source,
            )
        )
    session.flush()
    return settings


def history(session: Session, user: User) -> list[SettingsChange]:
    """The user's settings changes, newest first."""
    return list(
        session.scalars(
            select(SettingsChange)
            .where(SettingsChange.user_id == user.id)
            .order_by(SettingsChange.id.desc())
        )
    )


def to_input(settings: UserSettings) -> SettingsInput:
    """Rebuild the editable form of saved settings (used to prefill the settings page)."""
    return SettingsInput(
        delivery_mode=settings.delivery_mode,
        monitoring_mode=settings.monitoring_mode,
        display_unit=settings.display_unit,
        target_low_mgdl=settings.target_low_mgdl,
        target_high_mgdl=settings.target_high_mgdl,
        insulin_action_minutes=settings.insulin_action_minutes,
        max_bolus_units=settings.max_bolus_units,
        dose_step_units=settings.dose_step_units,
        clinician_contact=settings.clinician_contact,
        time_blocks=tuple(
            TimeBlockInput(b.start_time, b.icr_grams_per_unit, b.isf_mgdl)
            for b in settings.time_blocks
        ),
    )
