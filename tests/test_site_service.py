"""Site rotation for pump and pen users: suggestions, logging, blocked sites and weights."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.entries import EntryError
from glucobalance.features import feature_flags
from glucobalance.models import DeliveryMode, MonitoringMode, SitePurpose, User, UserSettings
from glucobalance.site_service import (
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
from glucobalance.sitemap import SITES, seed_body_sites

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
INFUSION = SitePurpose.INFUSION_SET
RAPID = SitePurpose.RAPID_INJECTION
LONG = SitePurpose.LONG_INJECTION
A = "abdomen-front-left-upper"
B = "abdomen-front-right-upper"


def make_user(session: Session, delivery: DeliveryMode) -> User:
    seed_body_sites(session)
    user = register(session, "ann@example.com", "Ann", "correct horse battery")
    session.add(
        UserSettings(
            user=user,
            delivery_mode=delivery,
            monitoring_mode=MonitoringMode.GLUCOMETER,
            max_bolus_units=Decimal("10"),
        )
    )
    session.flush()
    return user


@pytest.fixture
def pump_user(session: Session) -> User:
    return make_user(session, DeliveryMode.PUMP)


@pytest.fixture
def pen_user(session: Session) -> User:
    return make_user(session, DeliveryMode.PENS)


def test_pump_users_rotate_infusion_sets() -> None:
    assert purposes_for(feature_flags(DeliveryMode.PUMP, MonitoringMode.CGM)) == [INFUSION]


def test_pen_users_rotate_rapid_and_long_acting_separately() -> None:
    assert purposes_for(feature_flags(DeliveryMode.PENS, MonitoringMode.CGM)) == [RAPID, LONG]


def test_settings_default_to_a_14_day_rest_and_3_day_set_change(pump_user: User) -> None:
    assert pump_user.settings is not None
    assert pump_user.settings.site_rest_days == 14
    assert pump_user.settings.set_change_days == 3


def test_a_new_user_gets_every_site_suggested(pump_user: User, session: Session) -> None:
    ranked = suggestions(session, pump_user, INFUSION, now=NOW)
    assert sorted(ranked) == sorted(site.code for site in SITES)


def test_a_used_site_moves_to_the_back(pump_user: User, session: Session) -> None:
    log_site_use(session, pump_user, A, INFUSION, now=NOW)

    ranked = suggestions(session, pump_user, INFUSION, now=NOW)
    assert ranked[-1] == A


def test_the_suggestion_follows_the_last_use(pump_user: User, session: Session) -> None:
    first = suggestions(session, pump_user, INFUSION, now=NOW)[0]
    log_site_use(session, pump_user, first, INFUSION, now=NOW)

    assert suggestions(session, pump_user, INFUSION, now=NOW)[0] != first


def test_rapid_and_long_acting_rotations_are_independent(pen_user: User, session: Session) -> None:
    log_site_use(session, pen_user, A, RAPID, now=NOW)

    assert suggestions(session, pen_user, RAPID, now=NOW)[-1] == A
    assert suggestions(session, pen_user, LONG, now=NOW)[-1] != A


def test_logging_an_unknown_site_is_refused(pump_user: User, session: Session) -> None:
    with pytest.raises(SiteError, match="Unknown site"):
        log_site_use(session, pump_user, "elbow", INFUSION, now=NOW)


def test_logging_a_purpose_of_the_other_mode_is_refused(pump_user: User, session: Session) -> None:
    with pytest.raises(SiteError, match="does not match"):
        log_site_use(session, pump_user, A, RAPID, now=NOW)


def test_logging_needs_settings(session: Session) -> None:
    seed_body_sites(session)
    user = register(session, "bob@example.com", "Bob", "correct horse battery")
    with pytest.raises(SiteError, match="settings"):
        log_site_use(session, user, A, INFUSION, now=NOW)


def test_logging_in_the_future_is_refused(pump_user: User, session: Session) -> None:
    with pytest.raises(EntryError):
        log_site_use(session, pump_user, A, INFUSION, now=NOW, used_at=NOW + timedelta(hours=1))


def test_logging_an_earlier_time_is_allowed(pump_user: User, session: Session) -> None:
    use = log_site_use(session, pump_user, A, INFUSION, now=NOW, used_at=NOW - timedelta(hours=5))
    assert use.used_at == NOW - timedelta(hours=5)


def test_a_blocked_site_is_not_suggested(pen_user: User, session: Session) -> None:
    block_site(session, pen_user, A, now=NOW, until=None, reason="lump")

    assert A not in suggestions(session, pen_user, RAPID, now=NOW)
    assert A not in suggestions(session, pen_user, LONG, now=NOW)


def test_a_blocked_site_cannot_be_logged(pen_user: User, session: Session) -> None:
    block_site(session, pen_user, A, now=NOW, until=None, reason=None)
    with pytest.raises(SiteError, match="not available"):
        log_site_use(session, pen_user, A, RAPID, now=NOW)


def test_a_block_ends_on_its_end_date(pen_user: User, session: Session) -> None:
    until = NOW + timedelta(days=2)
    block_site(session, pen_user, A, now=NOW, until=until, reason="bruise")

    assert A not in suggestions(session, pen_user, RAPID, now=until - timedelta(minutes=1))
    assert A in suggestions(session, pen_user, RAPID, now=until)


def test_a_block_must_end_in_the_future(pen_user: User, session: Session) -> None:
    with pytest.raises(SiteError, match="future"):
        block_site(session, pen_user, A, now=NOW, until=NOW, reason=None)


def test_blocking_again_replaces_the_end_date(pen_user: User, session: Session) -> None:
    block_site(session, pen_user, A, now=NOW, until=NOW + timedelta(days=2), reason=None)
    block_site(session, pen_user, A, now=NOW, until=None, reason="scar")

    blocks = blocked_sites(session, pen_user, now=NOW)
    assert [(b.site.code, b.until, b.reason) for b in blocks] == [(A, None, "scar")]


def test_a_long_reason_is_refused(pen_user: User, session: Session) -> None:
    with pytest.raises(SiteError, match="100"):
        block_site(session, pen_user, A, now=NOW, until=None, reason="x" * 101)


def test_unblocking_makes_the_site_available_again(pen_user: User, session: Session) -> None:
    block_site(session, pen_user, A, now=NOW, until=None, reason=None)
    unblock_site(session, pen_user, A, now=NOW)

    assert blocked_sites(session, pen_user, now=NOW) == []
    assert A in suggestions(session, pen_user, RAPID, now=NOW)


def test_blocked_sites_lists_only_current_blocks(pen_user: User, session: Session) -> None:
    block_site(session, pen_user, A, now=NOW, until=NOW + timedelta(days=1), reason=None)
    block_site(session, pen_user, B, now=NOW, until=None, reason=None)

    later = NOW + timedelta(days=2)
    assert [b.site.code for b in blocked_sites(session, pen_user, now=later)] == [B]


def test_a_higher_weight_moves_a_site_up(pump_user: User, session: Session) -> None:
    for code in (A, B):
        log_site_use(session, pump_user, code, INFUSION, now=NOW - timedelta(days=20))
    set_weight(session, pump_user, B, Decimal("2"))

    ranked = suggestions(session, pump_user, INFUSION, now=NOW)
    assert ranked.index(B) < ranked.index(A)


def test_weight_zero_means_never_suggest(pump_user: User, session: Session) -> None:
    set_weight(session, pump_user, A, Decimal("0"))
    assert A not in suggestions(session, pump_user, INFUSION, now=NOW)


def test_setting_a_weight_twice_keeps_the_last_one(pump_user: User, session: Session) -> None:
    set_weight(session, pump_user, A, Decimal("0"))
    set_weight(session, pump_user, A, Decimal("1"))
    assert A in suggestions(session, pump_user, INFUSION, now=NOW)


@pytest.mark.parametrize("weight", ["-0.5", "2.5"])
def test_a_weight_outside_0_to_2_is_refused(pump_user: User, session: Session, weight: str) -> None:
    with pytest.raises(SiteError, match="0 and 2"):
        set_weight(session, pump_user, A, Decimal(weight))


def test_set_change_status_without_a_change(pump_user: User, session: Session) -> None:
    status = set_change_status(session, pump_user, now=NOW)
    assert status.last_change is None
    assert status.next_due is None
    assert status.days_left is None
    assert status.overdue is False


@pytest.mark.parametrize(
    ("days_ago", "days_left", "overdue"),
    [(0, 3, False), (1, 2, False), (2.5, 1, False), (3, 0, True), (4, 0, True)],
)
def test_days_until_the_next_set_change(
    pump_user: User, session: Session, days_ago: float, days_left: int, overdue: bool
) -> None:
    changed = NOW - timedelta(days=days_ago)
    log_site_use(session, pump_user, A, INFUSION, now=NOW, used_at=changed)

    status = set_change_status(session, pump_user, now=NOW)
    assert status.last_change == changed
    assert status.next_due == changed + timedelta(days=3)
    assert (status.days_left, status.overdue) == (days_left, overdue)


def test_the_set_change_interval_comes_from_settings(pump_user: User, session: Session) -> None:
    assert pump_user.settings is not None
    pump_user.settings.set_change_days = 2
    log_site_use(session, pump_user, A, INFUSION, now=NOW, used_at=NOW - timedelta(days=1))

    assert set_change_status(session, pump_user, now=NOW).days_left == 1
