"""Chart figures for Plotly: built in Python as plain dicts, so they can be tested.

Times are sent as local wall-clock strings (``2026-10-09T08:00:00``) because Plotly draws
the axis exactly as given; values are in the user's display unit.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from glucobalance.charts import daily_figure, weekly_figure
from glucobalance.models import (
    CarbEntry,
    DisplayUnit,
    DoseKind,
    GlucoseReading,
    InsulinDose,
    InsulinType,
    ReadingSource,
)

WARSAW = ZoneInfo("Europe/Warsaw")
DAY = date(2026, 10, 9)
T0 = datetime(2026, 10, 9, 6, 0, tzinfo=UTC)  # 08:00 in Warsaw


def reading(minutes: int, value: int, *, days: int = 0) -> GlucoseReading:
    return GlucoseReading(
        user_id=1,
        measured_at=T0 + timedelta(minutes=minutes, days=days),
        value_mgdl=value,
        source=ReadingSource.MANUAL,
    )


def dose(minutes: int, units: str = "4") -> InsulinDose:
    return InsulinDose(
        user_id=1,
        taken_at=T0 + timedelta(minutes=minutes),
        units=Decimal(units),
        insulin_type=InsulinType.RAPID,
        kind=DoseKind.BOLUS,
    )


def meal(minutes: int, grams: str = "45") -> CarbEntry:
    return CarbEntry(user_id=1, eaten_at=T0 + timedelta(minutes=minutes), grams=Decimal(grams))


def trace(figure: dict, name: str) -> dict:  # type: ignore[type-arg]
    (found,) = [t for t in figure["data"] if t["name"] == name]
    return found  # type: ignore[no-any-return]


def daily(
    readings: list[GlucoseReading] | None = None,
    doses: list[InsulinDose] | None = None,
    carbs: list[CarbEntry] | None = None,
    unit: DisplayUnit = DisplayUnit.MGDL,
) -> dict:  # type: ignore[type-arg]
    return daily_figure(
        DAY,
        WARSAW,
        readings=readings or [],
        doses=doses or [],
        carbs=carbs or [],
        unit=unit,
        target_low_mgdl=70,
        target_high_mgdl=180,
    )


# ---------- daily ----------


def test_glucose_points_use_local_times_and_values() -> None:
    glucose = trace(daily([reading(0, 110), reading(90, 145)]), "Glucose")
    assert glucose["x"] == ["2026-10-09T08:00:00", "2026-10-09T09:30:00"]
    assert glucose["y"] == [110, 145]


def test_mmol_users_get_mmol_values_and_band() -> None:
    figure = daily([reading(0, 126)], unit=DisplayUnit.MMOLL)
    assert trace(figure, "Glucose")["y"] == [7.0]
    band = figure["layout"]["shapes"][0]
    assert (band["y0"], band["y1"]) == (3.9, 10.0)
    assert "mmol/L" in figure["layout"]["yaxis"]["title"]["text"]


def test_target_band_spans_the_whole_day() -> None:
    band = daily()["layout"]["shapes"][0]
    assert band["type"] == "rect"
    assert (band["y0"], band["y1"]) == (70, 180)
    assert (band["x0"], band["x1"]) == ("2026-10-09T00:00:00", "2026-10-10T00:00:00")


def test_x_axis_covers_the_local_day() -> None:
    assert daily()["layout"]["xaxis"]["range"] == ["2026-10-09T00:00:00", "2026-10-10T00:00:00"]


def test_y_axis_always_shows_the_band_and_every_reading() -> None:
    low, high = daily([reading(0, 45), reading(60, 310)])["layout"]["yaxis"]["range"]
    assert low <= 45 and high >= 310
    low, high = daily([reading(0, 100)])["layout"]["yaxis"]["range"]
    assert low <= 70 and high >= 180


def test_insulin_and_carbs_are_marked_with_their_amounts() -> None:
    figure = daily(doses=[dose(10, "4.5")], carbs=[meal(15, "45")])
    insulin = trace(figure, "Insulin")
    carbs = trace(figure, "Carbs")
    assert insulin["x"] == ["2026-10-09T08:10:00"]
    assert insulin["text"] == ["4.5 u"]
    assert carbs["x"] == ["2026-10-09T08:15:00"]
    assert carbs["text"] == ["45 g"]


def test_markers_sit_in_their_own_strip_below_the_glucose_plot() -> None:
    figure = daily([reading(0, 100)], doses=[dose(10)], carbs=[meal(15)])
    strip = figure["layout"]["yaxis2"]
    glucose_domain = figure["layout"]["yaxis"]["domain"]
    assert strip["domain"][1] <= glucose_domain[0]
    for name in ("Insulin", "Carbs"):
        marker = trace(figure, name)
        assert marker["yaxis"] == "y2"
        assert all(strip["range"][0] < y < strip["range"][1] for y in marker["y"])
    assert trace(figure, "Insulin")["y"] != trace(figure, "Carbs")["y"]
    assert "yaxis" not in trace(figure, "Glucose")


def test_an_empty_day_still_has_all_traces_and_no_points() -> None:
    figure = daily()
    assert [t["name"] for t in figure["data"]] == ["Glucose", "Insulin", "Carbs"]
    assert all(t["x"] == [] for t in figure["data"])


def test_figure_is_json_serialisable() -> None:
    import json

    json.dumps(daily([reading(0, 110)], doses=[dose(5)], carbs=[meal(5)]))


# ---------- weekly ----------


def weekly(readings: list[GlucoseReading], unit: DisplayUnit = DisplayUnit.MGDL) -> dict:  # type: ignore[type-arg]
    return weekly_figure(
        DAY,
        WARSAW,
        readings=readings,
        unit=unit,
        target_low_mgdl=70,
        target_high_mgdl=180,
    )


def test_week_covers_seven_local_days_ending_on_the_chosen_day() -> None:
    layout = weekly([])["layout"]
    assert layout["xaxis"]["range"] == ["2026-10-03T00:00:00", "2026-10-10T00:00:00"]
    band = layout["shapes"][0]
    assert (band["x0"], band["x1"]) == ("2026-10-03T00:00:00", "2026-10-10T00:00:00")
    assert (band["y0"], band["y1"]) == (70, 180)


def test_week_shows_every_reading() -> None:
    figure = weekly([reading(0, 100, days=-6), reading(0, 120), reading(120, 140)])
    readings = trace(figure, "Readings")
    assert readings["x"] == ["2026-10-03T08:00:00", "2026-10-09T08:00:00", "2026-10-09T10:00:00"]
    assert readings["y"] == [100, 120, 140]


def test_readings_outside_the_week_are_left_out() -> None:
    figure = weekly([reading(0, 100, days=-7), reading(0, 110, days=1), reading(0, 120)])
    assert trace(figure, "Readings")["y"] == [120]


def test_daily_average_has_one_point_per_day_with_readings() -> None:
    figure = weekly(
        [reading(0, 100), reading(60, 140), reading(0, 90, days=-2), reading(0, 96, days=-2)]
    )
    average = trace(figure, "Daily average")
    assert average["x"] == ["2026-10-07T12:00:00", "2026-10-09T12:00:00"]
    assert average["y"] == [93, 120]


def test_daily_average_in_mmol_has_one_decimal() -> None:
    figure = weekly([reading(0, 126), reading(60, 144)], unit=DisplayUnit.MMOLL)
    assert trace(figure, "Daily average")["y"] == [7.5]


def test_an_empty_week_has_empty_traces() -> None:
    figure = weekly([])
    assert [t["name"] for t in figure["data"]] == ["Readings", "Daily average"]
    assert all(t["x"] == [] for t in figure["data"])
