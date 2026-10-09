"""The reminders page (rules, quiet hours) and the notification centre."""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from glucobalance.models import ReminderKind, RuleType, User, UserSettings
from glucobalance.reminder_service import (
    ReminderError,
    ReminderInput,
    create_reminder,
    delete_reminder,
    ensure_default_reminders,
    list_notifications,
    list_reminders,
    mark_all_read,
    mark_done,
    mark_read,
    quiet_hours_for,
    set_active,
    set_quiet_hours,
    snooze,
)
from glucobalance.web.deps import CurrentUser, DbSession, Templates
from glucobalance.web.rendering import render

router = APIRouter()

SNOOZE_CHOICES = {15: "15 min", 60: "1 hour", 180: "3 hours"}
RULE_LABELS = {
    RuleType.EVERY_N_DAYS: "Every N days",
    RuleType.DAILY_AT: "Every day at a time",
}
KIND_LABELS = {
    ReminderKind.SET_CHANGE: "Infusion set",
    ReminderKind.RESERVOIR: "Reservoir",
    ReminderKind.LONG_ACTING_DOSE: "Long-acting dose",
    ReminderKind.MISSED_DOSE: "Missed dose",
    ReminderKind.PEN_NEEDLE: "Pen needles",
    ReminderKind.PEN_EXPIRY: "Pen expiry",
    ReminderKind.GLUCOSE_CHECK: "Glucose check",
    ReminderKind.SENSOR_CHANGE: "CGM sensor",
    ReminderKind.HYPO_RECHECK: "Recheck after a low",
    ReminderKind.CUSTOM: "Custom",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_time(raw: str) -> time | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return time.fromisoformat(raw)
    except ValueError:
        raise ReminderError("Enter the time as HH:MM.") from None


def _parse_int(raw: str, message: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ReminderError(message) from None


def _describe(
    reminder_rule: RuleType, interval: int | None, at: time | None, delay: int | None
) -> str:
    if reminder_rule is RuleType.EVERY_N_DAYS:
        return f"every {interval} day{'s' if interval != 1 else ''}"
    if reminder_rule is RuleType.DAILY_AT and at is not None:
        return f"every day at {at:%H:%M}"
    return f"{delay} minutes after the event"


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
    quiet = quiet_hours_for(settings)
    rows = []
    for r in list_reminders(db, user):
        due = r.next_due_at.astimezone(zone) if r.next_due_at else None
        snoozed = (
            r.snoozed_until.astimezone(zone) if r.snoozed_until and r.snoozed_until > now else None
        )
        rows.append(
            {
                "id": r.id,
                "title": r.title,
                "kind": KIND_LABELS[r.kind],
                "rule": _describe(r.rule_type, r.interval_days, r.time_of_day, r.delay_minutes),
                "due": due,
                "snoozed": snoozed,
                "active": r.active,
                "overdue": bool(r.active and r.next_due_at and r.next_due_at <= now),
                "custom": r.kind is ReminderKind.CUSTOM,
            }
        )
    return render(
        request,
        templates,
        "reminders.html",
        user,
        status_code=status_code,
        error=error,
        reminders=rows,
        snooze_choices=SNOOZE_CHOICES,
        rule_labels=RULE_LABELS,
        quiet_start=f"{quiet.start:%H:%M}" if quiet else "",
        quiet_end=f"{quiet.end:%H:%M}" if quiet else "",
    )


@router.get("/reminders", response_model=None)
def reminders_page(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    # Accounts that finished setup before reminders existed get their defaults here.
    if ensure_default_reminders(db, user, now=_now()):
        db.commit()
    return _page(request, templates, db, user, settings)


async def _form(request: Request) -> dict[str, str]:
    return {k: str(v) for k, v in (await request.form()).items()}


def _done(request: Request, db: DbSession, message: str) -> RedirectResponse:
    db.commit()
    request.session["flash"] = message
    return RedirectResponse("/reminders", status_code=303)


@router.post("/reminders", response_model=None)
async def add_reminder(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = await _form(request)
    try:
        rule = RuleType(form.get("rule_type", ""))
        if rule is RuleType.AFTER_EVENT:
            raise ValueError
        create_reminder(
            db,
            user,
            ReminderInput(
                kind=ReminderKind.CUSTOM,
                title=form.get("title", ""),
                rule_type=rule,
                interval_days=_parse_int(
                    form.get("interval_days", ""), "Enter the days as a number."
                ),
                time_of_day=_parse_time(form.get("time_of_day", "")),
            ),
            now=_now(),
        )
    except ValueError as error:
        db.rollback()
        message = str(error) if isinstance(error, ReminderError) else "Choose how often."
        return _page(request, templates, db, user, settings, error=message, status_code=422)
    return _done(request, db, "Reminder added.")


@router.post("/reminders/quiet-hours", response_model=None)
async def save_quiet_hours(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = await _form(request)
    try:
        set_quiet_hours(
            db,
            user,
            _parse_time(form.get("quiet_start", "")),
            _parse_time(form.get("quiet_end", "")),
        )
    except ReminderError as error:
        db.rollback()
        return _page(request, templates, db, user, settings, error=str(error), status_code=422)
    return _done(request, db, "Quiet hours saved.")


@router.post("/reminders/{reminder_id}/{action}", response_model=None)
async def reminder_action(
    reminder_id: int,
    action: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    templates: Templates,
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    form = await _form(request)
    now = _now()
    try:
        match action:
            case "done":
                mark_done(db, user, reminder_id, now=now)
                message = "Marked as done."
            case "snooze":
                minutes = _parse_int(form.get("minutes", ""), "Choose how long to snooze.")
                snooze(db, user, reminder_id, minutes=minutes or 0, now=now)
                message = "Snoozed."
            case "on" | "off":
                set_active(db, user, reminder_id, action == "on", now=now)
                message = "Reminder switched on." if action == "on" else "Reminder switched off."
            case "delete":
                delete_reminder(db, user, reminder_id)
                message = "Reminder deleted."
            case _:
                return RedirectResponse("/reminders", status_code=303)
    except ReminderError as error:
        db.rollback()
        return _page(request, templates, db, user, settings, error=str(error), status_code=422)
    return _done(request, db, message)


@router.get("/notifications", response_model=None)
def notifications_page(
    request: Request, user: CurrentUser, db: DbSession, templates: Templates
) -> HTMLResponse | RedirectResponse:
    settings = user.settings
    if settings is None:
        return RedirectResponse("/onboarding/1", status_code=303)
    zone = ZoneInfo(settings.timezone)
    notes = [
        {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "when": n.created_at.astimezone(zone),
            "unread": n.read_at is None,
            "reminder_id": n.reminder_id,
        }
        for n in list_notifications(db, user)
    ]
    return render(request, templates, "notifications.html", user, notifications=notes)


@router.post("/notifications/read-all", response_model=None)
def read_all(user: CurrentUser, db: DbSession) -> RedirectResponse:
    mark_all_read(db, user, now=_now())
    db.commit()
    return RedirectResponse("/notifications", status_code=303)


@router.post("/notifications/{notification_id}/read", response_model=None)
def read_one(notification_id: int, user: CurrentUser, db: DbSession) -> RedirectResponse:
    try:
        mark_read(db, user, notification_id, now=_now())
    except ReminderError:
        db.rollback()
    else:
        db.commit()
    return RedirectResponse("/notifications", status_code=303)
