"""Site performance: how glucose looked after each injection or infusion site was used.

An overused site can build scar tissue (lipohypertrophy) and absorb insulin badly, which shows up
as higher glucose in the hours after a dose or set change. For each use of a site the mean
glucose from two to six hours later is taken, and the uses of one site are averaged. A site that
sits well above the user's overall mean after enough uses is flagged. This is a hint to look at
the site, not a diagnosis.
"""

import statistics
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from glucobalance.models import GlucoseReading

WINDOW_FROM = timedelta(hours=2)
WINDOW_TO = timedelta(hours=6)
MIN_READINGS_PER_USE = 3  # fewer readings than this in the window and the use is skipped
MIN_USES_TO_FLAG = 3
FLAG_DIFFERENCE_MGDL = 15  # how far above the overall mean a site must sit to be flagged


@dataclass(frozen=True, slots=True)
class SiteUseRecord:
    """One use of a site: its code and when."""

    code: str
    used_at: datetime


@dataclass(frozen=True, slots=True)
class SitePerformance:
    code: str
    uses: int  # uses that had enough readings after them
    mean_mgdl: float
    difference_mgdl: float  # against the mean of all readings in the period
    flagged: bool


def site_performance(
    uses: Sequence[SiteUseRecord], readings: Sequence[GlucoseReading]
) -> list[SitePerformance]:
    """The average glucose after each site, highest first."""
    if not readings:
        return []
    ordered = sorted(readings, key=lambda r: r.measured_at)
    moments = [r.measured_at for r in ordered]
    overall = statistics.fmean(r.value_mgdl for r in ordered)

    per_site: dict[str, list[float]] = defaultdict(list)
    for use in uses:
        first = bisect_left(moments, use.used_at + WINDOW_FROM)
        last = bisect_left(moments, use.used_at + WINDOW_TO)
        window = ordered[first:last]
        if len(window) >= MIN_READINGS_PER_USE:
            per_site[use.code].append(statistics.fmean(r.value_mgdl for r in window))

    rows = [
        SitePerformance(
            code=code,
            uses=len(means),
            mean_mgdl=statistics.fmean(means),
            difference_mgdl=statistics.fmean(means) - overall,
            flagged=(
                len(means) >= MIN_USES_TO_FLAG
                and statistics.fmean(means) - overall >= FLAG_DIFFERENCE_MGDL
            ),
        )
        for code, means in per_site.items()
    ]
    return sorted(rows, key=lambda row: row.mean_mgdl, reverse=True)
