"""Site performance: average glucose after each site was used."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from glucobalance.models import (
    GlucoseReading,
    ReadingSource,
    SitePurpose,
    SiteUse,
    User,
)
from glucobalance.repositories import SiteRepository
from glucobalance.site_performance import SiteUseRecord, site_performance
from glucobalance.sitemap import seed_body_sites

T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
A = "abdomen-front-left-upper"
B = "thigh-front-right-upper"


def readings_after(start: datetime, value: int, *, hours: tuple[int, ...] = (2, 3, 4, 5)) -> list:  # type: ignore[type-arg]
    return [
        GlucoseReading(
            user_id=1,
            measured_at=start + timedelta(hours=h),
            value_mgdl=value,
            source=ReadingSource.CGM,
        )
        for h in hours
    ]


def use(day: int, code: str = A) -> SiteUseRecord:
    return SiteUseRecord(code, T0 + timedelta(days=day))


def test_the_mean_is_taken_from_two_to_six_hours_after_the_use() -> None:
    uses = [use(0)]
    readings = [
        *readings_after(T0, 100, hours=(1,)),  # too early
        *readings_after(T0, 150, hours=(2, 3, 5)),
        *readings_after(T0, 300, hours=(6, 7)),  # too late (the window ends before 6 hours)
    ]
    (row,) = site_performance(uses, readings)
    assert row.code == A
    assert row.mean_mgdl == 150
    assert row.uses == 1


def test_each_use_counts_equally() -> None:
    uses = [use(0), use(1)]
    readings = readings_after(use(0).used_at, 100) + readings_after(use(1).used_at, 200)[:3]
    (row,) = site_performance(uses, readings)
    assert row.mean_mgdl == 150  # (100 + 200) / 2, not weighted by the number of readings
    assert row.uses == 2


def test_a_use_with_too_few_readings_is_skipped() -> None:
    uses = [use(0)]
    assert site_performance(uses, readings_after(T0, 150, hours=(2, 3))) == []


def test_sites_are_sorted_with_the_highest_first() -> None:
    uses = [use(0, A), use(1, B)]
    readings = readings_after(use(0).used_at, 120) + readings_after(use(1).used_at, 190)
    rows = site_performance(uses, readings)
    assert [r.code for r in rows] == [B, A]


def test_a_site_well_above_the_overall_mean_is_flagged_once_used_enough() -> None:
    uses = [use(d, A) for d in (0, 1, 2)] + [use(d, B) for d in (3, 4, 5)]
    readings = [r for u in uses for r in readings_after(u.used_at, 200 if u.code == A else 120)]
    rows = {r.code: r for r in site_performance(uses, readings)}
    assert rows[A].difference_mgdl == 40  # overall mean is 160
    assert rows[A].flagged
    assert not rows[B].flagged


def test_a_site_used_only_twice_is_never_flagged() -> None:
    uses = [use(d, A) for d in (0, 1)] + [use(d, B) for d in (2, 3, 4)]
    readings = [r for u in uses for r in readings_after(u.used_at, 250 if u.code == A else 100)]
    rows = {r.code: r for r in site_performance(uses, readings)}
    assert not rows[A].flagged


def test_no_readings_give_no_rows() -> None:
    assert site_performance([use(0)], []) == []


def test_the_repository_lists_uses_with_their_site_codes(session: Session) -> None:
    seed_body_sites(session)
    user = User(email="a@example.com", display_name="Ann")
    session.add(user)
    session.flush()
    sites = SiteRepository(session)
    site = sites.get_by_code(A)
    assert site is not None
    for hours, purpose in ((0, SitePurpose.INFUSION_SET), (30, SitePurpose.CGM_SENSOR)):
        sites.add_use(
            SiteUse(
                user_id=user.id,
                site_id=site.id,
                used_at=T0 + timedelta(hours=hours),
                purpose=purpose,
            )
        )
    sites.add_use(
        SiteUse(
            user_id=user.id,
            site_id=site.id,
            used_at=T0 + timedelta(days=30),
            purpose=SitePurpose.INFUSION_SET,
        )
    )
    found = sites.uses_between(user.id, T0, T0 + timedelta(days=2))
    # the sensor is not insulin delivery, so it is left out; the use after the range is too
    assert found == [(A, T0)]
