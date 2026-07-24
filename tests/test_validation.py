"""Tests for validation helpers and domain types."""

from __future__ import annotations

import pytest

from red_team_prop_threader.domain import (
    PersonRole,
    PersonEntry,
    ImportResult,
    ImportedAsset,
    OperationKind,
    SupportingLink,
    PersonSelection,
    DedupePeopleResult,
)
from red_team_prop_threader._errors import ValidationError
from red_team_prop_threader.validation import (
    dedupe_links,
    dedupe_people,
    infer_group_title,
    normalize_group_title,
    parse_supporting_links,
    validate_channel_members,
)


# ---------------------------------------------------------------------------
# parse_supporting_links
# ---------------------------------------------------------------------------


def test_parse_supporting_links_blank_returns_empty() -> None:
    """Blank input returns empty tuple."""
    assert parse_supporting_links("") == ()
    assert parse_supporting_links("   ") == ()
    assert parse_supporting_links("\n\n") == ()


def test_parse_supporting_links_single_entry() -> None:
    """Single valid entry is parsed correctly."""
    result = parse_supporting_links("Miro: https://miro.com/board/1")
    assert result == (SupportingLink("Miro", "https://miro.com/board/1"),)


def test_parse_supporting_links_multiline() -> None:
    """Multiple valid entries are parsed in order."""
    text = "Miro: https://miro.com/1\nReview: https://review.example.com/2"
    result = parse_supporting_links(text)
    assert len(result) == 2
    assert result[0] == SupportingLink("Miro", "https://miro.com/1")
    assert result[1] == SupportingLink("Review", "https://review.example.com/2")


def test_parse_supporting_links_preserves_order() -> None:
    """Input order is preserved."""
    text = "A: https://a.example.com\nB: https://b.example.com\nC: https://c.example.com"
    result = parse_supporting_links(text)
    assert [r.label for r in result] == ["A", "B", "C"]


def test_parse_supporting_links_skips_blank_lines() -> None:
    """Blank lines between entries are skipped."""
    text = "A: https://a.example.com\n\nB: https://b.example.com"
    result = parse_supporting_links(text)
    assert len(result) == 2


def test_parse_supporting_links_rejects_http() -> None:
    """Non-HTTPS URL raises ValidationError mentioning line 1."""
    with pytest.raises(ValidationError, match="1"):
        parse_supporting_links("Bad: http://example.com")


def test_parse_supporting_links_rejects_empty_label() -> None:
    """Empty label before colon raises ValidationError with explicit direction."""
    with pytest.raises(ValidationError, match=r"Supporting links require a label \(label: link\)"):
        parse_supporting_links(": https://example.com")


def test_parse_supporting_links_rejects_no_colon() -> None:
    """Line without colon-space separator raises ValidationError with explicit direction."""
    with pytest.raises(ValidationError, match=r"Supporting links require a label \(label: link\)"):
        parse_supporting_links("just some text")


def test_parse_supporting_links_rejects_relative_url() -> None:
    """Relative URL raises ValidationError."""
    with pytest.raises(ValidationError, match="1"):
        parse_supporting_links("Local: /relative/path")


def test_parse_supporting_links_no_sensitive_query_in_error() -> None:
    """ValidationError message does not echo sensitive query string values."""
    with pytest.raises(ValidationError) as exc_info:
        parse_supporting_links("Bad: http://example.com?secret=abc123")
    assert "abc123" not in str(exc_info.value)


def test_parse_supporting_links_error_identifies_line_number() -> None:
    """ValidationError identifies the offending line number."""
    text = "A: https://a.example.com\nBad: http://b.example.com"
    with pytest.raises(ValidationError, match="2"):
        parse_supporting_links(text)


@pytest.mark.parametrize(
    "url", ["https://:443/path", "https://user@:443/path", "https://[invalid/path", "https://example.com:not-a-port/path", "https://example.com:70000/path"]
)
def test_parse_supporting_links_rejects_malformed_authorities(url: str) -> None:
    """Malformed hosts and ports raise a safe ValidationError."""
    with pytest.raises(ValidationError, match="line 1"):
        parse_supporting_links(f"Bad: {url}")


# ---------------------------------------------------------------------------
# dedupe_links
# ---------------------------------------------------------------------------


def test_supporting_links_dedupe_by_normalized_url() -> None:
    """Asset entry wins over group entry when URLs normalize to the same value."""
    group = parse_supporting_links("Miro: https://miro.com/board/1")
    asset = parse_supporting_links("Review board: https://miro.com/board/1/")
    assert dedupe_links(group, asset) == (SupportingLink("Review board", "https://miro.com/board/1/"),)


