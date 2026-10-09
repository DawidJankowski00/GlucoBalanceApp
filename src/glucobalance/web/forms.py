"""Turn raw form strings into ``SettingsInput``.

Users type glucose values in their chosen unit; this module converts them to mg/dL. Every
problem is raised as ``SettingsError`` with a message that can be shown on the page.
"""

from collections.abc import Mapping
from datetime import time
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from glucobalance.models import DeliveryMode, DisplayUnit, MonitoringMode
from glucobalance.settings_service import SettingsError, SettingsInput, TimeBlockInput, validate
from glucobalance.units import mgdl_to_mmoll, mmoll_to_mgdl

BLOCK_ROWS = 6
DEFAULT_BLOCK = TimeBlockInput(time(0, 0), Decimal("10"), 40)


def _enum[E: StrEnum](enum_class: type[E], raw: str, label: str) -> E:
    try:
        return enum_class(raw)
    except ValueError:
        raise SettingsError(f"Choose a value for {label}.") from None


def _decimal(raw: str, label: str) -> Decimal:
    try:
        value = Decimal(raw.strip().replace(",", "."))
    except InvalidOperation:
        raise SettingsError(f"Enter a number for {label}.") from None
    if not value.is_finite():
        raise SettingsError(f"Enter a number for {label}.")
    return value


def _glucose_mgdl(raw: str, unit: DisplayUnit, label: str) -> int:
    value = _decimal(raw, label)
    return round(value) if unit is DisplayUnit.MGDL else mmoll_to_mgdl(float(value))


def _time(raw: str) -> time:
    try:
        hours, minutes = raw.strip().split(":")
        return time(int(hours), int(minutes))
    except ValueError:
        raise SettingsError("Enter block start times as HH:MM.") from None


def parse_time_blocks(form: Mapping[str, str], unit: DisplayUnit) -> tuple[TimeBlockInput, ...]:
    blocks: list[TimeBlockInput] = []
    for row in range(BLOCK_ROWS):
        start = form.get(f"block_start_{row}", "").strip()
        icr = form.get(f"block_icr_{row}", "").strip()
        isf = form.get(f"block_isf_{row}", "").strip()
        if not (start or icr or isf):
            continue
        if not (start and icr and isf):
            raise SettingsError(
                "Fill in the start time, carb ratio and sensitivity for each block."
            )
        blocks.append(
            TimeBlockInput(
                _time(start), _decimal(icr, "the carb ratio"), _glucose_mgdl(isf, unit, "ISF")
            )
        )
    return tuple(blocks)


def parse_settings(form: Mapping[str, str], *, require_blocks: bool = True) -> SettingsInput:
    """Parse and validate a full settings form.

    With ``require_blocks=False`` (an early wizard step) a placeholder block stands in when
    none was entered yet, so the other values can still be checked.
    """
    unit = _enum(DisplayUnit, form.get("display_unit", ""), "glucose units")
    blocks = parse_time_blocks(form, unit)
    if not blocks and not require_blocks:
        blocks = (DEFAULT_BLOCK,)
    data = SettingsInput(
        delivery_mode=_enum(DeliveryMode, form.get("delivery_mode", ""), "insulin delivery"),
        monitoring_mode=_enum(
            MonitoringMode, form.get("monitoring_mode", ""), "glucose monitoring"
        ),
        display_unit=unit,
        target_low_mgdl=_glucose_mgdl(form.get("target_low", ""), unit, "the low target"),
        target_high_mgdl=_glucose_mgdl(form.get("target_high", ""), unit, "the high target"),
        insulin_action_minutes=round(
            _decimal(form.get("insulin_action_hours", ""), "the insulin action time") * 60
        ),
        max_bolus_units=_decimal(form.get("max_bolus_units", ""), "the maximum bolus"),
        dose_step_units=_decimal(form.get("dose_step_units", ""), "the dose step"),
        clinician_contact=form.get("clinician_contact", "").strip() or None,
        time_blocks=blocks,
    )
    validate(data)
    return data


def settings_to_form(data: SettingsInput) -> dict[str, str]:
    """The inverse of ``parse_settings``: the form values that show ``data`` in its unit."""

    def glucose(mgdl: int) -> str:
        return f"{mgdl_to_mmoll(mgdl):.1f}" if data.display_unit is DisplayUnit.MMOLL else str(mgdl)

    form = {
        "delivery_mode": data.delivery_mode.value,
        "monitoring_mode": data.monitoring_mode.value,
        "display_unit": data.display_unit.value,
        "target_low": glucose(data.target_low_mgdl),
        "target_high": glucose(data.target_high_mgdl),
        "insulin_action_hours": format(
            (Decimal(data.insulin_action_minutes) / 60).normalize(), "f"
        ),
        "max_bolus_units": format(data.max_bolus_units.normalize(), "f"),
        "dose_step_units": format(data.dose_step_units.normalize(), "f"),
        "clinician_contact": data.clinician_contact or "",
    }
    for row, block in enumerate(data.time_blocks[:BLOCK_ROWS]):
        form[f"block_start_{row}"] = f"{block.start_time:%H:%M}"
        form[f"block_icr_{row}"] = format(block.icr_grams_per_unit.normalize(), "f")
        form[f"block_isf_{row}"] = glucose(block.isf_mgdl)
    return form


def parse_choices(form: Mapping[str, str]) -> None:
    """Check only the three onboarding choices (the first wizard step)."""
    _enum(DisplayUnit, form.get("display_unit", ""), "glucose units")
    _enum(DeliveryMode, form.get("delivery_mode", ""), "insulin delivery")
    _enum(MonitoringMode, form.get("monitoring_mode", ""), "glucose monitoring")
