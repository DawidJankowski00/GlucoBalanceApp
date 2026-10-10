r"""The PDF clinic report: one printable summary of a period for a diabetes team.

The report is drawn with fpdf2, a pure-Python PDF writer. It is built from the same
``Analytics`` that the page shows, so the paper and the screen never disagree. fpdf2's built-in
fonts only cover Latin-1, so text goes through ``_text()``, which turns letters outside Latin-1
(for example the Polish "ł") into plain ones instead of failing.
"""

import unicodedata
from datetime import date
from typing import Any

from fpdf import FPDF

from glucobalance.agp import AgpPoint
from glucobalance.analytics_service import Analytics
from glucobalance.models import DisplayUnit, MonitoringMode
from glucobalance.patterns import Finding
from glucobalance.sitemap import site_label
from glucobalance.stats import GlucoseStats
from glucobalance.units import mgdl_to_mmoll

# Letters that do not decompose into a plain letter plus an accent.
_TRANSLITERATION = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O"})

TEAL = (15, 118, 110)
GREY = (100, 116, 139)
# The five bands of the time-in-range bar, from very low to very high.
BAND_COLOURS = ((127, 29, 29), (220, 38, 38), (22, 163, 74), (245, 158, 11), (194, 65, 12))
MAX_SITES_SHOWN = 8
MAX_EXAMPLES = 5
DISCLAIMER = (
    "GlucoBalance is a personal, educational project and is not a medical device. "
    "These figures are not medical advice. Talk to your diabetes team before changing "
    "any setting or dose."
)


def _text(value: str) -> str:
    """``value`` limited to characters the built-in PDF fonts can draw."""
    plain = unicodedata.normalize("NFKD", value.translate(_TRANSLITERATION))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return plain.encode("latin-1", "replace").decode("latin-1")


def _day(day: date) -> str:
    return f"{day:%d %b %Y}"


def _glucose(mgdl: float, unit: DisplayUnit) -> str:
    """A value with its unit: whole mg/dL, or mmol/L with one decimal."""
    if unit is DisplayUnit.MMOLL:
        return f"{mgdl_to_mmoll(mgdl):.1f} {unit}"
    return f"{mgdl:.0f} {unit}"