def test_dedupe_links_asset_label_takes_precedence() -> None:
    """Asset label takes precedence over group label for the same URL."""
    group = parse_supporting_links("Group Label: https://example.com/page")
    asset = parse_supporting_links("Asset Label: https://example.com/page")
    result = dedupe_links(group, asset)
    assert len(result) == 1
    assert result[0].label == "Asset Label"


def test_dedupe_links_no_overlap_returns_all() -> None:
    """Non-overlapping entries from both levels are all returned."""
    group = parse_supporting_links("A: https://a.example.com/page")
    asset = parse_supporting_links("B: https://b.example.com/page")
    result = dedupe_links(group, asset)
    assert len(result) == 2


def test_dedupe_links_stable_order() -> None:
    """Non-overlapping entries preserve stable order (group first, then asset)."""
    group = parse_supporting_links("A: https://a.example.com\nB: https://b.example.com")
    asset = parse_supporting_links("C: https://c.example.com")
    result = dedupe_links(group, asset)
    labels = [r.label for r in result]
    assert labels == ["A", "B", "C"]


def test_dedupe_links_normalizes_scheme_host_case() -> None:
    """Scheme and host case differences are normalized for dedup."""
    group = (SupportingLink("A", "HTTPS://Example.COM/path"),)
    asset = (SupportingLink("B", "https://example.com/path"),)
    result = dedupe_links(group, asset)
    assert len(result) == 1
    assert result[0].label == "B"


def test_dedupe_links_empty_group() -> None:
    """Empty group with asset entries returns asset entries only."""
    asset = parse_supporting_links("A: https://a.example.com")
    result = dedupe_links((), asset)
    assert result == asset


def test_dedupe_links_empty_asset() -> None:
    """Empty asset with group entries returns group entries only."""
    group = parse_supporting_links("A: https://a.example.com")
    result = dedupe_links(group, ())
    assert result == group


def test_dedupe_links_deduplicates_within_group() -> None:
    """The first normalized URL within group links is retained."""
    group = (
        SupportingLink("First", "https://EXAMPLE.com/page/"),
        SupportingLink("Duplicate", "HTTPS://example.com/page"),
        SupportingLink("Other", "https://example.com/other"),
    )

    assert dedupe_links(group, ()) == (SupportingLink("First", "https://EXAMPLE.com/page/"), SupportingLink("Other", "https://example.com/other"))


def test_dedupe_links_deduplicates_within_asset() -> None:
    """The first normalized URL within asset links is retained."""
    asset = (
        SupportingLink("Asset first", "https://example.com/page"),
        SupportingLink("Asset duplicate", "https://EXAMPLE.com/page/"),
        SupportingLink("Asset other", "https://example.com/other"),
    )

    assert dedupe_links((), asset) == (SupportingLink("Asset first", "https://example.com/page"), SupportingLink("Asset other", "https://example.com/other"))


def test_dedupe_links_asset_wins_after_each_level_is_deduplicated() -> None:
    """Asset entries win across levels while each level keeps stable first occurrence."""
    group = (
        SupportingLink("Group duplicate", "https://example.com/shared/"),
        SupportingLink("Group duplicate again", "https://EXAMPLE.com/shared"),
        SupportingLink("Group unique", "https://example.com/group"),
    )
    asset = (
        SupportingLink("Asset winner", "HTTPS://example.com/shared"),
        SupportingLink("Asset duplicate", "https://example.com/shared/"),
        SupportingLink("Asset unique", "https://example.com/asset"),
    )

    assert dedupe_links(group, asset) == (
        SupportingLink("Group unique", "https://example.com/group"),
        SupportingLink("Asset winner", "HTTPS://example.com/shared"),
        SupportingLink("Asset unique", "https://example.com/asset"),
    )


def test_dedupe_links_equal_queries_are_duplicates() -> None:
    """Equivalent URLs with the same query deduplicate after case and slash normalization."""
    group = (SupportingLink("Group", "HTTPS://Example.com/page/?view=full"),)
    asset = (SupportingLink("Asset", "https://example.com/page?view=full"),)
    assert dedupe_links(group, asset) == asset


def test_dedupe_links_different_queries_remain_distinct() -> None:
    """URLs with different query strings remain separate entries."""
    group = (SupportingLink("Group", "https://example.com/page?view=group"),)
    asset = (SupportingLink("Asset", "https://example.com/page?view=asset"),)
    assert dedupe_links(group, asset) == group + asset


