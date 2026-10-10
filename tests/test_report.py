"""The PDF clinic report."""

from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from glucobalance.agp import AgpPoint
from glucobalance.analytics_service import Analytics
from glucobalance.models import DisplayUnit, MonitoringMode
from glucobalance.patterns import Evidence, Finding, PatternKind
from glucobalance.report import build_report
from glucobalance.site_performance import SitePerformance
from glucobalance.stats import GlucoseStats, PeriodAverage

STATS = GlucoseStats(
    count=1344,
    mean=154.0,
    sd=50.0,
    cv=32.5,
    gmi=7.0,
    very_low=0.5,
    below=3.0,
    in_range=70.0,
    above=27.0,
    very_high=4.0,
    coverage=96.0,
    warning=None,
)
FINDING = Finding(
    kind=PatternKind.NIGHT_LOWS,
    title="Repeated night lows",
    detail="Glucose went below 70 mg/dL between midnight and 06:00 on 4 nights in this period.",
    headline_mgdl=58,
    evidence=(Evidence(datetime(2026, 10, 3, 1, 0, tzinfo=UTC), 58),),
)


def analytics(**changes: object) -> Analytics:
    values: dict[str, object] = {
        "days": 14,
        "first_day": date(2026, 9, 27),
        "last_day": date(2026, 10, 10),
        "unit": DisplayUnit.MGDL,
        "low": 70,
        "high": 180,
        "mode": MonitoringMode.CGM,
        "zone": ZoneInfo("Europe/Warsaw"),
        "stats": STATS,
        "low_episodes": 5,
        "agp": [AgpPoint(m, 80, 100, 130, 160, 200, 14) for m in range(0, 24 * 60, 15)],
        "periods": [PeriodAverage("Night", 10, 110.0)],
        "findings": [FINDING],
        "sites": [SitePerformance("abdomen-front-left-upper", 4, 190.0, 36.0, True)],
    }
    values.update(changes)
    return Analytics(**values)  # type: ignore[arg-type]


def report(data: Analytics) -> bytes:
    return build_report(
        data,
        name="Ann Kowalska",
        clinician_contact="Dr Kowalska 555 0100",
        generated_on=date(2026, 10, 10),
        compress=False,
    )


def test_the_report_is_a_pdf() -> None:
    assert report(analytics()).startswith(b"%PDF")


def test_the_report_names_the_person_and_period() -> None:
    pdf = report(analytics())
    assert b"Ann Kowalska" in pdf
    assert b"27 Sep 2026" in pdf
    assert b"10 Oct 2026" in pdf


def test_the_report_has_the_headline_figures() -> None:
    pdf = report(analytics())
    for expected in (b"Time in range", b"70.0%", b"GMI", b"7.0%", b"32.5%", b"154 mg/dL"):
        assert expected in pdf, expected


def test_the_report_converts_to_mmol() -> None:
    pdf = report(analytics(unit=DisplayUnit.MMOLL))
    assert b"8.6 mmol/L" in pdf  # 154 mg/dL


def test_the_report_lists_patterns_and_flagged_sites() -> None:
    pdf = report(analytics())
    assert b"Repeated night lows" in pdf
    assert b"Abdomen, left, upper" in pdf


def test_the_report_says_when_nothing_was_found() -> None:
    pdf = report(analytics(findings=[], sites=[]))
    assert b"No patterns" in pdf


def test_the_report_carries_the_warning_and_disclaimer() -> None:
    warned = analytics(stats=replace(STATS, warning="Only 7 days selected."))
    pdf = build_report(
        warned, name="Ann", clinician_contact=None, generated_on=date(2026, 10, 10), compress=False
    )
    assert b"Only 7 days selected." in pdf
    assert b"not a medical device" in pdf


def test_a_glucometer_report_has_time_of_day_averages_instead_of_an_agp() -> None:
    pdf = report(analytics(mode=MonitoringMode.GLUCOMETER, agp=[]))
    assert b"Average by time of day" in pdf
    assert b"Ambulatory glucose profile" not in pdf


def test_a_report_without_readings_still_builds() -> None:
    pdf = report(analytics(stats=None, agp=[], findings=[], sites=[], low_episodes=0))
    assert b"No glucose readings" in pdf


def test_polish_letters_do_not_break_the_report() -> None:
    pdf = build_report(
        analytics(),
        name="Łukasz Żółć",
        clinician_contact="dr Wiśniewska",
        generated_on=date(2026, 10, 10),
        compress=False,
    )
    assert pdf.startswith(b"%PDF")
    assert b"Lukasz Zolc" in pdf
