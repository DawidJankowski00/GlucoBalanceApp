"""The SVG body map: where each zone is drawn, and how usage turns into heat."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from glucobalance.accounts import register
from glucobalance.bodymap import FIGURE_CENTRE, Box, heat_level, usage_counts, zone_box
from glucobalance.models import (
    BodySide,
    BodyView,
    DeliveryMode,
    MonitoringMode,
    SitePurpose,
    User,
    UserSettings,
)
from glucobalance.site_service import log_site_use
from glucobalance.sitemap import SITES, SiteSpec, seed_body_sites

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
A = "abdomen-front-left-upper"
B = "thigh-front-right-lower"


def overlaps(a: Box, b: Box) -> bool:
    apart_x = a.x + a.width <= b.x or b.x + b.width <= a.x
    apart_y = a.y + a.height <= b.y or b.y + b.height <= a.y
    return not (apart_x or apart_y)


def test_every_site_has_a_box_with_a_size() -> None:
    for site in SITES:
        box = zone_box(site)
        assert box.width > 0 and box.height > 0, site.code


def test_zones_in_the_same_view_do_not_overlap() -> None:
    for view in BodyView:
        boxes = [(s.code, zone_box(s)) for s in SITES if s.view is view]
        for i, (code_a, a) in enumerate(boxes):
            for code_b, b in boxes[i + 1 :]:
                assert not overlaps(a, b), (code_a, code_b)


def test_front_and_back_are_drawn_side_by_side() -> None:
    front = [zone_box(s) for s in SITES if s.view is BodyView.FRONT]
    back = [zone_box(s) for s in SITES if s.view is BodyView.BACK]
    assert max(b.x + b.width for b in front) < min(b.x for b in back)


@pytest.mark.parametrize(
    ("view", "left_is_on_the_right"),
    [(BodyView.FRONT, True), (BodyView.BACK, False)],
)
def test_left_and_right_are_mirrored_like_looking_at_a_person(
    view: BodyView, left_is_on_the_right: bool
) -> None:
    """From the front you see the person's left on your right; from behind, on your left."""
    centre = FIGURE_CENTRE[view]
    for site in SITES:
        if site.view is not view:
            continue
        box = zone_box(site)
        mirror = zone_box(SiteSpec(site.region, site.view, BodySide.RIGHT, site.zone))
        assert box.y == mirror.y and box.width == mirror.width
        on_right = box.x >= centre
        if site.side is BodySide.LEFT:
            assert on_right is left_is_on_the_right, site.code
        else:
            assert on_right is not left_is_on_the_right, site.code


@pytest.mark.parametrize(
    ("count", "most", "level"),
    [(0, 0, 0), (0, 5, 0), (1, 1, 4), (1, 4, 1), (2, 4, 2), (3, 4, 3), (4, 4, 4), (1, 10, 1)],
)
def test_heat_level_scales_to_the_most_used_site(count: int, most: int, level: int) -> None:
    assert heat_level(count, most) == level


@pytest.fixture
def user(session: Session) -> User:
    seed_body_sites(session)
    user = register(session, "ann@example.com", "Ann", "correct horse battery")
    session.add(
        UserSettings(
            user=user,
            delivery_mode=DeliveryMode.PENS,
            monitoring_mode=MonitoringMode.GLUCOMETER,
            max_bolus_units=Decimal("10"),
        )
    )
    session.flush()
    return user


def test_usage_counts_every_rotation_in_the_window(user: User, session: Session) -> None:
    log_site_use(session, user, A, SitePurpose.RAPID_INJECTION, now=NOW)
    log_site_use(session, user, A, SitePurpose.LONG_INJECTION, now=NOW)
    two_days_ago = NOW - timedelta(days=2)
    log_site_use(session, user, B, SitePurpose.RAPID_INJECTION, now=NOW, used_at=two_days_ago)

    assert usage_counts(session, user, now=NOW, days=30) == {A: 2, B: 1}


def test_usage_outside_the_window_is_ignored(user: User, session: Session) -> None:
    long_ago = NOW - timedelta(days=29)
    log_site_use(session, user, A, SitePurpose.RAPID_INJECTION, now=NOW, used_at=long_ago)

    assert usage_counts(session, user, now=NOW, days=7) == {}
    assert usage_counts(session, user, now=NOW, days=30) == {A: 1}