class _Report(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(*GREY)
        self.cell(0, 5, f"Page {self.page_no()}", align="C")


def _heading(pdf: _Report, title: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*TEAL)
    pdf.cell(0, 7, _text(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", size=10)


def _paragraph(pdf: _Report, text: str, *, size: int = 10, grey: bool = False) -> None:
    pdf.set_font("Helvetica", size=size)
    pdf.set_text_color(*(GREY if grey else (0, 0, 0)))
    pdf.multi_cell(0, 5, _text(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _row(pdf: _Report, cells: list[tuple[float, str]], *, bold: bool = False) -> None:
    pdf.set_font("Helvetica", "B" if bold else "", 10)
    for width, text in cells:
        pdf.cell(width, 6, _text(text))
    pdf.ln(6)


def _range_bar(pdf: _Report, stats: GlucoseStats) -> None:
    """A stacked bar: very low, low, in range, high and very high."""
    shares = (
        stats.very_low,
        stats.below - stats.very_low,
        stats.in_range,
        stats.above - stats.very_high,
        stats.very_high,
    )
    x, y, width = pdf.l_margin, pdf.get_y() + 1, pdf.epw
    for share, colour in zip(shares, BAND_COLOURS, strict=True):
        if share <= 0:
            continue
        pdf.set_fill_color(*colour)
        pdf.rect(x, y, width * share / 100, 7, style="F")
        x += width * share / 100
    pdf.set_y(y + 10)


def _summary(pdf: _Report, data: Analytics, stats: GlucoseStats) -> None:
    low, high, unit = data.low, data.high, data.unit
    _heading(pdf, "Summary")
    if stats.warning:
        _paragraph(pdf, stats.warning)
        pdf.ln(1)
    _range_bar(pdf, stats)
    rows = [
        (
            "Time in range",
            f"{stats.in_range:.1f}%",
            f"{_glucose(low, unit)} to {_glucose(high, unit)}",
        ),
        ("Time below range", f"{stats.below:.1f}%", f"under {_glucose(low, unit)}"),
        ("  of which very low", f"{stats.very_low:.1f}%", f"under {_glucose(54, unit)}"),
        ("Time above range", f"{stats.above:.1f}%", f"over {_glucose(high, unit)}"),
        ("  of which very high", f"{stats.very_high:.1f}%", f"over {_glucose(250, unit)}"),
        ("Mean glucose", _glucose(stats.mean, unit), ""),
        ("Variability (CV)", f"{stats.cv:.1f}%", "target: 36% or lower"),
        ("GMI", f"{stats.gmi:.1f}%", "estimated HbA1c from the mean"),
        ("Readings", str(stats.count), ""),
        ("Low episodes", str(data.low_episodes), f"separate lows under {_glucose(70, unit)}"),
    ]
    if stats.coverage is not None:
        rows.append(("Sensor coverage", f"{stats.coverage:.0f}%", "at least 70% is recommended"))
    for label, value, note in rows:
        _row(pdf, [(55, label), (35, value)])
        if note:
            pdf.set_xy(pdf.l_margin + 90, pdf.get_y() - 6)
            pdf.set_text_color(*GREY)
            pdf.set_font("Helvetica", size=9)
            pdf.cell(0, 6, _text(note))
            pdf.set_text_color(0, 0, 0)
            pdf.ln(6)


def _agp(pdf: _Report, data: Analytics) -> None:
    """The AGP drawn straight from the percentile numbers: two bands and the median."""
    _heading(pdf, "Ambulatory glucose profile")
    if pdf.get_y() > 190:
        pdf.add_page()
    unit = data.unit
    scale = 1.0 if unit is DisplayUnit.MGDL else 18.0
    points: list[AgpPoint] = data.agp
    top_mgdl = max(300.0, max(p.p95 for p in points) + 20)
    left, top, width, height = pdf.l_margin + 12, pdf.get_y() + 2, pdf.epw - 14, 70.0

    def px(minute: float) -> float:
        return left + width * minute / (24 * 60)

    def py(mgdl: float) -> float:
        return top + height * (1 - min(mgdl, top_mgdl) / top_mgdl)

    pdf.set_fill_color(220, 240, 236)
    pdf.rect(left, py(data.high), width, py(data.low) - py(data.high), style="F")
    pdf.set_draw_color(200, 200, 200)
    pdf.rect(left, top, width, height)
    pdf.set_font("Helvetica", size=8)
    pdf.set_text_color(*GREY)
    step = 50 if unit is DisplayUnit.MGDL else 3
    tick = step
    while tick * scale < top_mgdl:
        pdf.line(left, py(tick * scale), left + width, py(tick * scale))
        pdf.text(left - 9, py(tick * scale) + 1, str(tick))
        tick += step
    for hour in range(0, 25, 3):
        pdf.text(px(hour * 60) - 3, top + height + 4, f"{hour:02d}")

    for lower, upper, shade in (("p5", "p95", 205), ("p25", "p75", 150)):
        edge = [(px(p.minute), py(getattr(p, upper))) for p in points]
        back = [(px(p.minute), py(getattr(p, lower))) for p in reversed(points)]
        pdf.set_fill_color(shade - 100, shade, shade - 20)
        pdf.polygon([*edge, *back], style="F")
    pdf.set_draw_color(*TEAL)
    pdf.set_line_width(0.6)
    pdf.polyline([(px(p.minute), py(p.p50)) for p in points])
    pdf.set_line_width(0.2)
    pdf.set_draw_color(0, 0, 0)
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(top + height + 7)
    _paragraph(
        pdf,
        f"Median (line), middle half of days (dark band) and 90% of days (light band), in {unit}. "
        "The pale band is the target range.",
        size=8,
        grey=True,
    )


def _time_of_day(pdf: _Report, data: Analytics) -> None:
    _heading(pdf, "Average by time of day")
    for period in data.periods:
        mean = _glucose(period.mean, data.unit) if period.mean is not None else "no readings"
        _row(pdf, [(40, period.name), (40, mean), (40, f"{period.count} readings")])


def _patterns(pdf: _Report, data: Analytics, findings: list[Finding]) -> None:
    _heading(pdf, "Patterns found")
    if not findings:
        _paragraph(pdf, "No patterns were found in this period.")
        return
    for finding in findings:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, _text(finding.title), new_x="LMARGIN", new_y="NEXT")
        _paragraph(pdf, finding.detail)
        examples = "; ".join(
            f"{e.measured_at.astimezone(data.zone):%d %b %H:%M} {_glucose(e.value_mgdl, data.unit)}"
            for e in finding.evidence[:MAX_EXAMPLES]
        )
        _paragraph(
            pdf,
            f"Typical value: {_glucose(finding.headline_mgdl, data.unit)}. Examples: {examples}",
            size=9,
            grey=True,
        )
        pdf.ln(1)


def _sites(pdf: _Report, data: Analytics) -> None:
    if pdf.get_y() > 240:
        pdf.add_page()
    _heading(pdf, "Glucose after each site (2 to 6 hours)")
    _row(
        pdf, [(80, "Site"), (20, "Uses"), (35, "Mean glucose"), (40, "Against overall")], bold=True
    )
    for row in data.sites[:MAX_SITES_SHOWN]:
        sign = "+" if row.difference_mgdl >= 0 else "-"
        gap = _glucose(abs(row.difference_mgdl), data.unit)
        flag = "  above average" if row.flagged else ""
        _row(
            pdf,
            [
                (80, site_label(row.code)),
                (20, str(row.uses)),
                (35, _glucose(row.mean_mgdl, data.unit)),
                (40, f"{sign}{gap}{flag}"),
            ],
        )


def build_report(
    data: Analytics,
    *,
    name: str,
    clinician_contact: str | None,
    generated_on: date,
    compress: bool = True,
) -> bytes:
    """The clinic report for ``data`` as PDF bytes."""
    pdf = _Report(format="A4")
    pdf.set_compression(compress)
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*TEAL)
    pdf.cell(0, 10, "GlucoBalance report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    _paragraph(pdf, f"{name}", size=12)
    _paragraph(
        pdf,
        f"{_day(data.first_day)} to {_day(data.last_day)} ({data.days} days). "
        f"Generated {_day(generated_on)}. Glucose in {data.unit}. "
        f"Monitoring: {'CGM' if data.mode is MonitoringMode.CGM else 'glucometer'}.",
        size=9,
        grey=True,
    )
    if clinician_contact:
        _paragraph(pdf, f"Clinician contact: {clinician_contact}", size=9, grey=True)
    _paragraph(pdf, DISCLAIMER, size=8, grey=True)

    if data.stats is None:
        _heading(pdf, "Summary")
        _paragraph(pdf, "No glucose readings were logged in this period.")
    else:
        _summary(pdf, data, data.stats)
        if data.show_agp:
            _agp(pdf, data)
        else:
            _time_of_day(pdf, data)
    _patterns(pdf, data, data.findings)
    if data.sites:
        _sites(pdf, data)

    output: Any = pdf.output()
    return bytes(output)
