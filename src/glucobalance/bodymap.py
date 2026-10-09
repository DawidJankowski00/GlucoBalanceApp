"""Drawing the body map: one rectangle per zone, and a heat level from recent use.

The map is a plain SVG built from ``sitemap.SITES``, so adding a zone there needs one row in
``_LAYOUT`` here. Front and back are drawn side by side, as if looking at the person: from the
front, their left is on your right; from behind, it is on your left.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from glucobalance.models import BodySide, BodyView, SiteRegion, User
from glucobalance.repositories import SiteRepository
from glucobalance.sitemap import SiteSpec

VIEW_WIDTH = 400
VIEW_HEIGHT = 260
HEAT_LEVELS = 4
FIGURE_CENTRE = {BodyView.FRONT: 100, BodyView.BACK: 300}


@dataclass(frozen=True, slots=True)
class Box:
    x: int
    y: int
    width: int
    height: int


# (region, view, zone) -> (inner, outer, top, bottom): distances from the figure's centre line
# and from the top of the drawing.
_LAYOUT: dict[tuple[SiteRegion, BodyView, str], tuple[int, int, int, int]] = {
    (SiteRegion.ABDOMEN, BodyView.FRONT, "upper"): (4, 28, 88, 112),
    (SiteRegion.ABDOMEN, BodyView.FRONT, "lower"): (4, 28, 112, 136),
    (SiteRegion.ABDOMEN, BodyView.FRONT, "flank"): (28, 38, 88, 136),
    (SiteRegion.ARM, BodyView.FRONT, "upper"): (46, 60, 62, 104),
    (SiteRegion.THIGH, BodyView.FRONT, "upper"): (4, 30, 154, 192),
    (SiteRegion.THIGH, BodyView.FRONT, "lower"): (4, 30, 192, 230),
    (SiteRegion.ARM, BodyView.BACK, "upper"): (46, 60, 62, 100),
    (SiteRegion.ARM, BodyView.BACK, "lower"): (46, 60, 100, 138),
    (SiteRegion.BUTTOCK, BodyView.BACK, "upper"): (4, 34, 128, 148),
    (SiteRegion.BUTTOCK, BodyView.BACK, "lower"): (4, 34, 148, 168),
    (SiteRegion.THIGH, BodyView.BACK, "upper"): (4, 30, 172, 206),
    (SiteRegion.THIGH, BodyView.BACK, "lower"): (4, 30, 206, 240),
}


def _drawn_on_right(side: BodySide, view: BodyView) -> bool:
    return (side is BodySide.LEFT) == (view is BodyView.FRONT)


def zone_box(site: SiteSpec) -> Box:
    """Where to draw a zone in the SVG (viewBox ``0 0 VIEW_WIDTH VIEW_HEIGHT``)."""
    inner, outer, top, bottom = _LAYOUT[(site.region, site.view, site.zone)]
    centre = FIGURE_CENTRE[site.view]
    x = centre + inner if _drawn_on_right(site.side, site.view) else centre - outer
    return Box(x=x, y=top, width=outer - inner, height=bottom - top)


def heat_level(count: int, most: int) -> int:
    """0 for an unused site, up to ``HEAT_LEVELS`` for the most used one."""
    if count <= 0 or most <= 0:
        return 0
    return min(HEAT_LEVELS, math.ceil(HEAT_LEVELS * count / most))


def usage_counts(session: Session, user: User, *, now: datetime, days: int) -> dict[str, int]:
    """How often each site was used, any purpose, in the ``days`` up to ``now``."""
    start = now - timedelta(days=days)
    return SiteRepository(session).use_counts(user.id, start, now + timedelta(microseconds=1))
