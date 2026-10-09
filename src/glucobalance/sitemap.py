"""The body map: every site a user can inject, infuse or place a device on.

The list is reference data shared by all users. ``SITES`` is the single source for the database
rows (``seed_body_sites`` and the migration that loads them) and for the SVG body map, so a site
is added or removed in one place only.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from glucobalance.models.sites import BodySide, BodySite, BodyView, SiteRegion
from glucobalance.repositories import SiteRepository


@dataclass(frozen=True, slots=True)
class SiteSpec:
    """One sub-zone of the body, for example the upper left abdomen."""

    region: SiteRegion
    view: BodyView
    side: BodySide
    zone: str

    @property
    def code(self) -> str:
        return f"{self.region}-{self.view}-{self.side}-{self.zone}"


# Each region is listed once, for the left side; the right side mirrors it.
_ZONES: tuple[tuple[SiteRegion, BodyView, tuple[str, ...]], ...] = (
    (SiteRegion.ABDOMEN, BodyView.FRONT, ("upper", "lower", "flank")),
    (SiteRegion.THIGH, BodyView.FRONT, ("upper", "lower")),
    (SiteRegion.THIGH, BodyView.BACK, ("upper", "lower")),
    (SiteRegion.ARM, BodyView.FRONT, ("upper",)),
    (SiteRegion.ARM, BodyView.BACK, ("upper", "lower")),
    (SiteRegion.BUTTOCK, BodyView.BACK, ("upper", "lower")),
)

SITES: tuple[SiteSpec, ...] = tuple(
    SiteSpec(region, view, side, zone)
    for side in BodySide
    for region, view, zones in _ZONES
    for zone in zones
)


def seed_body_sites(session: Session) -> None:
    """Insert the sites that are missing. Safe to run any number of times."""
    repo = SiteRepository(session)
    existing = {site.code for site in repo.all()}
    for spec in SITES:
        if spec.code not in existing:
            repo.add(
                BodySite(
                    code=spec.code,
                    region=spec.region,
                    side=spec.side,
                    view=spec.view,
                    zone=spec.zone,
                )
            )