# ---------------------------------------------------------------------------
# normalize_group_title
# ---------------------------------------------------------------------------


def test_group_title_normalizes_case_space_and_colon() -> None:
    """Case, surrounding whitespace, repeated internal whitespace, and trailing colon are normalized."""
    assert normalize_group_title(" season 31 prop request threads: ") == "SEASON 31 PROP REQUEST THREADS"


def test_normalize_group_title_no_colon() -> None:
    """Title without trailing colon is normalized without adding one."""
    assert normalize_group_title("season 31") == "SEASON 31"


def test_normalize_group_title_internal_whitespace() -> None:
    """Repeated internal whitespace is collapsed to a single space."""
    assert normalize_group_title("season  31   prop") == "SEASON 31 PROP"


def test_normalize_group_title_uppercase() -> None:
    """Output is always uppercase."""
    assert normalize_group_title("lowercase title") == "LOWERCASE TITLE"


# ---------------------------------------------------------------------------
# infer_group_title
# ---------------------------------------------------------------------------


def test_infer_group_title_common_season() -> None:
    """All assets sharing one season token produces the canonical title."""
    assets = ["S31_prop_a", "S31_prop_b", "s31_prop_c"]
    assert infer_group_title(assets) == "SEASON 31 PROP REQUEST THREADS:"


def test_infer_group_title_multiple_seasons_across_assets() -> None:
    """Assets with different season tokens returns empty string."""
    assets = ["S31_prop_a", "S32_prop_b"]
    assert infer_group_title(assets) == ""


def test_infer_group_title_no_season_tokens() -> None:
    """Assets with no season tokens return empty string."""
    assets = ["prop_a", "prop_b"]
    assert infer_group_title(assets) == ""


def test_infer_group_title_empty_list() -> None:
    """Empty asset list returns empty string."""
    assert infer_group_title([]) == ""


def test_infer_group_title_multiple_seasons_in_one_name() -> None:
    """Asset containing multiple S<n> tokens is ambiguous; returns empty string."""
    assets = ["S31_and_S32_prop"]
    assert infer_group_title(assets) == ""


def test_infer_group_title_single_asset() -> None:
    """Single asset with one season token returns the canonical title."""
    assert infer_group_title(["S10_hero_prop"]) == "SEASON 10 PROP REQUEST THREADS:"


@pytest.mark.parametrize("name", ["assetS31_prop", "S31prop", "XS31Y", "S31S32_prop"])
def test_infer_group_title_rejects_embedded_or_adjacent_tokens(name: str) -> None:
    """Season tokens embedded in alphanumeric text are not accepted."""
    assert infer_group_title([name]) == ""


@pytest.mark.parametrize("name", ["S31_prop", "prop_S31", "prop_S31_asset", "_S31_"])
def test_infer_group_title_accepts_underscore_boundaries(name: str) -> None:
    """Underscores provide valid boundaries around season tokens."""
    assert infer_group_title([name]) == "SEASON 31 PROP REQUEST THREADS:"


# ---------------------------------------------------------------------------
# dedupe_people
# ---------------------------------------------------------------------------


def test_dedupe_people_asset_role_takes_precedence() -> None:
    """Person in asset selection is removed from group selection."""
    group_sel = PersonSelection(people=(PersonEntry("U001", PersonRole.ADDITIONAL),))
    asset_sel = PersonSelection(people=(PersonEntry("U001", PersonRole.ANIMATOR),))
    result = dedupe_people(group_sel, asset_sel)
    assert result.asset.people == (PersonEntry("U001", PersonRole.ANIMATOR),)
    assert all(p.slack_user_id != "U001" for p in result.group.people)


def test_dedupe_people_animator_precedence_within_group() -> None:
    """Within group, ANIMATOR wins over ADDITIONAL for the same user."""
    group_sel = PersonSelection(people=(PersonEntry("U001", PersonRole.ADDITIONAL), PersonEntry("U001", PersonRole.ANIMATOR)))
    result = dedupe_people(group_sel, PersonSelection(people=()))
    u001_entries = [p for p in result.group.people if p.slack_user_id == "U001"]
    assert len(u001_entries) == 1
    assert u001_entries[0].role == PersonRole.ANIMATOR


def test_dedupe_people_animator_precedence_within_asset() -> None:
    """Within asset, ANIMATOR wins over ADDITIONAL for the same user."""
    asset_sel = PersonSelection(people=(PersonEntry("U001", PersonRole.ADDITIONAL), PersonEntry("U001", PersonRole.ANIMATOR)))
    result = dedupe_people(PersonSelection(people=()), asset_sel)
    u001_entries = [p for p in result.asset.people if p.slack_user_id == "U001"]
    assert len(u001_entries) == 1
    assert u001_entries[0].role == PersonRole.ANIMATOR


