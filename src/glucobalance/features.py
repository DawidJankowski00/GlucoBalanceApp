"""Feature flags derived from the two onboarding switches.

``feature_flags`` is the single place that decides what each mode means. Screens, reminders
and the assistant ask this function (never the raw settings), so a behaviour change for pump
or pens, glucometer or CGM is made once, here.
"""

from dataclasses import dataclass
from enum import StrEnum

from glucobalance.models.user import DeliveryMode, MonitoringMode


class SiteRotationUnit(StrEnum):
    """What counts as one step of site rotation."""

    PER_SET_CHANGE = "per_set_change"
    PER_INJECTION = "per_injection"


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    delivery: DeliveryMode
    monitoring: MonitoringMode

    # Insulin delivery
    site_rotation_unit: SiteRotationUnit
    separate_long_acting_rotation: bool
    infusion_set_reminder: bool
    reservoir_reminder: bool
    pump_battery_reminder: bool
    log_set_problems: bool
    long_acting_dose_reminder: bool
    missed_dose_alert: bool
    pen_needle_reminder: bool
    pen_expiry_reminder: bool
    log_injection_site_issues: bool
    log_each_injection: bool

    # Glucose monitoring
    manual_glucose_entry: bool
    glucose_check_reminders: bool
    recheck_reminder_after_out_of_range: bool
    sparse_data_warning: bool
    cgm_import: bool
    sensor_change_reminder: bool
    sensor_site_rotation: bool
    live_alerts: bool
    agp_report: bool
    forecast_available: bool


def feature_flags(delivery: DeliveryMode, monitoring: MonitoringMode) -> FeatureFlags:
    """Turn the pump/pens and glucometer/CGM choices into feature flags."""
    pump = delivery is DeliveryMode.PUMP
    pens = delivery is DeliveryMode.PENS
    cgm = monitoring is MonitoringMode.CGM
    meter = monitoring is MonitoringMode.GLUCOMETER
    return FeatureFlags(
        delivery=delivery,
        monitoring=monitoring,
        site_rotation_unit=(
            SiteRotationUnit.PER_SET_CHANGE if pump else SiteRotationUnit.PER_INJECTION
        ),
        separate_long_acting_rotation=pens,
        infusion_set_reminder=pump,
        reservoir_reminder=pump,
        pump_battery_reminder=pump,
        log_set_problems=pump,
        long_acting_dose_reminder=pens,
        missed_dose_alert=pens,
        pen_needle_reminder=pens,
        pen_expiry_reminder=pens,
        log_injection_site_issues=pens,
        log_each_injection=pens,
        manual_glucose_entry=meter,
        glucose_check_reminders=meter,
        recheck_reminder_after_out_of_range=meter,
        sparse_data_warning=meter,
        cgm_import=cgm,
        sensor_change_reminder=cgm,
        sensor_site_rotation=cgm,
        live_alerts=cgm,
        agp_report=cgm,
        forecast_available=cgm,
    )
