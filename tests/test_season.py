"""Tests for grouping_season copied from ReviewPrep."""

from __future__ import annotations

from red_team_prop_threader.season import grouping_season, grouping_season_with_fallback


def test_grouping_season_maps_lowest_jira_to_s_token() -> None:
    """Lowest jira version maps to S30 / S30.1 tokens."""
    assert grouping_season(["30.1.0", "30.0.0"]) == "S30"
    assert grouping_season(["30.1.0"]) == "S30.1"
    assert grouping_season(["32.0.0"]) == "S32"
    assert grouping_season([]) is None


def test_grouping_season_falls_back_to_tags_then_gantt() -> None:
    """Tags then gantt text supply a season when jira labels are empty."""
    assert grouping_season_with_fallback([], tags=["S30.1"]) == "S30.1"
    assert grouping_season_with_fallback([], gantt_season="S32") == "S32"
    assert grouping_season_with_fallback([], tags=[], gantt_season="") is None
