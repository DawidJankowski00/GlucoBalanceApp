"""Tests for the feature-flag function: one place that turns the two switches into flags."""

import dataclasses

import pytest

from glucobalance.features import FeatureFlags, SiteRotationUnit, feature_flags
from glucobalance.models import DeliveryMode, MonitoringMode

ALL_MODES = [(d, m) for d in DeliveryMode for m in MonitoringMode]


def flags(delivery: DeliveryMode, monitoring: MonitoringMode) -> FeatureFlags:
    return feature_flags(delivery, monitoring)


def test_flags_are_immutable() -> None:
    result = flags(DeliveryMode.PUMP, MonitoringMode.CGM)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.cgm_import = False  # type: ignore[misc]


@pytest.mark.parametrize(("delivery", "monitoring"), ALL_MODES)
def test_every_combination_is_supported(delivery: DeliveryMode, monitoring: MonitoringMode) -> None:
    result = flags(delivery, monitoring)
    assert result.delivery is delivery
    assert result.monitoring is monitoring


@pytest.mark.parametrize("monitoring", list(MonitoringMode))
def test_pump_flags(monitoring: MonitoringMode) -> None:
    f = flags(DeliveryMode.PUMP, monitoring)
    assert f.site_rotation_unit is SiteRotationUnit.PER_SET_CHANGE
    assert not f.separate_long_acting_rotation
    assert f.infusion_set_reminder
    assert f.reservoir_reminder
    assert f.pump_battery_reminder
    assert f.log_set_problems
    assert not f.long_acting_dose_reminder
    assert not f.missed_dose_alert
    assert not f.pen_needle_reminder
    assert not f.pen_expiry_reminder
    assert not f.log_injection_site_issues
    assert not f.log_each_injection


@pytest.mark.parametrize("monitoring", list(MonitoringMode))
def test_pen_flags(monitoring: MonitoringMode) -> None:
    f = flags(DeliveryMode.PENS, monitoring)
    assert f.site_rotation_unit is SiteRotationUnit.PER_INJECTION
    assert f.separate_long_acting_rotation
    assert f.long_acting_dose_reminder
    assert f.missed_dose_alert
    assert f.pen_needle_reminder
    assert f.pen_expiry_reminder
    assert f.log_injection_site_issues
    assert f.log_each_injection
    assert not f.infusion_set_reminder
    assert not f.reservoir_reminder
    assert not f.pump_battery_reminder
    assert not f.log_set_problems


@pytest.mark.parametrize("delivery", list(DeliveryMode))
def test_glucometer_flags(delivery: DeliveryMode) -> None:
    f = flags(delivery, MonitoringMode.GLUCOMETER)
    assert f.manual_glucose_entry
    assert f.glucose_check_reminders
    assert f.recheck_reminder_after_out_of_range
    assert f.sparse_data_warning
    assert not f.cgm_import
    assert not f.sensor_change_reminder
    assert not f.sensor_site_rotation
    assert not f.live_alerts
    assert not f.agp_report
    assert not f.forecast_available


@pytest.mark.parametrize("delivery", list(DeliveryMode))
def test_cgm_flags(delivery: DeliveryMode) -> None:
    f = flags(delivery, MonitoringMode.CGM)
    assert f.cgm_import
    assert f.sensor_change_reminder
    assert f.sensor_site_rotation
    assert f.live_alerts
    assert f.agp_report
    assert f.forecast_available
    assert not f.manual_glucose_entry
    assert not f.glucose_check_reminders
    assert not f.recheck_reminder_after_out_of_range
    assert not f.sparse_data_warning


def test_switching_modes_changes_only_that_axis() -> None:
    before = flags(DeliveryMode.PUMP, MonitoringMode.CGM)
    after = flags(DeliveryMode.PUMP, MonitoringMode.GLUCOMETER)
    assert before.infusion_set_reminder == after.infusion_set_reminder
    assert before.cgm_import != after.cgm_import
