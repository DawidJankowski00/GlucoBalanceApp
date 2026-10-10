"""The ambulatory glucose profile (AGP): how glucose behaves over a typical day.

Readings from every day in the period are folded onto one 24-hour local clock and cut into
15-minute buckets. For each bucket the 5th, 25th, 50th, 75th and 95th percentiles show the
spread: the median is the typical day, the inner band holds half of the days and the outer
band nine in ten. The figure is a plain dict that Plotly draws, like the charts in ``charts.py``.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from glucobalance.charts import BAND_COLOUR, GLUCOSE_COLOUR, Figure, _shown, _y_range
from glucobalance.models import DisplayUnit, GlucoseReading

BUCKET_MINUTES = 15
# A bucket with fewer readings than this has no meaningful percentiles and is skipped.
MIN_PER_BUCKET = 3


@dataclass(frozen=True, slots=True)
class AgpPoint:
    """The percentile band for one 15-minute bucket, in mg/dL."""

    minute: int  # minutes after local midnight at the start of the bucket
    p5: float
    p25: float
    p50: float
    p75: float
    p95: float
    count: int


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """The ``q``-th percentile (0 to 100) of sorted values, interpolating between neighbours."""
    if not sorted_values:
        raise ValueError("no values")
    position = (len(sorted_values) - 1) * q / 100
    below = int(position)
    above = min(below + 1, len(sorted_values) - 1)
    fraction = position - below
    return sorted_values[below] + (sorted_values[above] - sorted_values[below]) * fraction


def agp_profile(readings: Iterable[GlucoseReading], zone: ZoneInfo) -> list[AgpPoint]:
    """The percentile bands per bucket of the local day, ordered by time."""
    buckets: dict[int, list[float]] = defaultdict(list)
    for reading in readings:
        local = reading.measured_at.astimezone(zone)
        minute = (local.hour * 60 + local.minute) // BUCKET_MINUTES * BUCKET_MINUTES
        buckets[minute].append(float(reading.value_mgdl))
    points = []
    for minute in sorted(buckets):
        values = sorted(buckets[minute])
        if len(values) < MIN_PER_BUCKET:
            continue
        points.append(
            AgpPoint(
                minute,
                percentile(values, 5),
                percentile(values, 25),
                percentile(values, 50),
                percentile(values, 75),
                percentile(values, 95),
                len(values),
            )
        )
    return points


def _band(
    hours: list[float], lower: list[float], upper: list[float], name: str, colour: str
) -> list[Figure]:
    """Two traces make one shaded band: an invisible lower edge, then the upper edge filled down."""
    edge: Figure = {"type": "scatter", "x": hours, "mode": "lines", "line": {"width": 0}}
    return [
        {**edge, "y": lower, "hoverinfo": "skip", "showlegend": False},
        {
            **edge,
            "y": upper,
            "fill": "tonexty",
            "fillcolor": colour,
            "name": name,
            "hoverinfo": "skip",
        },
    ]


def agp_figure(points: Sequence[AgpPoint], unit: DisplayUnit, *, low: int, high: int) -> Figure:
    """The AGP as a Plotly figure: two shaded bands, the median and the target range."""
    hours = [p.minute / 60 for p in points]

    def series(attribute: str) -> list[float]:
        return [_shown(getattr(p, attribute), unit) for p in points]

    median: Figure = {
        "type": "scatter",
        "x": hours,
        "y": series("p50"),
        "mode": "lines",
        "line": {"color": GLUCOSE_COLOUR, "width": 3},
        "name": "Median",
    }
    values = [int(p.p5) for p in points] + [int(p.p95) for p in points]
    return {
        "data": [
            *_band(
                hours,
                series("p5"),
                series("p95"),
                "5th to 95th percentile",
                "rgba(15,118,110,0.15)",
            ),
            *_band(
                hours,
                series("p25"),
                series("p75"),
                "25th to 75th percentile",
                "rgba(15,118,110,0.35)",
            ),
            median,
        ],
        "layout": {
            "xaxis": {
                "range": [0, 24],
                "tickvals": list(range(0, 25, 3)),
                "ticktext": [f"{h:02d}:00" for h in range(0, 25, 3)],
            },
            "yaxis": {"title": str(unit), "range": _y_range(values, low, high, unit)},
            "shapes": [
                {
                    "type": "rect",
                    "xref": "paper",
                    "yref": "y",
                    "x0": 0,
                    "x1": 1,
                    "y0": _shown(low, unit),
                    "y1": _shown(high, unit),
                    "fillcolor": BAND_COLOUR,
                    "line": {"width": 0},
                    "layer": "below",
                }
            ],
            "legend": {"orientation": "h"},
            "margin": {"l": 50, "r": 10, "t": 10, "b": 40},
        },
    }
