"""The site rotation page: next site to use, skip, log a use, block a site, set weights."""

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.bodymap import (
    FIGURE_CENTRE,
    VIEW_HEIGHT,
    VIEW_WIDTH,
    heat_level,
    usage_counts,
    zone_box,
)
from glucobalance.entries import EntryError
from glucobalance.features import feature_flags
from glucobalance.models import BodyView, SitePurpose, User, UserSettings
from glucobalance.repositories import SiteRepository
from glucobalance.site_service import (
    PURPOSE_LABELS,
    SiteError,
    block_site,
    blocked_sites,
    log_site_use,
    purposes_for,
    set_change_status,
    set_weight,
    suggestions,
    unblock_site,
)
from glucobalance.sitemap import SITES, site_label
from glucobalance.timeline import day_bounds
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.rendering import render

router = APIRouter(prefix="/sites")

HEAT_DAYS = 30
WEIGHTS = {"0": "Avoid", "0.5": "Less often", "1": "Normal", "1.5": "More often", "2": "Prefer"}


def _now() -> datetime:
    return datetime.now(UTC)


def _skip(raw: str | None) -> int:
    try:
        return max(0, int(raw or "0"))
    except ValueError:
        return 0


def _page(
    request: Request,
    templates: Templates,
    db: DbSession,
    user: User,
    settings: UserSettings,
    *,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    now = _now()
    zone = ZoneInfo(settings.timezone)
    flags = feature_flags(settings.delivery_mode, settings.monitoring_mode)
    rotations: list[dict[str, Any]] = []
    for purpose in purposes_for(flags):
        ranked = suggestions(db, user, purpose, now=now)
        skip = _skip(request.query_params.get(f"skip_{purpose.value}"))
        current = ranked[skip % len(ranked)] if ranked else None
        rotations.append(
            {
                "purpose": purpose.value,
                "label": PURPOSE_LABELS[purpose],
                "code": current,
                "site": site_label(current) if current else None,
                "next_skip": skip + 1,
                "can_skip": len(ranked) > 1,
            }
        )
    set_change = None
    if SitePurpose.INFUSION_SET in purposes_for(flags):
        set_change = set_change_status(db, user, now=now)
    blocks = [
        {
            "code": b.site.code,
            "site": site_label(b.site.code),
            "until": b.until.astimezone(zone) if b.until else None,
            "reason": b.reason,
        }
        for b in blocked_sites(db, user, now=now)
    ]
    weights = _weights(db, user)
    counts = usage_counts(db, user, now=now, days=HEAT_DAYS)
    most = max(counts.values(), default=0)
    blocked = {b["code"] for b in blocks}
    suggested = {r["code"] for r in rotations if r["code"]}
    zones: list[dict[str, Any]] = []
    for site in SITES:
        box = zone_box(site)
        zones.append(
            {
                "code": site.code,
                "label": site.label,
                "x": box.x,
                "y": box.y,
                "width": box.width,
                "height": box.height,
                "count": counts.get(site.code, 0),
                "heat": heat_level(counts.get(site.code, 0), most),
                "blocked": site.code in blocked,
                "suggested": site.code in suggested,
            }
        )
    body_map = {
        "width": VIEW_WIDTH,
        "height": VIEW_HEIGHT,
        "days": HEAT_DAYS,
        "figures": [(view.value.capitalize(), FIGURE_CENTRE[view]) for view in BodyView],
        "zones": zones,
    }
    return render(
        request,
        templates,
        "sites.html",
        user,
        status_code=status_code,
        rotations=rotations,
        set_change=set_change,
        set_change_days=settings.set_change_days,
        blocks=blocks,
        sites=[(site.code, site.label) for site in SITES],
        weights=weights,
        weight_options=WEIGHTS,
        body_map=body_map,
        error=error,
    )


def _weights(db: DbSession, user: User) -> dict[str, str]:
    """The user's preference per site code, as the option values of ``WEIGHTS``."""
    return {
        pref.site.code: format(pref.weight.normalize(), "f")
        for pref in SiteRepository(db).weights(user.id).values()
    }


@router.get("", response_model=None)
def sites_page(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    if user.settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    return _page(request, templates, db, user, user.settings)


@router.get("/zone/{code}", response_model=None)
def zone_panel(
    code: str, request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    """What can be done with one zone: a panel for HTMX, or a whole page without JavaScript."""
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    spec = next((site for site in SITES if site.code == code), None)
    if spec is None:
        raise HTTPException(status_code=404)
    now = _now()
    zone = ZoneInfo(settings.timezone)
    flags = feature_flags(settings.delivery_mode, settings.monitoring_mode)
    block = next((b for b in blocked_sites(db, user, now=now) if b.site.code == code), None)
    panel = {
        "code": code,
        "label": spec.label,
        "count": usage_counts(db, user, now=now, days=HEAT_DAYS).get(code, 0),
        "purposes": [(p.value, PURPOSE_LABELS[p]) for p in purposes_for(flags)],
        "weight": _weights(db, user).get(code, "1"),
        "block": {
            "until": block.until.astimezone(zone) if block.until else None,
            "reason": block.reason,
        }
        if block
        else None,
    }
    name = "_site_zone.html" if request.headers.get("HX-Request") else "sites_zone.html"
    return render(
        request,
        templates,
        name,
        user,
        zone=panel,
        days=HEAT_DAYS,
        weight_options=WEIGHTS,
    )


async def _form(request: Request) -> dict[str, str]:
    return {k: str(v) for k, v in (await request.form()).items()}


def _purpose(raw: str) -> SitePurpose:
    try:
        return SitePurpose(raw)
    except ValueError:
        raise SiteError("Unknown rotation.") from None


def _until(raw: str, zone: ZoneInfo) -> datetime | None:
    """The end of the chosen local day, in UTC; empty means the block has no end date."""
    if not raw.strip():
        return None
    try:
        day = date.fromisoformat(raw.strip())
    except ValueError:
        raise SiteError("Enter the end date as a date, for example 2026-10-20.") from None
    return day_bounds(day, zone)[1]


def _weight(raw: str) -> Decimal:
    try:
        return Decimal(raw.strip())
    except InvalidOperation:
        raise SiteError("Choose a weight between 0 and 2.") from None


@router.post("/use", response_model=None)
async def use_site(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = await _form(request)
    try:
        use = log_site_use(
            db, user, form.get("code", ""), _purpose(form.get("purpose", "")), now=_now()
        )
    except EntryError as error:
        db.rollback()
        return _page(request, templates, db, user, settings, error=str(error), status_code=422)
    db.commit()
    request.session["flash"] = (
        f"Logged {PURPOSE_LABELS[use.purpose].lower()} at {site_label(use.site.code)}."
    )
    return RedirectResponse("/sites", status_code=303)


@router.post("/block", response_model=None)
async def block(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = await _form(request)
    code = form.get("code", "")
    try:
        until = _until(form.get("until", ""), ZoneInfo(settings.timezone))
        block_site(db, user, code, now=_now(), until=until, reason=form.get("reason"))
    except SiteError as error:
        db.rollback()
        return _page(request, templates, db, user, settings, error=str(error), status_code=422)
    db.commit()
    request.session["flash"] = f"{site_label(code)} is marked not available."
    return RedirectResponse("/sites", status_code=303)


@router.post("/unblock", response_model=None)
async def unblock(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    code = (await _form(request)).get("code", "")
    try:
        unblock_site(db, user, code, now=_now())
    except SiteError as error:
        db.rollback()
        return _page(request, templates, db, user, settings, error=str(error), status_code=422)
    db.commit()
    request.session["flash"] = f"{site_label(code)} is available again."
    return RedirectResponse("/sites", status_code=303)


@router.post("/weight", response_model=None)
async def weight(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = await _form(request)
    code = form.get("code", "")
    try:
        set_weight(db, user, code, _weight(form.get("weight", "")))
    except SiteError as error:
        db.rollback()
        return _page(request, templates, db, user, settings, error=str(error), status_code=422)
    db.commit()
    request.session["flash"] = f"Saved the preference for {site_label(code)}."
    return RedirectResponse("/sites", status_code=303)
