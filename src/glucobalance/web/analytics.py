"""The analytics page and the PDF clinic report."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from glucobalance.agp import agp_figure
from glucobalance.analytics_service import PERIOD_CHOICES, build_analytics, parse_days
from glucobalance.models import DisplayUnit
from glucobalance.report import build_report
from glucobalance.sitemap import site_label
from glucobalance.units import mgdl_to_mmoll
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.rendering import render

router = APIRouter()


@router.get("/analytics", response_model=None)
def analytics_page(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    templates: Templates,
    days: str | None = None,
) -> HTMLResponse | RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    data = build_analytics(db, user, days=parse_days(days), now=datetime.now(UTC))
    unit = data.unit

    def shown(mgdl: float) -> str:
        """A glucose value without its unit: whole mg/dL, or mmol/L with one decimal."""
        return f"{mgdl_to_mmoll(mgdl):.1f}" if unit is DisplayUnit.MMOLL else f"{mgdl:.0f}"

    figure = agp_figure(data.agp, unit, low=data.low, high=data.high) if data.show_agp else None
    return render(
        request,
        templates,
        "analytics.html",
        user,
        data=data,
        figure=figure,
        shown=shown,
        site_label=site_label,
        choices=PERIOD_CHOICES,
    )


@router.get("/report.pdf", response_model=None)
def report_pdf(
    user: CurrentUser, db: DbSession, days: str | None = None
) -> Response | RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    data = build_analytics(db, user, days=parse_days(days), now=datetime.now(UTC))
    pdf = build_report(
        data,
        name=user.display_name,
        clinician_contact=user.settings.clinician_contact,
        generated_on=data.last_day,
    )
    filename = f"glucobalance-report-{data.last_day.isoformat()}-{data.days}d.pdf"
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
