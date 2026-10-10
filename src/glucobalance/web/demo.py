"""One-click demo logins for the two synthetic demo accounts (only when GBA_DEMO_MODE is on)."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from glucobalance.demo_data import PENS_EMAIL, PUMP_EMAIL, seed_pens_user, seed_pump_user
from glucobalance.repositories import UserRepository
from glucobalance.web.deps import SESSION_USER_KEY, DbSession

router = APIRouter()

DEMO_KINDS = {"pump": PUMP_EMAIL, "pens": PENS_EMAIL}


@router.post("/demo/{kind}", response_model=None)
def demo_login(kind: Literal["pump", "pens"], request: Request, db: DbSession) -> RedirectResponse:
    """Log in as a demo user, building its synthetic data on first use."""
    if not request.app.state.settings.demo_mode:
        raise HTTPException(status_code=404)
    user = UserRepository(db).get_by_email(DEMO_KINDS[kind])
    if user is None:
        now = datetime.now(UTC)
        user = seed_pump_user(db, end=now) if kind == "pump" else seed_pens_user(db, end=now)
        db.commit()
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    return RedirectResponse("/", status_code=303)
