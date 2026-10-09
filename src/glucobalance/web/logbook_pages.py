"""The logbook page and its CSV export."""

from datetime import UTC, datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from glucobalance.logbook import (
    PAGE_SIZE,
    LogbookError,
    LogbookFilters,
    parse_filters,
    query_logbook,
    to_csv,
)
from glucobalance.timeline import EntryKind
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.log import TAG_LABELS
from glucobalance.web.rendering import render
from glucobalance.web.today import describe

router = APIRouter()


def _params(request: Request) -> dict[str, str]:
    """Query parameters as a plain dict; ``type`` may repeat (checkboxes) and is joined."""
    params = {k: v for k, v in request.query_params.items() if k != "type"}
    params["type"] = ",".join(request.query_params.getlist("type"))
    return params


def _query_string(filters: LogbookFilters, **extra: object) -> str:
    pairs: list[tuple[str, str]] = [
        ("start", filters.start.isoformat()),
        ("end", filters.end.isoformat()),
    ]
    if filters.kinds != frozenset(EntryKind):
        pairs += [("type", kind.value) for kind in EntryKind if kind in filters.kinds]
    if filters.tag:
        pairs.append(("tag", filters.tag.value))
    pairs += [(key, str(value)) for key, value in extra.items()]
    return urlencode(pairs)


@router.get("/logbook", response_model=None)
def logbook(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates, page: int = 1
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    zone = ZoneInfo(settings.timezone)
    today = datetime.now(UTC).astimezone(zone).date()
    error = None
    status_code = 200
    try:
        filters = parse_filters(_params(request), today)
    except LogbookError as problem:
        error, status_code = str(problem), 422
        filters = parse_filters({}, today)
    result = query_logbook(db, user.id, zone, filters, page=page)
    rows = [
        {
            "time": f"{item.at.astimezone(zone):%d %b %H:%M}",
            "kind": item.kind.value,
            **describe(item, settings),
        }
        for item in result.rows
    ]
    return render(
        request,
        templates,
        "logbook.html",
        user,
        status_code=status_code,
        error=error,
        filters=filters,
        rows=rows,
        page=result,
        page_size=PAGE_SIZE,
        kinds=EntryKind,
        tags=TAG_LABELS,
        selected_tag=filters.tag.value if filters.tag else "",
        csv_link=f"/logbook.csv?{_query_string(filters)}",
        previous_link=f"/logbook?{_query_string(filters, page=result.page - 1)}"
        if result.page > 1
        else None,
        next_link=f"/logbook?{_query_string(filters, page=result.page + 1)}"
        if result.page < result.pages
        else None,
    )


@router.get("/logbook.csv", response_model=None)
def logbook_csv(request: Request, user: CurrentUser, db: DbSession) -> Response | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    zone = ZoneInfo(settings.timezone)
    try:
        filters = parse_filters(_params(request), datetime.now(UTC).astimezone(zone).date())
    except LogbookError as problem:
        return PlainTextResponse(str(problem), status_code=422)
    result = query_logbook(db, user.id, zone, filters, page_size=None)
    name = f"glucobalance-logbook-{filters.start.isoformat()}-to-{filters.end.isoformat()}.csv"
    return Response(
        to_csv(result.rows, settings.display_unit, zone),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
