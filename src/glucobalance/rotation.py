"""Site rotation: which body site to use next.

``rank_sites`` is a pure function: it reads only its arguments, touches no database and no
clock, so every rule can be tested with plain values. A service (later in Stage 4) gathers the
inputs and calls it.

THIS FILE IS FOR THE OWNER TO WRITE (PLAN.md rule 5). The types and the contract are fixed by
``tests/test_rotation.py``; the function bodies are still to be written.
"""

from dataclasses import dataclass
from datetime import datetime

# A site that was never used counts as this many days since last use.
NEVER_USED_DAYS = 365.0


@dataclass(frozen=True, slots=True)
class SiteState:
    """Everything the ranking needs to know about one site for one user."""

    code: str
    last_used: datetime | None
    blocked: bool = False
    weight: float = 1.0


def rank_sites(sites: list[SiteState], now: datetime, rest_days: int) -> list[str]:
    """Site codes, best first. Sites that must not be used are left out.

    Rules (each has a test in ``tests/test_rotation.py``):

    1. A blocked site is never returned.
    2. A site with weight 0 is never returned (the user wants to avoid it).
    3. A site is *rested* when it was never used, or last used at least ``rest_days`` days ago.
       Every rested site ranks above every site that is still resting.
    4. Within each group, the score is ``days since last use * weight`` (a never-used site counts
       as ``NEVER_USED_DAYS``). A higher score ranks first.
    5. Equal scores are ordered by site code, so the result is the same on every run.
    """
    candidates = [s for s in sites if not s.blocked and s.weight > 0]
    if not candidates:
        return []

    def sort_key(s: SiteState) -> tuple[int, float, str]:
        if s.last_used is None:
            days_since = NEVER_USED_DAYS
            is_rested = True
        else:
            days_since = (now - s.last_used).total_seconds() / 86400.0
            is_rested = days_since >= rest_days

        score = days_since * s.weight

        return (0 if is_rested else 1, -score, s.code)

    return [s.code for s in sorted(candidates, key=sort_key)]


def suggest_site(sites: list[SiteState], now: datetime, rest_days: int) -> str | None:
    ranked = rank_sites(sites, now, rest_days)
    return ranked[0] if ranked else None