def test_dedupe_people_stable_order_additional() -> None:
    """Additional people preserve stable input order."""
    group_sel = PersonSelection(
        people=(PersonEntry("U001", PersonRole.ADDITIONAL), PersonEntry("U002", PersonRole.ADDITIONAL), PersonEntry("U003", PersonRole.ADDITIONAL))
    )
    result = dedupe_people(group_sel, PersonSelection(people=()))
    ids = [p.slack_user_id for p in result.group.people]
    assert ids == ["U001", "U002", "U003"]


def test_dedupe_people_return_type() -> None:
    """dedupe_people returns a DedupePeopleResult instance."""
    result = dedupe_people(PersonSelection(people=()), PersonSelection(people=()))
    assert isinstance(result, DedupePeopleResult)


def test_dedupe_people_result_is_frozen() -> None:
    """DedupePeopleResult is immutable."""
    result = dedupe_people(PersonSelection(people=()), PersonSelection(people=()))
    with pytest.raises((AttributeError, TypeError)):
        result.group = PersonSelection(people=())  # type: ignore[misc]


def test_dedupe_people_no_overlap() -> None:
    """Non-overlapping group and asset people are all preserved."""
    group_sel = PersonSelection(people=(PersonEntry("U001", PersonRole.ADDITIONAL),))
    asset_sel = PersonSelection(people=(PersonEntry("U002", PersonRole.ANIMATOR),))
    result = dedupe_people(group_sel, asset_sel)
    assert len(result.group.people) == 1
    assert len(result.asset.people) == 1


# ---------------------------------------------------------------------------
# validate_channel_members
# ---------------------------------------------------------------------------


def test_validate_channel_members_finds_absent() -> None:
    """Returns Slack IDs selected but not in the member set."""
    selected = {"U001", "U002", "U003"}
    members = {"U001", "U003"}
    absent = validate_channel_members(selected, members)
    assert absent == {"U002"}


def test_validate_channel_members_all_present() -> None:
    """Returns empty set when all selected IDs are members."""
    selected = {"U001"}
    members = {"U001", "U002"}
    assert validate_channel_members(selected, members) == set()


def test_validate_channel_members_empty_selection() -> None:
    """Empty selection always returns empty set."""
    assert validate_channel_members(set(), {"U001"}) == set()


# ---------------------------------------------------------------------------
# Domain type structural tests
# ---------------------------------------------------------------------------


def test_supporting_link_frozen() -> None:
    """SupportingLink is immutable."""
    link = SupportingLink("A", "https://example.com")
    with pytest.raises((AttributeError, TypeError)):
        link.label = "B"  # type: ignore[misc]


def test_imported_asset_frozen() -> None:
    """ImportedAsset is immutable."""
    asset = ImportedAsset(entity_id=1, name="prop", url="https://sg.example.com/1", source_index=0)
    with pytest.raises((AttributeError, TypeError)):
        asset.name = "other"  # type: ignore[misc]


def test_import_result_frozen() -> None:
    """ImportResult is immutable."""
    result = ImportResult(assets=(), duplicate_count=0)
    with pytest.raises((AttributeError, TypeError)):
        result.duplicate_count = 1  # type: ignore[misc]


def test_operation_kind_values() -> None:
    """OperationKind has the required string values."""
    assert OperationKind.POST_SUMMARY == "post_summary"
    assert OperationKind.POST_ASSET == "post_asset"
    assert OperationKind.INDEX_ASSET == "index_asset"
    assert OperationKind.RETIRE_PRIOR_LATEST == "retire_prior_latest"
    assert OperationKind.FINALIZE_SUMMARY == "finalize_summary"


def test_person_role_values() -> None:
    """PersonRole has animator and additional values."""
    assert PersonRole.ANIMATOR == "animator"
    assert PersonRole.ADDITIONAL == "additional"


def test_person_entry_frozen() -> None:
    """PersonEntry is immutable."""
    entry = PersonEntry("U001", PersonRole.ANIMATOR)
    with pytest.raises((AttributeError, TypeError)):
        entry.slack_user_id = "U002"  # type: ignore[misc]


def test_person_selection_frozen() -> None:
    """PersonSelection is immutable."""
    sel = PersonSelection(people=())
    with pytest.raises((AttributeError, TypeError)):
        sel.people = (PersonEntry("U001", PersonRole.ANIMATOR),)  # type: ignore[misc]
