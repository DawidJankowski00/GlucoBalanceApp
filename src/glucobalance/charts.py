"""Figures for the charts, built in Python as plain dicts that Plotly draws in the browser.

Keeping the figure in Python means the numbers on the chart (local times, the target band,
mmol/L conversion) are tested, and the browser only does the drawing. Times go out as local
wall-clock strings such as ``2026-10-09T08:00:00``: Plotly draws a date axis exactly as given.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from glucobalance.models import CarbEntry, DisplayUnit, GlucoseReading, InsulinDose
from glucobalance.units import mgdl_to_mmoll

type Figure = dict[str, Any]

GLUCOSE_COLOUR = "#0f766e"
INSULIN_COLOUR = "#7c3aed"
CARBS_COLOUR = "#d97706"
BAND_COLOUR = "rgba(15, 118, 110, 0.12)"
# Insulin and carbs sit in their own strip under the glucose plot (a second y axis), so their
# labels never collide with the glucose line. These are the rows inside that strip.
_STRIP_DOMAIN = [0.0, 0.22]
_STRIP_RANGE = [0, 3]
_INSULIN_ROW = 0.6
_CARB_ROW = 1.9


def _local(moment: datetime, zone: ZoneInfo) -> str:
    return moment.astimezone(zone).replace(tzinfo=None).isoformat(timespec="seconds")


def _midnight(day: date) -> str:
    return datetime.combine(day, time(0, 0)).isoformat(timespec="seconds")


def _shown(mgdl: float, unit: DisplayUnit) -> float:
    """A mg/dL value in the display unit: whole mg/dL, or mmol/L with one decimal."""
    return round(mgdl) if unit is DisplayUnit.MGDL else mgdl_to_mmoll(mgdl)


def _y_range(values: Sequence[int], low: int, high: int, unit: DisplayUnit) -> list[float]:
    """A y-axis that always shows the target band and every value, with room below for markers."""
    bottom = max(0, min([*values, low]) - 30)
    bottom = min(bottom, 40)
    top = max(max([*values, high]) + 20, 250)
    return [_shown(bottom, unit), _shown(top, unit)]


def _band(x_range: list[str], low: int, high: int, unit: DisplayUnit) -> Figure:
    return {
        "type": "rect",
        "xref": "x",
        "yref": "y",
        "x0": x_range[0],
        "x1": x_range[1],
        "y0": _shown(low, unit),
        "y1": _shown(high, unit),
        "fillcolor": BAND_COLOUR,
        "line": {"width": 0},
        "layer": "below",
    }


def _layout(x_range: list[str], y_range: list[float], band: Figure, unit: DisplayUnit) -> Figure:
    return {
        "height": 380,
        "margin": {"l": 52, "r": 12, "t": 12, "b": 40},
        "showlegend": True,
        "legend": {"orientation": "h", "y": -0.18},
        "xaxis": {"type": "date", "range": x_range, "tickformat": "%H:%M"},
        "yaxis": {"range": y_range, "title": {"text": f"Glucose ({unit.value})"}},
        "shapes": [band],
    }


def _units(value: Any) -> str:
    return format(value.normalize(), "f")


def daily_figure(
    day: date,
    zone: ZoneInfo,
    *,
    readings: Sequence[GlucoseReading],
    doses: Sequence[InsulinDose],
    carbs: Sequence[CarbEntry],
    unit: DisplayUnit,
    target_low_mgdl: int,
    target_high_mgdl: int,
) -> Figure:
    """One local day: glucose line, target band, and insulin and carb markers."""
    x_range = [_midnight(day), _midnight(day + timedelta(days=1))]
    y_range = _y_range([r.value_mgdl for r in readings], target_low_mgdl, target_high_mgdl, unit)
    layout = _layout(
        x_range, y_range, _band(x_range, target_low_mgdl, target_high_mgdl, unit), unit
    )
    layout["yaxis"]["domain"] = [0.28, 1.0]
    layout["yaxis2"] = {
        "domain": _STRIP_DOMAIN,
        "range": _STRIP_RANGE,
        "showticklabels": False,
        "showgrid": False,
        "zeroline": False,
        "fixedrange": True,
    }
    data = [
        {
            "type": "scatter",
            "mode": "lines+markers",
            "name": "Glucose",
            "x": [_local(r.measured_at, zone) for r in readings],
            "y": [_shown(r.value_mgdl, unit) for r in readings],
            "line": {"color": GLUCOSE_COLOUR, "width": 2},
            "marker": {"color": GLUCOSE_COLOUR, "size": 7},
        },
        {
            "type": "scatter",
            "mode": "markers+text",
            "name": "Insulin",
            "x": [_local(d.taken_at, zone) for d in doses],
            "yaxis": "y2",
            "y": [_INSULIN_ROW for _ in doses],
            "text": [f"{_units(d.units)} u" for d in doses],
            "textposition": "top center",
            "marker": {"color": INSULIN_COLOUR, "symbol": "triangle-up", "size": 11},
        },
        {
            "type": "scatter",
            "mode": "markers+text",
            "name": "Carbs",
            "x": [_local(c.eaten_at, zone) for c in carbs],
            "yaxis": "y2",
            "y": [_CARB_ROW for _ in carbs],
            "text": [f"{_units(c.grams)} g" for c in carbs],
            "hovertext": [c.description or "" for c in carbs],
            "textposition": "top center",
            "marker": {"color": CARBS_COLOUR, "symbol": "square", "size": 10},
        },
    ]
    return {"data": data, "layout": layout}


def weekly_figure(
    last_day: date,
    zone: ZoneInfo,
    *,
    readings: Sequence[GlucoseReading],
    unit: DisplayUnit,
    target_low_mgdl: int,
    target_high_mgdl: int,
) -> Figure:
    """Seven local days ending on ``last_day``: every reading and the average of each day."""
    first_day = last_day - timedelta(days=6)
    x_range = [_midnight(first_day), _midnight(last_day + timedelta(days=1))]
    in_week = sorted(
        (r for r in readings if first_day <= r.measured_at.astimezone(zone).date() <= last_day),
        key=lambda r: r.measured_at,
    )
    by_day: dict[date, list[int]] = defaultdict(list)
    for r in in_week:
        by_day[r.measured_at.astimezone(zone).date()].append(r.value_mgdl)
    layout = _layout(
        x_range,
        _y_range([r.value_mgdl for r in in_week], target_low_mgdl, target_high_mgdl, unit),
        _band(x_range, target_low_mgdl, target_high_mgdl, unit),
        unit,
    )
    layout["xaxis"]["tickformat"] = "%d %b"
    layout["xaxis"]["dtick"] = 86_400_000
    data = [
        {
            "type": "scatter",
            "mode": "markers",
            "name": "Readings",
            "x": [_local(r.measured_at, zone) for r in in_week],
            "y": [_shown(r.value_mgdl, unit) for r in in_week],
            "marker": {"color": GLUCOSE_COLOUR, "size": 6, "opacity": 0.55},
        },
        {
            "type": "scatter",
            "mode": "lines+markers",
            "name": "Daily average",
            "x": [datetime.combine(d, time(12, 0)).isoformat() for d in sorted(by_day)],
            "y": [_shown(sum(by_day[d]) / len(by_day[d]), unit) for d in sorted(by_day)],
            "line": {"color": INSULIN_COLOUR, "width": 2},
            "marker": {"color": INSULIN_COLOUR, "size": 9},
        },
    ]
    return {"data": data, "layout": layout}
