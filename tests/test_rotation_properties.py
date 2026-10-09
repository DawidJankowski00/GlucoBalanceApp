"""Property-based tests for the site ranking.

Hypothesis generates many random sets of sites (random last uses, blocks, weights and rest
periods) and checks that rules which must hold for *every* input really do. When a rule breaks,
Hypothesis shrinks the input to the smallest example that still fails.
"""

import random
from collections import Counter
from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from glucobalance.rotation import SiteState, rank_sites, suggest_site

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

rest_days = st.integers(min_value=0, max_value=60)
last_used = st.one_of(
    st.none(),
    st.integers(min_value=1, max_value=400 * 24 * 60).map(lambda m: NOW - timedelta(minutes=m)),
)
weights = st.sampled_from([0.0, 0.5, 1.0, 1.5, 2.0])


@st.composite
def site_lists(draw: st.DrawFn, *, allow_blocks: bool = True) -> list[SiteState]:
    count = draw(st.integers(min_value=0, max_value=24))
    return [
        SiteState(
            code=f"site-{i:02d}",
            last_used=draw(last_used),
            blocked=draw(st.booleans()) if allow_blocks else False,
            weight=draw(weights),
        )
        for i in range(count)
    ]


def usable(sites: list[SiteState]) -> set[str]:
    return {s.code for s in sites if not s.blocked and s.weight > 0}


@given(site_lists(), rest_days)
def test_no_blocked_or_avoided_site_is_ever_ranked(sites: list[SiteState], rest: int) -> None:
    ranked = rank_sites(sites, NOW, rest)
    excluded = {s.code for s in sites} - usable(sites)
    assert not excluded & set(ranked)


@given(site_lists(), rest_days)
def test_no_blocked_or_avoided_site_is_ever_suggested(sites: list[SiteState], rest: int) -> None:
    suggestion = suggest_site(sites, NOW, rest)
    assert suggestion is None or suggestion in usable(sites)
    assert (suggestion is None) == (not usable(sites))


@given(site_lists(), rest_days)
def test_every_usable_site_is_ranked_once(sites: list[SiteState], rest: int) -> None:
    ranked = rank_sites(sites, NOW, rest)
    assert len(ranked) == len(set(ranked))
    assert set(ranked) == usable(sites)


@given(site_lists(), rest_days)
def test_rested_sites_always_come_first(sites: list[SiteState], rest: int) -> None:
    by_code = {s.code: s for s in sites}

    def rested(code: str) -> bool:
        used = by_code[code].last_used
        return used is None or NOW - used >= timedelta(days=rest)

    flags = [rested(code) for code in rank_sites(sites, NOW, rest)]
    assert flags == sorted(flags, reverse=True)


@given(site_lists(), rest_days, st.randoms(use_true_random=False))
def test_input_order_does_not_matter(sites: list[SiteState], rest: int, rng: random.Random) -> None:
    shuffled = list(sites)
    rng.shuffle(shuffled)
    assert rank_sites(shuffled, NOW, rest) == rank_sites(sites, NOW, rest)


@given(
    site_lists(allow_blocks=False),
    rest_days,
    st.integers(min_value=1, max_value=5),
    st.sampled_from([timedelta(hours=8), timedelta(days=1), timedelta(days=3)]),
)
def test_always_following_the_suggestion_keeps_usage_even(
    sites: list[SiteState], rest: int, rounds: int, step: timedelta
) -> None:
    """With equal weights, using the suggested site every time spreads use evenly.

    Starting from any history, after ``rounds`` passes over the sites every site has been used
    exactly ``rounds`` times: the ranking never picks a site twice before using all others.
    (The simulation spans at most 360 days, under ``NEVER_USED_DAYS``, so a never-used site
    always outranks one used during the simulation.)
    """
    sites = [SiteState(s.code, s.last_used) for s in sites]  # weight 1, not blocked
    if not sites:
        return
    uses: Counter[str] = Counter()
    now = NOW
    for _ in range(rounds * len(sites)):
        code = suggest_site(sites, now, rest)
        assert code is not None
        uses[code] += 1
        sites = [SiteState(s.code, now) if s.code == code else s for s in sites]
        now += step
    assert set(uses.values()) == {rounds}
    assert set(uses) == {s.code for s in sites}
