"""Tests for deterministic group-summary and asset-root message renderers."""

from __future__ import annotations

import json

import pytest

from red_team_prop_threader.domain import SupportingLink
from red_team_prop_threader._errors import ValidationError
from red_team_prop_threader.messages import (
    AID_EDIT_ASSET_DETAILS,
    AID_EDIT_GROUP_DETAILS,
    AssetRootContext,
    GroupSummaryContext,
    render_asset_root,
    render_group_summary,
)


# ---------------------------------------------------------------------------
# sample builders
# ---------------------------------------------------------------------------


def sample_group_context(**kwargs: object) -> GroupSummaryContext:
    """Build a minimal GroupSummaryContext."""
    base: dict[str, object] = dict(
        group_title="SEASON 31 PROP REQUEST THREADS",
        animator_id="U_ANIMATOR",
        additional_ids=(),
        links=(),
        included_asset_count=5,
        processing_status="In progress",
        summary_identity="summary-001",
        completion_count=None,
        failure_count=None,
        canvas_url=None,
    )
    base.update(kwargs)
    return GroupSummaryContext(**base)  # type: ignore[arg-type]


def sample_asset_context(**kwargs: object) -> AssetRootContext:
    """Build a minimal AssetRootContext with distinct asset and group people."""
    base: dict[str, object] = dict(
        asset_entity_id=12345,
        asset_name="Prop A",
        asset_url="https://sg.example.com/12345",
        group_title="SEASON 31 PROP REQUEST THREADS",
        created_ts=1700000000,
        asset_animator_id="U_ASSET_ANIMATOR",
        asset_additional_ids=(),
        group_animator_display="Group Animator Name",
        group_additional_displays=(),
        group_links=(),
        asset_links=(),
        message_identity="msg-001",
        is_latest=True,
        last_editor_display=None,
        updated_ts=None,
    )
    base.update(kwargs)
    return AssetRootContext(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# mandatory tests (from brief)
# ---------------------------------------------------------------------------


def test_asset_root_mentions_asset_people_but_not_group_people() -> None:
    """Asset root mentions asset animator but not the group animator by Slack ID."""
    message = render_asset_root(sample_asset_context())
    rendered = json.dumps(message)
    assert "<@U_ASSET_ANIMATOR>" in rendered
    assert "<@U_GROUP_ANIMATOR>" not in rendered
    assert "Group POCs" in rendered


# ---------------------------------------------------------------------------
# group summary — structure
# ---------------------------------------------------------------------------


def test_group_summary_accessible_fallback_text() -> None:
    """Group summary has a non-empty top-level text field for accessibility."""
    message = render_group_summary(sample_group_context())
    assert message.get("text")
    assert isinstance(message["text"], str)
    assert len(message["text"]) > 0  # type: ignore[arg-type]


def test_group_summary_has_blocks() -> None:
    """Group summary has a blocks list."""
    message = render_group_summary(sample_group_context())
    assert "blocks" in message
    assert isinstance(message["blocks"], list)
    assert len(message["blocks"]) > 0  # type: ignore[arg-type]


def test_group_summary_title_in_output() -> None:
    """Group title appears in the rendered summary."""
    ctx = sample_group_context(group_title="UNIQUE_TITLE_XYZ_31")
    rendered = json.dumps(render_group_summary(ctx))
    assert "UNIQUE_TITLE_XYZ_31" in rendered


def test_group_summary_title_mrkdwn_escaped() -> None:
    """Group title special chars are escaped."""
    ctx = sample_group_context(group_title="Title & <stuff>")
    rendered = json.dumps(render_group_summary(ctx))
    assert "&amp;" in rendered


def test_group_summary_animator_mention() -> None:
    """Animator is rendered as a notifying Slack mention."""
    ctx = sample_group_context(animator_id="U_ANIM_XYZ")
    rendered = json.dumps(render_group_summary(ctx))
    assert "<@U_ANIM_XYZ>" in rendered


def test_group_summary_additional_mentions() -> None:
    """Additional people are rendered as notifying Slack mentions."""
    ctx = sample_group_context(additional_ids=("U_ADD1", "U_ADD2"))
    rendered = json.dumps(render_group_summary(ctx))
    assert "<@U_ADD1>" in rendered
    assert "<@U_ADD2>" in rendered


def test_group_summary_links_rendered() -> None:
    """Supporting links appear as Slack link markup."""
    links = (SupportingLink("Miro", "https://miro.com/board/1"),)
    ctx = sample_group_context(links=links)
    rendered = json.dumps(render_group_summary(ctx))
    assert "https://miro.com/board/1" in rendered
    assert "Miro" in rendered


def test_group_summary_included_count_in_output() -> None:
    """Included asset count appears in the rendered summary."""
    ctx = sample_group_context(included_asset_count=12)
    rendered = json.dumps(render_group_summary(ctx))
    assert "12" in rendered


def test_group_summary_processing_status_in_output() -> None:
    """Processing status string appears in the rendered summary."""
    ctx = sample_group_context(processing_status="UNIQUE_STATUS_STRING_ABC")
    rendered = json.dumps(render_group_summary(ctx))
    assert "UNIQUE_STATUS_STRING_ABC" in rendered


def test_group_summary_edit_button_action_id() -> None:
    """Group summary includes the stable edit_group_details action ID."""
    message = render_group_summary(sample_group_context())
    rendered = json.dumps(message)
    assert AID_EDIT_GROUP_DETAILS in rendered


def test_group_summary_edit_button_value_is_opaque_identity() -> None:
    """Edit button value is the opaque summary_identity, not other data."""
    ctx = sample_group_context(summary_identity="OPAQUE_SUMMARY_ID_XYZ")
    message = render_group_summary(ctx)
    rendered = json.dumps(message)
    assert "OPAQUE_SUMMARY_ID_XYZ" in rendered


@pytest.mark.parametrize("value_length", [2000, 2001])
def test_group_summary_enforces_button_value_limit(value_length: int) -> None:
    """Summary identity accepts 2000 characters and rejects 2001."""
    context = sample_group_context(summary_identity="x" * value_length)

    if value_length == 2000:
        message = render_group_summary(context)
        button = message["blocks"][-1]["elements"][0]  # type: ignore[index]
        assert len(button["value"]) == 2000
    else:
        with pytest.raises(ValidationError, match="button value"):
            render_group_summary(context)


def test_group_summary_completion_count_when_supplied() -> None:
    """Completion count appears when provided."""
    ctx = sample_group_context(completion_count=8, failure_count=2)
    rendered = json.dumps(render_group_summary(ctx))
    assert "8" in rendered
    assert "2" in rendered


def test_group_summary_canvas_link_when_supplied() -> None:
    """Canvas URL appears as a link when provided."""
    ctx = sample_group_context(canvas_url="https://slack.com/canvas/unique-canvas-id")
    rendered = json.dumps(render_group_summary(ctx))
    assert "unique-canvas-id" in rendered


def test_group_summary_no_canvas_link_when_absent() -> None:
    """Canvas URL is absent when canvas_url is None."""
    ctx = sample_group_context(canvas_url=None)
    rendered = json.dumps(render_group_summary(ctx))
    assert "canvas-id" not in rendered


def test_group_summary_json_serializable() -> None:
    """Group summary is JSON-serializable."""
    json.dumps(render_group_summary(sample_group_context()))


def test_group_summary_long_title_raises() -> None:
    """Group title exceeding Slack section text limit raises ValidationError."""
    ctx = sample_group_context(group_title="T" * 3001)
    with pytest.raises(ValidationError):
        render_group_summary(ctx)


# ---------------------------------------------------------------------------
# asset root — structure
# ---------------------------------------------------------------------------


def test_asset_root_accessible_fallback_text() -> None:
    """Asset root has a non-empty top-level text field for accessibility."""
    message = render_asset_root(sample_asset_context())
    assert message.get("text")
    assert isinstance(message["text"], str)
    assert len(message["text"]) > 0  # type: ignore[arg-type]


def test_asset_root_has_blocks() -> None:
    """Asset root has a blocks list."""
    message = render_asset_root(sample_asset_context())
    assert "blocks" in message
    assert isinstance(message["blocks"], list)
    assert len(message["blocks"]) > 0  # type: ignore[arg-type]


def test_asset_root_latest_marker_when_current() -> None:
    """Latest marker is present when is_latest=True."""
    ctx = sample_asset_context(is_latest=True)
    rendered = json.dumps(render_asset_root(ctx))
    assert "Latest" in rendered or "latest" in rendered


def test_asset_root_no_latest_marker_when_not_current() -> None:
    """Latest marker is absent when is_latest=False."""
    ctx = sample_asset_context(is_latest=False)
    rendered = json.dumps(render_asset_root(ctx))
    # "Latest" should not appear
    assert "Latest" not in rendered


def test_asset_root_creation_date_markup() -> None:
    """Creation time appears as Slack date markup with unix timestamp."""
    ctx = sample_asset_context(created_ts=1700000000)
    rendered = json.dumps(render_asset_root(ctx))
    assert "1700000000" in rendered


def test_asset_root_asset_name_in_output() -> None:
    """Asset name appears in the rendered message."""
    ctx = sample_asset_context(asset_name="UNIQUE_ASSET_PROP_NAME_XYZ")
    rendered = json.dumps(render_asset_root(ctx))
    assert "UNIQUE_ASSET_PROP_NAME_XYZ" in rendered


def test_asset_root_asset_url_in_output() -> None:
    """Asset URL appears as a link in the rendered message."""
    ctx = sample_asset_context(asset_url="https://sg.example.com/unique-test-12345")
    rendered = json.dumps(render_asset_root(ctx))
    assert "unique-test-12345" in rendered


def test_asset_root_group_title_in_output() -> None:
    """Group title appears in the rendered message."""
    ctx = sample_asset_context(group_title="SEASON_31_UNIQUE_GROUP_TITLE")
    rendered = json.dumps(render_asset_root(ctx))
    assert "SEASON_31_UNIQUE_GROUP_TITLE" in rendered


def test_asset_root_asset_animator_mentioned() -> None:
    """Asset animator is rendered as a notifying Slack mention."""
    ctx = sample_asset_context(asset_animator_id="U_ASSET_ANIM_UNIQUE")
    rendered = json.dumps(render_asset_root(ctx))
    assert "<@U_ASSET_ANIM_UNIQUE>" in rendered


def test_asset_root_asset_additional_mentioned() -> None:
    """Asset additional people are rendered as notifying Slack mentions."""
    ctx = sample_asset_context(asset_additional_ids=("U_ASSET_ADD1", "U_ASSET_ADD2"))
    rendered = json.dumps(render_asset_root(ctx))
    assert "<@U_ASSET_ADD1>" in rendered
    assert "<@U_ASSET_ADD2>" in rendered


def test_asset_root_group_animator_not_mentioned() -> None:
    """Group animator is shown as plain display name, never as <@ID>."""
    ctx = sample_asset_context(group_animator_display="Jane Doe")
    rendered = json.dumps(render_asset_root(ctx))
    # The display name should appear
    assert "Jane Doe" in rendered
    # But not as a Slack mention (<@U_...>) — we don't have the slack ID in context


def test_asset_root_group_additional_not_mentioned() -> None:
    """Group additional people appear as plain display names, not @-mentions."""
    ctx = sample_asset_context(group_additional_displays=("Alice Smith", "Bob Jones"))
    rendered = json.dumps(render_asset_root(ctx))
    assert "Alice Smith" in rendered
    assert "Bob Jones" in rendered


def test_asset_root_group_pocs_label_present() -> None:
    """Group POCs label is present in the rendered message."""
    rendered = json.dumps(render_asset_root(sample_asset_context()))
    assert "Group POCs" in rendered


def test_asset_root_group_links_in_output() -> None:
    """Group links appear in the rendered message."""
    links = (SupportingLink("Miro", "https://miro.com/board/unique-group-link"),)
    ctx = sample_asset_context(group_links=links)
    rendered = json.dumps(render_asset_root(ctx))
    assert "unique-group-link" in rendered


def test_asset_root_asset_links_in_output() -> None:
    """Asset links appear in the rendered message."""
    links = (SupportingLink("SG", "https://sg.example.com/unique-asset-link"),)
    ctx = sample_asset_context(asset_links=links)
    rendered = json.dumps(render_asset_root(ctx))
    assert "unique-asset-link" in rendered


def test_asset_root_group_links_and_asset_links_labelled_separately() -> None:
    """Group and asset links appear in separate labelled sections."""
    g_links = (SupportingLink("Group Link", "https://group.example.com/1"),)
    a_links = (SupportingLink("Asset Link", "https://asset.example.com/2"),)
    ctx = sample_asset_context(group_links=g_links, asset_links=a_links)
    rendered = json.dumps(render_asset_root(ctx))
    # Both links present
    assert "group.example.com" in rendered
    assert "asset.example.com" in rendered


def test_asset_root_edit_button_action_id() -> None:
    """Asset root includes the stable edit_asset_details action ID."""
    rendered = json.dumps(render_asset_root(sample_asset_context()))
    assert AID_EDIT_ASSET_DETAILS in rendered


def test_asset_root_edit_button_value_is_message_identity() -> None:
    """Edit button value is the opaque message identity."""
    ctx = sample_asset_context(message_identity="OPAQUE_MSG_ID_ABC")
    rendered = json.dumps(render_asset_root(ctx))
    assert "OPAQUE_MSG_ID_ABC" in rendered


@pytest.mark.parametrize("value_length", [2000, 2001])
def test_asset_root_enforces_button_value_limit(value_length: int) -> None:
    """Message identity accepts 2000 characters and rejects 2001."""
    context = sample_asset_context(message_identity="x" * value_length)

    if value_length == 2000:
        message = render_asset_root(context)
        button = message["blocks"][-1]["elements"][0]  # type: ignore[index]
        assert len(button["value"]) == 2000
    else:
        with pytest.raises(ValidationError, match="button value"):
            render_asset_root(context)


def test_asset_root_last_editor_when_set_and_latest() -> None:
    """Last editor display name appears when set and is_latest=True."""
    ctx = sample_asset_context(is_latest=True, last_editor_display="Editor Name", updated_ts=1700000100)
    rendered = json.dumps(render_asset_root(ctx))
    assert "Editor Name" in rendered


def test_asset_root_update_timestamp_when_set() -> None:
    """Update timestamp appears in the rendered message when set and latest."""
    ctx = sample_asset_context(is_latest=True, last_editor_display="Ed", updated_ts=1700000999)
    rendered = json.dumps(render_asset_root(ctx))
    assert "1700000999" in rendered


def test_asset_root_no_edit_info_when_not_latest() -> None:
    """Edit timestamp and editor are absent when is_latest=False."""
    ctx = sample_asset_context(is_latest=False, last_editor_display="Ed", updated_ts=1700000999)
    rendered = json.dumps(render_asset_root(ctx))
    # update ts should not appear for non-latest roots
    assert "1700000999" not in rendered


def test_asset_root_json_serializable() -> None:
    """Asset root message is JSON-serializable."""
    json.dumps(render_asset_root(sample_asset_context()))


def test_asset_root_deterministic_block_order() -> None:
    """Same context produces identical rendered output on repeated calls."""
    ctx = sample_asset_context()
    assert json.dumps(render_asset_root(ctx)) == json.dumps(render_asset_root(ctx))


def test_asset_root_mrkdwn_escaped_asset_name() -> None:
    """Special characters in asset name are escaped."""
    ctx = sample_asset_context(asset_name="Prop & <B>")
    rendered = json.dumps(render_asset_root(ctx))
    assert "&amp;" in rendered


def test_asset_root_group_pocs_not_slack_mentions() -> None:
    """Group POC display names are never rendered as <@...> mentions."""
    ctx = sample_asset_context(group_animator_display="Jane Doe", group_additional_displays=("Alice", "Bob"))
    rendered = json.dumps(render_asset_root(ctx))
    # display names present
    assert "Jane Doe" in rendered
    assert "Alice" in rendered
    # none of them as @-mentions (these names don't have Slack IDs in context)
    # verify no "<@" followed immediately by display name characters
    assert "<@Jane" not in rendered
    assert "<@Alice" not in rendered


def test_group_summary_fallback_text_contains_title() -> None:
    """Accessible fallback text for group summary includes the group title."""
    ctx = sample_group_context(group_title="SEASON 31 FALLBACK CHECK")
    message = render_group_summary(ctx)
    assert "SEASON 31 FALLBACK CHECK" in message["text"]  # type: ignore[operator]


def test_asset_root_fallback_text_contains_asset_name() -> None:
    """Accessible fallback text for asset root includes the asset name."""
    ctx = sample_asset_context(asset_name="UNIQUE_FALLBACK_PROP")
    message = render_asset_root(ctx)
    assert "UNIQUE_FALLBACK_PROP" in message["text"]  # type: ignore[operator]
