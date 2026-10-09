"""The site ranking rules. The function itself is written by the owner."""

from datetime import UTC, datetime, timedelta

from glucobalance.rotation import NEVER_USED_DAYS, SiteState, rank_sites, suggest_site

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
REST = 14


def used(code: str, days_ago: float, **kwargs: object) -> SiteState:
    return SiteState(code, NOW - timedelta(days=days_ago), **kwargs)  # type: ignore[arg-type]


def never(code: str, **kwargs: object) -> SiteState:
    return SiteState(code, None, **kwargs)  # type: ignore[arg-type]


def test_no_sites_gives_an_empty_ranking_and_no_suggestion() -> None:
    assert rank_sites([], NOW, REST) == []
    assert suggest_site([], NOW, REST) is None


def test_the_site_unused_for_longest_comes_first() -> None:
    sites = [used("a", 20), used("b", 40), used("c", 30)]
    assert rank_sites(sites, NOW, REST) == ["b", "c", "a"]


def test_a_never_used_site_comes_before_a_used_one() -> None:
    sites = [used("a", 100), never("b")]
    assert rank_sites(sites, NOW, REST) == ["b", "a"]


def test_a_never_used_site_scores_never_used_days() -> None:
    sites = [used("a", NEVER_USED_DAYS + 1), never("b")]
    assert rank_sites(sites, NOW, REST)[0] == "a"


def test_a_blocked_site_is_never_returned() -> None:
    sites = [used("a", 90, blocked=True), used("b", 20)]
    assert rank_sites(sites, NOW, REST) == ["b"]


def test_a_blocked_never_used_site_is_never_returned() -> None:
    assert rank_sites([never("a", blocked=True)], NOW, REST) == []
    assert suggest_site([never("a", blocked=True)], NOW, REST) is None


def test_a_site_with_weight_zero_is_never_returned() -> None:
    sites = [used("a", 90, weight=0.0), used("b", 20)]
    assert rank_sites(sites, NOW, REST) == ["b"]


def test_rested_sites_rank_above_sites_still_resting() -> None:
    sites = [used("fresh", 3, weight=2.0), used("rested", 15)]
    assert rank_sites(sites, NOW, REST) == ["rested", "fresh"]


def test_exactly_the_rest_period_counts_as_rested() -> None:
    sites = [used("resting", 13.9), used("rested", 14.0)]
    assert rank_sites(sites, NOW, REST) == ["rested", "resting"]


def test_resting_sites_are_still_offered_after_the_rested_ones() -> None:
    sites = [used("a", 1), used("b", 5), used("c", 3)]
    assert rank_sites(sites, NOW, REST) == ["b", "c", "a"]


def test_a_higher_weight_lifts_a_site_within_its_group() -> None:
    sites = [used("plain", 30), used("liked", 20, weight=2.0)]
    assert rank_sites(sites, NOW, REST) == ["liked", "plain"]


def test_a_lower_weight_drops_a_site_within_its_group() -> None:
    sites = [used("plain", 20), used("disliked", 30, weight=0.5)]
    assert rank_sites(sites, NOW, REST) == ["plain", "disliked"]


def test_equal_scores_are_ordered_by_code() -> None:
    sites = [used("b", 20), used("a", 20), used("c", 20)]
    assert rank_sites(sites, NOW, REST) == ["a", "b", "c"]


def test_the_result_does_not_depend_on_input_order() -> None:
    sites = [used("a", 20), used("b", 40), never("c"), used("d", 2)]
    assert rank_sites(sites, NOW, REST) == rank_sites(list(reversed(sites)), NOW, REST)


def test_input_list_is_not_changed() -> None:
    sites = [used("a", 20), used("b", 40)]
    before = list(sites)
    rank_sites(sites, NOW, REST)
    assert sites == before


def test_suggest_site_is_the_first_ranked_site() -> None:
    sites = [used("a", 20), used("b", 40), used("c", 1, blocked=True)]
    assert suggest_site(sites, NOW, REST) == "b"


def test_the_rest_period_decides_which_group_a_site_is_in() -> None:
    sites = [used("a", 20), used("b", 10, weight=3.0)]
    assert rank_sites(sites, NOW, 14) == ["a", "b"]  # only a has rested
    assert rank_sites(sites, NOW, 5) == ["b", "a"]  # both rested: b scores 30, a scores 20
