"""Web Push endpoints used by the reminders page, and the service worker script."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from glucobalance.models import Notification
from glucobalance.push import deliver, subscribe, subscriptions_for, unsubscribe
from glucobalance.reminder_service import ReminderError
from glucobalance.web.deps import CurrentUser, DbSession
from glucobalance.web.rendering import STATIC_DIR

router = APIRouter()


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=422)


@router.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    """The service worker must be served from the site root so it can show notifications."""
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/push/status")
def push_status(request: Request, user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Whether the server can send pushes, the public key the browser needs, and device count."""
    settings = request.app.state.settings
    return {
        "enabled": settings.push_enabled,
        "key": settings.vapid_public_key if settings.push_enabled else None,
        "devices": len(subscriptions_for(db, user)),
    }


@router.post("/push/subscribe", response_model=None)
async def push_subscribe(request: Request, user: CurrentUser, db: DbSession) -> Response:
    body = await _json(request)
    keys = body.get("keys")
    keys = keys if isinstance(keys, dict) else {}
    try:
        subscribe(
            db,
            user,
            endpoint=str(body.get("endpoint", "")),
            p256dh=str(keys.get("p256dh", "")),
            auth=str(keys.get("auth", "")),
            now=datetime.now(UTC),
        )
    except ReminderError as error:
        db.rollback()
        return _error(str(error))
    db.commit()
    return Response(status_code=204)


@router.post("/push/unsubscribe", response_model=None)
async def push_unsubscribe(request: Request, user: CurrentUser, db: DbSession) -> Response:
    body = await _json(request)
    unsubscribe(db, user, str(body.get("endpoint", "")))
    db.commit()
    return Response(status_code=204)


@router.post("/push/test", response_model=None)
def push_test(request: Request, user: CurrentUser, db: DbSession) -> JSONResponse:
    """Send a test message to this user's devices. Nothing is added to the notification centre."""
    sender = request.app.state.push_sender
    if sender is None:
        return _error("Phone notifications are not set up on this server.")
    message = Notification(
        user_id=user.id,
        title="GlucoBalanceApp",
        body="Notifications are working.",
        created_at=datetime.now(UTC),
    )
    sent = deliver(db, [message], sender)
    db.commit()  # removes devices the push service reported as gone
    return JSONResponse({"sent": sent})
