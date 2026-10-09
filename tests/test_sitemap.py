"""The body map: which sites exist, how they are named, and loading them into the database."""

from sqlalchemy.orm import Session

from glucobalance.models.sites import BodySide, BodySite, BodyView, SiteRegion
from glucobalance.repositories import SiteRepository
from glucobalance.sitemap import SITES, SiteSpec, seed_body_sites, site_label


def test_codes_are_unique() -> None:
    codes = [site.code for site in SITES]
    assert len(codes) == len(set(codes))


def test_code_is_built_from_region_view_side_and_zone() -> None:
    site = SiteSpec(SiteRegion.ABDOMEN, BodyView.FRONT, BodySide.LEFT, "upper")
    assert site.code == "abdomen-front-left-upper"


def test_every_region_has_sites_on_both_sides() -> None:
    for region in SiteRegion:
        sides = {site.side for site in SITES if site.region == region}
        assert sides == {BodySide.LEFT, BodySide.RIGHT}, region


def test_both_views_are_used() -> None:
    assert {site.view for site in SITES} == {BodyView.FRONT, BodyView.BACK}


def test_the_map_is_left_right_symmetric() -> None:
    def shape(side: BodySide) -> set[tuple[SiteRegion, BodyView, str]]:
        return {(s.region, s.view, s.zone) for s in SITES if s.side == side}

    assert shape(BodySide.LEFT) == shape(BodySide.RIGHT)


def test_seed_creates_every_site(session: Session) -> None:
    seed_body_sites(session)

    stored = SiteRepository(session).all()
    assert {site.code for site in stored} == {site.code for site in SITES}


def test_seed_stores_region_side_view_and_zone(session: Session) -> None:
    seed_body_sites(session)

    site = SiteRepository(session).get_by_code("thigh-front-right-lower")
    assert site is not None
    assert (site.region, site.side, site.view, site.zone) == (
        SiteRegion.THIGH,
        BodySide.RIGHT,
        BodyView.FRONT,
        "lower",
    )


def test_seed_twice_does_not_duplicate(session: Session) -> None:
    seed_body_sites(session)
    seed_body_sites(session)

    assert len(SiteRepository(session).all()) == len(SITES)


def test_seed_leaves_existing_rows_alone(session: Session) -> None:
    seed_body_sites(session)
    first = session.query(BodySite).order_by(BodySite.id).first()
    assert first is not None
    first_id = first.id

    seed_body_sites(session)

    again = session.query(BodySite).order_by(BodySite.id).first()
    assert again is not None and again.id == first_id


def test_site_label_names_region_side_zone_and_view() -> None:
    assert site_label("abdomen-front-left-upper") == "Abdomen, left, upper (front)"


def test_an_unknown_code_is_its_own_label() -> None:
    assert site_label("elbow") == "elbow"
