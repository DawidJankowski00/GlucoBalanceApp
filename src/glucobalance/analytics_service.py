"""Puts the analytics together for one user and period.

The page and the PDF report both call ``build_analytics`` so they always show the same numbers.
All the maths lives in ``stats``, ``agp``, ``patterns`` and ``site_performance``; this module
only loads the data and calls them.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from glucobalance.agp import AgpPoint, agp_profile
from glucobalance.models import DisplayUnit, MonitoringMode, User
from glucobalance.patterns import LOW_MGDL, Finding, detect_patterns
from glucobalance.repositories import CarbRepository, GlucoseRepository, SiteRepository
from glucobalance.site_performance import SitePerformance, SiteUseRecord, site_performance
from glucobalance.stats import (
    GlucoseStats,
    PeriodAverage,
    compute_stats,
    low_episodes,
    time_of_day_averages,
)
from glucobalance.timeline import day_bounds

PERIOD_CHOICES = (14, 30)


@dataclass(frozen=True, slots=True)
class Analytics:
    """Everything shown for one period, in mg/dL (display conversion happens at the edges)."""

    days: int
    first_day: date  # local days, both included
    last_day: date
    unit: DisplayUnit
    low: int
    high: int
    mode: MonitoringMode
    zone: ZoneInfo
    stats: GlucoseStats | None
    low_episodes: int
    agp: list[AgpPoint]
    periods: list[PeriodAverage]
    findings: list[Finding]
    sites: list[SitePerformance]

    @property
    def show_agp(self) -> bool:
        """The AGP needs a CGM; glucometer users get the time-of-day averages instead."""
        return self.mode is MonitoringMode.CGM and bool(self.agp)


def build_analytics(session: Session, user: User, *, days: int, now: datetime) -> Analytics:
    """The analytics for the last ``days`` local days up to and including today."""
    settings = user.settings
    if settings is None:
        raise ValueError("the user has not finished onboarding")
    zone = ZoneInfo(settings.timezone)
    last_day = now.astimezone(zone).date()
    first_day = last_day - timedelta(days=days - 1)
    start = day_bounds(first_day, zone)[0]
    end = day_bounds(last_day, zone)[1]

    readings = GlucoseRepository(session).between(user.id, start, end)
    carbs = CarbRepository(session).between(user.id, start, end)
    uses = SiteRepository(session).uses_between(user.id, start, end)
    mode = settings.monitoring_mode
    return Analytics(
        days=days,
        first_day=first_day,
        last_day=last_day,
        unit=settings.display_unit,
        low=settings.target_low_mgdl,
        high=settings.target_high_mgdl,
        mode=mode,
        zone=zone,
        stats=compute_stats(
            readings,
            low=settings.target_low_mgdl,
            high=settings.target_high_mgdl,
            days=days,
            mode=mode,
        ),
        low_episodes=low_episodes(readings, limit=LOW_MGDL),
        agp=agp_profile(readings, zone) if mode is MonitoringMode.CGM else [],
        periods=time_of_day_averages(readings, zone),
        findings=detect_patterns(readings, carbs, zone, high=settings.target_high_mgdl),
        sites=site_performance([SiteUseRecord(code, used_at) for code, used_at in uses], readings),
    )


def parse_days(raw: str | None) -> int:
    """The period from a query string; anything but 14 or 30 falls back to 14."""
    try:
        days = int(raw) if raw else PERIOD_CHOICES[0]
    except ValueError:
        return PERIOD_CHOICES[0]
    return days if days in PERIOD_CHOICES else PERIOD_CHOICES[0]
