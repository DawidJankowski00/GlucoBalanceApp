"""The onboarding wizard: three steps that end by saving the user's first settings.

Answers collect in the signed session cookie (``draft``) until the last step, so nothing is
saved half-finished.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.models import ChangeSource, DisplayUnit
from glucobalance.settings_service import SettingsError, apply_settings, is_valid_timezone
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.forms import BLOCK_ROWS, parse_choices, parse_settings
from glucobalance.web.rendering import render

router = APIRouter(prefix="/onboarding")

DRAFT_KEY = "onboarding_draft"
LAST_STEP = 3
STEP_FIELDS: dict[int, tuple[str, ...]] = {
    1: ("delivery_mode", "monitoring_mode", "display_unit", "timezone"),
    2: (
        "target_low",
        "target_high",
        "insulin_action_hours",
        "max_bolus_units",
        "dose_step_units",
        "clinician_contact",
    ),
    3: tuple(
        f"block_{part}_{row}" for row in range(BLOCK_ROWS) for part in ("start", "icr", "isf")
    ),
}
DEFAULTS = {
    DisplayUnit.MGDL.value: {"target_low": "70", "target_high": "180", "block_isf_0": "40"},
    DisplayUnit.MMOLL.value: {"target_low": "3.9", "target_high": "10.0", "block_isf_0": "2.2"},
}


def _draft(request: Request) -> dict[str, str]:
    draft: dict[str, str] = request.session.get(DRAFT_KEY, {})
    return draft


def _step_page(
    request: Request,
    templates: Templates,
    user: CurrentUser,
    step: int,
    values: dict[str, str],
    **extra: Any,
) -> HTMLResponse:
    unit = values.get("display_unit", DisplayUnit.MGDL.value)
    shown = {**DEFAULTS.get(unit, DEFAULTS["mg/dL"]), "dose_step_units": "0.5", **values}
    shown.setdefault("block_start_0", "00:00")
    shown.setdefault("block_icr_0", "10")
    return render(
        request,
        templates,
        f"onboarding/step{step}.html",
        user,
        step=step,
        steps=LAST_STEP,
        values=shown,
        rows=range(BLOCK_ROWS),
        **extra,
    )


@router.get("", response_model=None)
def start(user: CurrentUser) -> RedirectResponse:
    return RedirectResponse("/" if user.settings else "/onboarding/1", status_code=303)


@router.get("/{step}", response_model=None)
def show_step(
    step: int, request: Request, user: CurrentUser, templates: Templates
) -> HTMLResponse | RedirectResponse:
    if user.settings is not None or step not in STEP_FIELDS:
        return RedirectResponse("/", status_code=303)
    return _step_page(request, templates, user, step, _draft(request))


@router.post("/{step}", response_model=None)
async def submit_step(
    step: int, request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    if user.settings is not None or step not in STEP_FIELDS:
        return RedirectResponse("/", status_code=303)

    posted = {k: str(v) for k, v in (await request.form()).items() if k in STEP_FIELDS[step]}
    draft = _draft(request)
    if step == 1 and posted.get("display_unit") != draft.get("display_unit"):
        # Values typed in another unit would be misread, so later steps start fresh.
        draft = {}
    draft = {**draft, **posted}
    if step == 1 and not is_valid_timezone(draft.get("timezone", "")):
        # The browser fills this in; without a usable answer start from UTC, editable later.
        draft["timezone"] = "UTC"

    try:
        if step == 1:
            parse_choices(draft)
        else:
            data = parse_settings(draft, require_blocks=step == LAST_STEP)
            if step == LAST_STEP:
                apply_settings(db, user, data, ChangeSource.ONBOARDING, user)
                db.commit()
                request.session.pop(DRAFT_KEY, None)
                request.session["flash"] = "You're all set. Settings saved."
                return RedirectResponse("/", status_code=303)
    except SettingsError as error:
        return _step_page(request, templates, user, step, draft, error=str(error))

    request.session[DRAFT_KEY] = draft
    return RedirectResponse(f"/onboarding/{step + 1}", status_code=303)
