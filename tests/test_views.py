"""Tests for Slack Block Kit modal view renderers and state decoders."""

from __future__ import annotations

import re
import json
from typing import Any

import pytest

from red_team_prop_threader.views import (
    AID_NAV_BACK,
    AID_NAV_NEXT,
    AID_NAV_CONFIRM,
    BID_GROUP_LINKS,
    BID_GROUP_TITLE,
    AID_CANVAS_CREATE,
    AID_CANVAS_RENAME,
    AID_IMPORT_RESUME,
    AID_CANVAS_DECLINE,
    BID_GROUP_ANIMATOR,
    BID_GROUP_ADDITIONAL,
    AID_IMPORT_START_OVER,
    AID_CONFIRM_GROUP_TITLE,
    BID_CONFIRM_GROUP_TITLE,
    AssetDraft,
    ImportContext,
    AssetSelection,
    DecodedAssetPage,
    ChannelMemberOption,
    ConfirmationContext,
    CanvasPreflightContext,
    render_asset_page,
    render_import_view,
    decode_asset_page_state,
    render_confirmation_view,
    render_canvas_preflight_view,
)
from red_team_prop_threader.domain import ImportedAsset
from red_team_prop_threader._errors import ValidationError


# ---------------------------------------------------------------------------
# sample builders
# ---------------------------------------------------------------------------


def _asset(i: int) -> ImportedAsset:
    return ImportedAsset(entity_id=100 + i, name=f"Prop_{i}", url=f"https://sg.example.com/{100 + i}", source_index=i)


def _selection(i: int, **kwargs: Any) -> AssetSelection:
    base: dict[str, Any] = dict(entity_id=100 + i, included=True, animator_id=None, additional_ids=(), links_text="")
    base.update(kwargs)
    return AssetSelection(**base)


def sample_draft(asset_count: int = 5, **kwargs: Any) -> AssetDraft:
    """Build a minimal AssetDraft with n assets (entity_ids 100..100+n-1)."""
    assets = tuple(_asset(i) for i in range(asset_count))
    selections = tuple(_selection(i) for i in range(asset_count))
    base: dict[str, Any] = dict(
        draft_id="draft-001",
        assets=assets,
        group_title="SEASON 31 PROP REQUEST THREADS",
        group_animator_id=None,
        group_additional_ids=(),
        group_links_text="",
        selections=selections,
        channel_members=(
            ChannelMemberOption("U_ANIM", "Animator (@uanim)"),
            ChannelMemberOption("U_ADD1", "Add One (@uadd1)"),
            ChannelMemberOption("U_ADD2", "Add Two (@uadd2)"),
            ChannelMemberOption("U_GROUP_ANIM", "Group Animator (@ugroupanim)"),
            ChannelMemberOption("U_GROUP_ADD1", "Group Add (@ugroupadd1)"),
            ChannelMemberOption("U_ANIM1", "Anim One (@uanim1)"),
            ChannelMemberOption("U_ANIM3", "Anim Three (@uanim3)"),
        ),
    )
    base.update(kwargs)
    return AssetDraft(**base)


def _action_ids_in_view(view: dict[str, Any]) -> set[str]:
    """Return all action IDs found in actions blocks."""
    ids: set[str] = set()
    for block in view.get("blocks", []):
        for elem in block.get("elements", []):
            if "action_id" in elem:
                ids.add(elem["action_id"])
    return ids


def _block_ids(view: dict[str, Any]) -> list[str]:
    return [b.get("block_id", "") for b in view.get("blocks", [])]


def _extract_state_from_view(view: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal mock Slack view_state from a rendered view's initial values."""
    values: dict[str, dict[str, Any]] = {}
    for block in view.get("blocks", []):
        bid = block.get("block_id")
        if not bid or block.get("type") != "input":
            continue
        element = block.get("element", {})
        etype = element.get("type")
        if etype == "plain_text_input":
            values[bid] = {bid: {"type": "plain_text_input", "value": element.get("initial_value") or ""}}
        elif etype == "users_select":
            values[bid] = {bid: {"type": "users_select", "selected_user": element.get("initial_user")}}
        elif etype == "static_select":
            initial = element.get("initial_option") or {}
            values[bid] = {bid: {"type": "static_select", "selected_option": initial or None}}
        elif etype == "multi_users_select":
            values[bid] = {bid: {"type": "multi_users_select", "selected_users": list(element.get("initial_users") or [])}}
        elif etype == "multi_static_select":
            values[bid] = {bid: {"type": "multi_static_select", "selected_options": list(element.get("initial_options") or [])}}
        elif etype == "checkboxes":
            values[bid] = {bid: {"type": "checkboxes", "selected_options": list(element.get("initial_options") or [])}}
    return {"values": values}


# ---------------------------------------------------------------------------
# mandatory tests (from brief)
# ---------------------------------------------------------------------------


def test_asset_page_never_exceeds_fifteen_assets_or_one_hundred_blocks() -> None:
    """Render page 0 of a 30-asset draft; block and asset-block counts must be within limits."""
    view = render_asset_page(sample_draft(asset_count=30), page_index=0)
    assert view["private_metadata"]
    assert len(view["blocks"]) <= 100  # type: ignore[arg-type]
    assert sum(block["block_id"].startswith("asset_") for block in view["blocks"]) <= 15 * 4  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# canvas preflight
# ---------------------------------------------------------------------------


def test_canvas_preflight_action_ids_present() -> None:
    """Canvas preflight view includes create, rename, and decline action IDs."""
    ctx = CanvasPreflightContext(draft_id="d1", canvas_name="Season 31 Prop Threads", channel_id="C_ABC")
    view = render_canvas_preflight_view(ctx)
    aids = _action_ids_in_view(view)
    assert AID_CANVAS_CREATE in aids
    assert AID_CANVAS_RENAME in aids
    assert AID_CANVAS_DECLINE in aids


def test_canvas_preflight_private_metadata_is_draft_id() -> None:
    """private_metadata contains only the draft ID, no other state."""
    ctx = CanvasPreflightContext(draft_id="draft-xyz", canvas_name="Title", channel_id="C1")
    view = render_canvas_preflight_view(ctx)
    assert view["private_metadata"] == "draft-xyz"


def test_canvas_preflight_accessible_text_in_block() -> None:
    """Preflight view includes explanatory text about the canvas situation."""
    ctx = CanvasPreflightContext(draft_id="d1", canvas_name="My Canvas", channel_id="C1")
    view = render_canvas_preflight_view(ctx)
    rendered = json.dumps(view)
    assert "My Canvas" in rendered


def test_canvas_preflight_canvas_name_mrkdwn_escaped() -> None:
    """User-supplied canvas_name is escaped to prevent mrkdwn injection."""
    ctx = CanvasPreflightContext(draft_id="d1", canvas_name="Title <b> & more > here", channel_id="C1")
    view = render_canvas_preflight_view(ctx)
    rendered = json.dumps(view)
    assert "&amp;" in rendered
    assert "&lt;" in rendered
    assert "&gt;" in rendered


def test_canvas_preflight_json_serializable() -> None:
    """Canvas preflight view is JSON-serializable."""
    ctx = CanvasPreflightContext(draft_id="d1", canvas_name="Title", channel_id="C1")
    view = render_canvas_preflight_view(ctx)
    json.dumps(view)  # must not raise


def test_canvas_preflight_long_draft_id_raises() -> None:
    """Draft ID exceeding max length raises ValidationError."""
    ctx = CanvasPreflightContext(draft_id="x" * 300, canvas_name="Title", channel_id="C1")
    with pytest.raises(ValidationError):
        render_canvas_preflight_view(ctx)


def test_canvas_preflight_all_blocks_have_block_id() -> None:
    """Every block in the canvas preflight view has a block_id."""
    ctx = CanvasPreflightContext(draft_id="d1", canvas_name="Title", channel_id="C1")
    view = render_canvas_preflight_view(ctx)
    for block in view["blocks"]:  # type: ignore[union-attr]
        assert "block_id" in block, f"block missing block_id: {block!r}"


def test_canvas_preflight_type_is_modal() -> None:
    """Canvas preflight view is a modal."""
    ctx = CanvasPreflightContext(draft_id="d1", canvas_name="Title", channel_id="C1")
    view = render_canvas_preflight_view(ctx)
    assert view["type"] == "modal"


# ---------------------------------------------------------------------------
# import view
# ---------------------------------------------------------------------------


def test_import_view_basic_structure() -> None:
    """Import view is a modal with submit and close."""
    ctx = ImportContext(draft_id="d1")
    view = render_import_view(ctx)
    assert view["type"] == "modal"
    assert "submit" in view
    assert "close" in view


def test_import_view_private_metadata_is_draft_id() -> None:
    """Import view private_metadata is the draft ID."""
    ctx = ImportContext(draft_id="import-draft-007")
    view = render_import_view(ctx)
    assert view["private_metadata"] == "import-draft-007"


def test_import_view_prefilled_url_in_block() -> None:
    """Prefilled URL appears as initial_value in the URL input block."""
    ctx = ImportContext(draft_id="d1", prefilled_url="https://sg.example.com/page/23280")
    view = render_import_view(ctx)
    rendered = json.dumps(view)
    assert "https://sg.example.com/page/23280" in rendered


def test_import_view_no_prefilled_url_absent() -> None:
    """Without a prefilled URL the input block has no initial_value or an empty one."""
    ctx = ImportContext(draft_id="d1")
    view = render_import_view(ctx)
    # find the url input element
    for block in view["blocks"]:  # type: ignore[union-attr]
        elem = block.get("element", {})
        if elem.get("type") == "plain_text_input":
            assert not elem.get("initial_value")


def test_import_view_existing_draft_shows_resume_and_start_over() -> None:
    """When an existing draft is present, resume and start-over action IDs appear."""
    ctx = ImportContext(draft_id="d1", existing_draft_id="d-old", import_snapshot_ts=1700000000)
    view = render_import_view(ctx)
    aids = _action_ids_in_view(view)
    assert AID_IMPORT_RESUME in aids
    assert AID_IMPORT_START_OVER in aids


def test_import_view_no_existing_draft_no_resume_buttons() -> None:
    """Without an existing draft, resume and start-over actions are absent."""
    ctx = ImportContext(draft_id="d1")
    view = render_import_view(ctx)
    aids = _action_ids_in_view(view)
    assert AID_IMPORT_RESUME not in aids
    assert AID_IMPORT_START_OVER not in aids


def test_import_view_snapshot_time_shown() -> None:
    """Import snapshot timestamp appears in the rendered view for an existing draft."""
    ctx = ImportContext(draft_id="d1", existing_draft_id="d-old", import_snapshot_ts=1700000000)
    view = render_import_view(ctx)
    # must show some form of timestamp text (date markup or fallback)
    rendered = json.dumps(view)
    assert "1700000000" in rendered or "2023" in rendered


def test_import_view_json_serializable() -> None:
    """Import view is JSON-serializable."""
    ctx = ImportContext(draft_id="d1", prefilled_url="https://sg.example.com/page/1")
    json.dumps(render_import_view(ctx))


def test_import_view_all_blocks_have_block_id() -> None:
    """Every block in the import view has a block_id."""
    ctx = ImportContext(draft_id="d1", existing_draft_id="d-old", import_snapshot_ts=1700000000)
    view = render_import_view(ctx)
    for block in view["blocks"]:  # type: ignore[union-attr]
        assert "block_id" in block, f"block missing block_id: {block!r}"


@pytest.mark.parametrize("value_length", [2000, 2001])
def test_import_view_enforces_button_value_limit(value_length: int) -> None:
    """Existing draft button values accept 2000 characters and reject 2001."""
    context = ImportContext(draft_id="d1", existing_draft_id="x" * value_length)

    if value_length == 2000:
        view = render_import_view(context)
        resume = next(
            element
            for block in view["blocks"]  # type: ignore[union-attr]
            for element in block.get("elements", [])
            if element.get("action_id") == AID_IMPORT_RESUME
        )
        assert len(resume["value"]) == 2000
    else:
        with pytest.raises(ValidationError, match="button value"):
            render_import_view(context)


# ---------------------------------------------------------------------------
# asset page — counts and limits
# ---------------------------------------------------------------------------


def test_asset_page_zero_assets() -> None:
    """Zero-asset draft renders a valid modal with no asset blocks."""
    view = render_asset_page(sample_draft(asset_count=0), page_index=0)
    assert view["type"] == "modal"
    assert "submit" in view
    assert not any(b["block_id"].startswith("asset_") for b in view["blocks"])  # type: ignore[union-attr]


def test_asset_page_one_asset_page_0() -> None:
    """One-asset draft renders one set of asset blocks."""
    view = render_asset_page(sample_draft(asset_count=1), page_index=0)
    asset_block_count = sum(b["block_id"].startswith("asset_") for b in view["blocks"])  # type: ignore[union-attr]
    assert asset_block_count == 4


def test_asset_page_fifteen_assets_page_0() -> None:
    """Exactly 15 assets yields exactly 60 asset-prefixed blocks."""
    view = render_asset_page(sample_draft(asset_count=15), page_index=0)
    asset_block_count = sum(b["block_id"].startswith("asset_") for b in view["blocks"])  # type: ignore[union-attr]
    assert asset_block_count == 60
    assert len(view["blocks"]) <= 100  # type: ignore[arg-type]


def test_asset_page_sixteen_assets_splits_to_two_pages() -> None:
    """16 assets: page 0 has 15, page 1 has 1."""
    draft = sample_draft(asset_count=16)
    view0 = render_asset_page(draft, page_index=0)
    view1 = render_asset_page(draft, page_index=1)
    assert sum(b["block_id"].startswith("asset_") for b in view0["blocks"]) == 60  # type: ignore[union-attr]
    assert sum(b["block_id"].startswith("asset_") for b in view1["blocks"]) == 4  # type: ignore[union-attr]


def test_asset_page_thirty_assets_page_0() -> None:
    """30 assets on page 0: 15 assets, ≤100 blocks, ≤60 asset blocks."""
    view = render_asset_page(sample_draft(asset_count=30), page_index=0)
    assert len(view["blocks"]) <= 100  # type: ignore[arg-type]
    assert sum(b["block_id"].startswith("asset_") for b in view["blocks"]) <= 60  # type: ignore[union-attr]


def test_asset_page_thirty_assets_page_1() -> None:
    """30 assets on page 1: 15 assets, ≤100 blocks, ≤60 asset blocks."""
    view = render_asset_page(sample_draft(asset_count=30), page_index=1)
    assert len(view["blocks"]) <= 100  # type: ignore[arg-type]
    assert sum(b["block_id"].startswith("asset_") for b in view["blocks"]) <= 60  # type: ignore[union-attr]


def test_asset_page_preserves_shotgrid_order() -> None:
    """Assets appear in ShotGrid source_index order on each page."""
    assets = (
        ImportedAsset(entity_id=301, name="Prop_A", url="https://sg.example.com/301", source_index=0),
        ImportedAsset(entity_id=202, name="Prop_B", url="https://sg.example.com/202", source_index=1),
        ImportedAsset(entity_id=103, name="Prop_C", url="https://sg.example.com/103", source_index=2),
    )
    selections = tuple(AssetSelection(entity_id=a.entity_id, included=True, animator_id=None, additional_ids=(), links_text="") for a in assets)
    draft = AssetDraft(
        draft_id="d1", assets=assets, group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=selections
    )
    view = render_asset_page(draft, page_index=0)
    # collect entity IDs from asset_include block IDs in order
    include_bids = [b["block_id"] for b in view["blocks"] if re.match(r"asset_\d+_include", b.get("block_id", ""))]  # type: ignore[union-attr]
    entity_ids_in_order = [int(re.search(r"asset_(\d+)_include", bid).group(1)) for bid in include_bids]  # type: ignore[union-attr]
    assert entity_ids_in_order == [301, 202, 103]


def test_asset_page_private_metadata_is_draft_id_only() -> None:
    """private_metadata is exactly the draft ID — no extra JSON or secrets."""
    draft = sample_draft(asset_count=3)
    view = render_asset_page(draft, page_index=0)
    assert view["private_metadata"] == "draft-001"


def test_asset_page_all_blocks_have_block_id() -> None:
    """Every block in the asset page view has a block_id."""
    view = render_asset_page(sample_draft(asset_count=5), page_index=0)
    for block in view["blocks"]:  # type: ignore[union-attr]
        assert "block_id" in block, f"block missing block_id: {block!r}"


# ---------------------------------------------------------------------------
# asset page — initial values
# ---------------------------------------------------------------------------


def test_asset_page_initial_checkbox_set_when_included() -> None:
    """Include block has initial_options when included=True."""
    assets = (_asset(0),)
    selections = (AssetSelection(entity_id=100, included=True, animator_id=None, additional_ids=(), links_text=""),)
    draft = AssetDraft(
        draft_id="d1", assets=assets, group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=selections
    )
    view = render_asset_page(draft, page_index=0)
    include_block = next(b for b in view["blocks"] if b.get("block_id") == "asset_100_include")  # type: ignore[union-attr]
    assert include_block["element"]["initial_options"]  # type: ignore[index]


def test_asset_page_initial_checkbox_absent_when_not_included() -> None:
    """Include block has no initial_options when included=False."""
    assets = (_asset(0),)
    selections = (AssetSelection(entity_id=100, included=False, animator_id=None, additional_ids=(), links_text=""),)
    draft = AssetDraft(
        draft_id="d1", assets=assets, group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=selections
    )
    view = render_asset_page(draft, page_index=0)
    include_block = next(b for b in view["blocks"] if b.get("block_id") == "asset_100_include")  # type: ignore[union-attr]
    assert not include_block["element"].get("initial_options")  # type: ignore[index]


def test_asset_page_initial_user_set_when_animator_present() -> None:
    """Animator block has initial_option when animator_id is set."""
    assets = (_asset(0),)
    selections = (AssetSelection(entity_id=100, included=True, animator_id="U_ANIM", additional_ids=(), links_text=""),)
    draft = AssetDraft(
        draft_id="d1",
        assets=assets,
        group_title="G",
        group_animator_id=None,
        group_additional_ids=(),
        group_links_text="",
        selections=selections,
        channel_members=(ChannelMemberOption("U_ANIM", "Animator (@uanim)"),),
    )
    view = render_asset_page(draft, page_index=0)
    anim_block = next(b for b in view["blocks"] if b.get("block_id") == "asset_100_animator")  # type: ignore[union-attr]
    assert anim_block["element"]["type"] == "static_select"  # type: ignore[index]
    assert anim_block["element"]["initial_option"]["value"] == "U_ANIM"  # type: ignore[index]
    assert "@uanim" in anim_block["element"]["initial_option"]["text"]["text"]  # type: ignore[index]


def test_asset_page_animator_input_is_optional() -> None:
    """Per-asset animator input is optional so create can proceed unassigned."""
    view = render_asset_page(sample_draft(asset_count=1), page_index=0)
    animator = next(block for block in view["blocks"] if block.get("block_id") == "asset_100_animator")  # type: ignore[union-attr]

    assert animator["type"] == "input"
    assert animator["optional"] is True


def test_asset_page_plain_text_asset_label_preserves_special_characters() -> None:
    """Plain-text labels retain raw special characters while mrkdwn stays escaped."""
    asset = ImportedAsset(entity_id=42, name="Prop & <Hero>", url="https://sg.example.com/42", source_index=0)
    selection = AssetSelection(entity_id=42, included=True, animator_id=None, additional_ids=(), links_text="")
    draft = AssetDraft(
        draft_id="d1", assets=(asset,), group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=(selection,)
    )
    view = render_asset_page(draft, page_index=0)
    include = next(block for block in view["blocks"] if block.get("block_id") == "asset_42_include")  # type: ignore[union-attr]
    context = next(block for block in view["blocks"] if block.get("block_id") == "ctx_asset_42")  # type: ignore[union-attr]

    assert include["label"]["text"] == "Prop & <Hero> (ID: 42)"  # type: ignore[index]
    assert context["elements"][0]["text"] == "<https://sg.example.com/42|Prop &amp; &lt;Hero&gt;> · ShotGrid ID: 42"  # type: ignore[index]


def test_asset_context_mrkdwn_accepts_exact_slack_limit() -> None:
    """Asset context mrkdwn accepts a payload exactly 3000 characters long."""
    prefix = "<https://sg.example.com/42|"
    suffix = "> · ShotGrid ID: 42"
    name = "N" * (3000 - len(prefix) - len(suffix))
    asset = ImportedAsset(entity_id=42, name=name, url="https://sg.example.com/42", source_index=0)
    selection = AssetSelection(entity_id=42, included=True, animator_id=None, additional_ids=(), links_text="")
    draft = AssetDraft(
        draft_id="d1", assets=(asset,), group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=(selection,)
    )

    view = render_asset_page(draft, page_index=0)
    context = next(block for block in view["blocks"] if block.get("block_id") == "ctx_asset_42")  # type: ignore[union-attr]
    assert len(context["elements"][0]["text"]) == 3000  # type: ignore[index]


def test_asset_context_mrkdwn_rejects_over_slack_limit() -> None:
    """Asset context fails safely instead of truncating Slack link markup."""
    prefix = "<https://sg.example.com/42|"
    suffix = "> · ShotGrid ID: 42"
    name = "N" * (3001 - len(prefix) - len(suffix))
    asset = ImportedAsset(entity_id=42, name=name, url="https://sg.example.com/42", source_index=0)
    selection = AssetSelection(entity_id=42, included=True, animator_id=None, additional_ids=(), links_text="")
    draft = AssetDraft(
        draft_id="d1", assets=(asset,), group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=(selection,)
    )

    with pytest.raises(ValidationError, match="asset context"):
        render_asset_page(draft, page_index=0)


def test_asset_context_mrkdwn_rejects_oversized_url() -> None:
    """An impossible oversized imported URL fails safely before link rendering."""
    asset = ImportedAsset(entity_id=42, name="Prop", url=f"https://sg.example.com/{'x' * 3000}", source_index=0)
    selection = AssetSelection(entity_id=42, included=True, animator_id=None, additional_ids=(), links_text="")
    draft = AssetDraft(
        draft_id="d1", assets=(asset,), group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=(selection,)
    )

    with pytest.raises(ValidationError, match="asset context"):
        render_asset_page(draft, page_index=0)


def test_asset_page_initial_users_set_for_additional() -> None:
    """Additional block has initial_options when additional_ids are present."""
    assets = (_asset(0),)
    selections = (AssetSelection(entity_id=100, included=True, animator_id=None, additional_ids=("U_ADD1", "U_ADD2"), links_text=""),)
    draft = AssetDraft(
        draft_id="d1",
        assets=assets,
        group_title="G",
        group_animator_id=None,
        group_additional_ids=(),
        group_links_text="",
        selections=selections,
        channel_members=(ChannelMemberOption("U_ADD1", "Add One (@uadd1)"), ChannelMemberOption("U_ADD2", "Add Two (@uadd2)")),
    )
    view = render_asset_page(draft, page_index=0)
    add_block = next(b for b in view["blocks"] if b.get("block_id") == "asset_100_additional")  # type: ignore[union-attr]
    assert add_block["element"]["type"] == "multi_static_select"  # type: ignore[index]
    assert [o["value"] for o in add_block["element"]["initial_options"]] == ["U_ADD1", "U_ADD2"]  # type: ignore[index]


def test_asset_page_initial_links_text_set() -> None:
    """Links block has initial_value when links_text is non-empty."""
    assets = (_asset(0),)
    selections = (AssetSelection(entity_id=100, included=True, animator_id=None, additional_ids=(), links_text="Miro: https://miro.com/1"),)
    draft = AssetDraft(
        draft_id="d1", assets=assets, group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=selections
    )
    view = render_asset_page(draft, page_index=0)
    links_block = next(b for b in view["blocks"] if b.get("block_id") == "asset_100_links")  # type: ignore[union-attr]
    assert links_block["element"]["initial_value"] == "Miro: https://miro.com/1"  # type: ignore[index]


def test_asset_page_group_initial_animator_set() -> None:
    """group_animator block has initial_option when group_animator_id is set."""
    draft = sample_draft(asset_count=1, group_animator_id="U_GROUP_ANIM")
    view = render_asset_page(draft, page_index=0)
    anim_block = next(b for b in view["blocks"] if b.get("block_id") == BID_GROUP_ANIMATOR)  # type: ignore[union-attr]
    assert anim_block["element"]["type"] == "static_select"  # type: ignore[index]
    assert anim_block["element"]["initial_option"]["value"] == "U_GROUP_ANIM"  # type: ignore[index]
    assert "@ugroupanim" in anim_block["element"]["initial_option"]["text"]["text"]  # type: ignore[index]


def test_asset_page_group_initial_title_set() -> None:
    """group_title block has initial_value matching the draft group title."""
    draft = sample_draft(asset_count=1, group_title="SEASON 31 PROP REQUEST THREADS")
    view = render_asset_page(draft, page_index=0)
    title_block = next(b for b in view["blocks"] if b.get("block_id") == BID_GROUP_TITLE)  # type: ignore[union-attr]
    assert title_block["element"]["initial_value"] == "SEASON 31 PROP REQUEST THREADS"  # type: ignore[index]


# ---------------------------------------------------------------------------
# asset page — navigation action IDs
# ---------------------------------------------------------------------------


def test_asset_page_page_0_shows_next_when_more_pages() -> None:
    """Page 0 of a 16-asset draft includes the next action ID."""
    view = render_asset_page(sample_draft(asset_count=16), page_index=0)
    assert AID_NAV_NEXT in _action_ids_in_view(view)


def test_asset_page_page_0_no_back_button() -> None:
    """Page 0 does not include the back action ID."""
    view = render_asset_page(sample_draft(asset_count=5), page_index=0)
    assert AID_NAV_BACK not in _action_ids_in_view(view)


def test_asset_page_page_0_single_page_shows_confirm() -> None:
    """Page 0 with ≤15 assets shows the confirm action ID."""
    view = render_asset_page(sample_draft(asset_count=5), page_index=0)
    assert AID_NAV_CONFIRM in _action_ids_in_view(view)


def test_asset_page_page_1_shows_back_and_confirm() -> None:
    """Page 1 includes back and confirm action IDs."""
    view = render_asset_page(sample_draft(asset_count=30), page_index=1)
    aids = _action_ids_in_view(view)
    assert AID_NAV_BACK in aids
    assert AID_NAV_CONFIRM in aids


def test_asset_page_page_1_no_next_button() -> None:
    """Page 1 does not include the next action ID."""
    view = render_asset_page(sample_draft(asset_count=30), page_index=1)
    assert AID_NAV_NEXT not in _action_ids_in_view(view)


# ---------------------------------------------------------------------------
# asset page — error cases
# ---------------------------------------------------------------------------


def test_asset_page_invalid_page_index_raises() -> None:
    """Page index outside {0,1} raises ValidationError."""
    with pytest.raises(ValidationError):
        render_asset_page(sample_draft(asset_count=5), page_index=2)
    with pytest.raises(ValidationError):
        render_asset_page(sample_draft(asset_count=5), page_index=-1)


def test_asset_page_page_1_when_fifteen_assets_raises() -> None:
    """Page 1 for a draft with ≤15 assets raises ValidationError."""
    with pytest.raises(ValidationError):
        render_asset_page(sample_draft(asset_count=15), page_index=1)


def test_asset_page_too_many_assets_raises() -> None:
    """Draft with >30 assets raises ValidationError."""
    assets = tuple(ImportedAsset(entity_id=i, name=f"Prop_{i}", url=f"https://sg.example.com/{i}", source_index=i) for i in range(31))
    selections = tuple(AssetSelection(entity_id=a.entity_id, included=True, animator_id=None, additional_ids=(), links_text="") for a in assets)
    with pytest.raises(ValidationError):
        AssetDraft(draft_id="d1", assets=assets, group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=selections)


def test_asset_page_duplicate_entity_ids_raises() -> None:
    """Assets with duplicate entity IDs raise ValidationError."""
    assets = (
        ImportedAsset(entity_id=100, name="P1", url="https://sg.example.com/100", source_index=0),
        ImportedAsset(entity_id=100, name="P2", url="https://sg.example.com/100b", source_index=1),
    )
    selections = (
        AssetSelection(entity_id=100, included=True, animator_id=None, additional_ids=(), links_text=""),
        AssetSelection(entity_id=100, included=True, animator_id=None, additional_ids=(), links_text=""),
    )
    with pytest.raises(ValidationError):
        AssetDraft(draft_id="d1", assets=assets, group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=selections)


def test_asset_page_asset_name_visible_in_view() -> None:
    """Asset name appears somewhere in the rendered view."""
    assets = (ImportedAsset(entity_id=42, name="MY_UNIQUE_PROP_NAME", url="https://sg.example.com/42", source_index=0),)
    selections = (AssetSelection(entity_id=42, included=True, animator_id=None, additional_ids=(), links_text=""),)
    draft = AssetDraft(
        draft_id="d1", assets=assets, group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=selections
    )
    view = render_asset_page(draft, page_index=0)
    rendered = json.dumps(view)
    assert "MY_UNIQUE_PROP_NAME" in rendered


def test_asset_page_asset_url_visible_in_view() -> None:
    """Asset URL appears somewhere in the rendered view."""
    assets = (ImportedAsset(entity_id=42, name="Prop", url="https://sg.example.com/unique-url-42", source_index=0),)
    selections = (AssetSelection(entity_id=42, included=True, animator_id=None, additional_ids=(), links_text=""),)
    draft = AssetDraft(
        draft_id="d1", assets=assets, group_title="G", group_animator_id=None, group_additional_ids=(), group_links_text="", selections=selections
    )
    view = render_asset_page(draft, page_index=0)
    rendered = json.dumps(view)
    assert "unique-url-42" in rendered


def test_asset_page_group_title_escaped_in_view() -> None:
    """Group title with special chars is mrkdwn-escaped in the view."""
    draft = sample_draft(asset_count=1, group_title="Title & <stuff>")
    view = render_asset_page(draft, page_index=0)
    rendered = json.dumps(view)
    assert "&amp;" in rendered
    assert "&lt;" in rendered
    assert "&gt;" in rendered


def test_asset_page_json_serializable() -> None:
    """Asset page view is JSON-serializable."""
    json.dumps(render_asset_page(sample_draft(asset_count=5), page_index=0))


# ---------------------------------------------------------------------------
# decode_asset_page_state
# ---------------------------------------------------------------------------


def test_decode_user_select_empty_string_is_none() -> None:
    """Cleared users_select may submit empty string; treat as no selection."""
    state = {"values": {"group_animator": {"group_animator": {"selected_user": "  "}}}}
    decoded = decode_asset_page_state(state, page_index=0)
    assert decoded.group_animator_id is None


def test_asset_and_confirm_views_include_form_errors_notice_sink() -> None:
    """Trailing Notice input exists so validation can surface off-screen errors."""
    from red_team_prop_threader.views import BID_FORM_ERRORS, FORM_ERRORS_NOTICE, ConfirmationContext, with_form_error_notice, render_confirmation_view

    draft = sample_draft(asset_count=1)
    asset_view = render_asset_page(draft, 0)
    assert any(isinstance(b, dict) and b.get("block_id") == BID_FORM_ERRORS for b in asset_view["blocks"])  # type: ignore[union-attr]
    confirm = render_confirmation_view(
        ConfirmationContext(
            draft_id="d1",
            target_channel_id="C1",
            group_title="SEASON 31 PROP REQUEST THREADS",
            included_count=1,
            deduped_row_count=1,
            existing_duplicate_thread_count=0,
            existing_duplicate_thread_links=(),
            warnings=(),
        )
    )
    assert any(isinstance(b, dict) and b.get("block_id") == BID_FORM_ERRORS for b in confirm["blocks"])  # type: ignore[union-attr]
    noticed = with_form_error_notice({"group_animator": "nope"})
    assert noticed[BID_FORM_ERRORS] == FORM_ERRORS_NOTICE
    assert noticed["group_animator"] == "nope"


def test_decode_asset_page_strict_roundtrip() -> None:
    """Encode selections into a view then decode back to the same values."""
    assets = tuple(_asset(i) for i in range(3))
    selections = (
        AssetSelection(entity_id=100, included=True, animator_id="U_ANIM1", additional_ids=("U_ADD1",), links_text="A: https://a.example.com"),
        AssetSelection(entity_id=101, included=False, animator_id=None, additional_ids=(), links_text=""),
        AssetSelection(entity_id=102, included=True, animator_id="U_ANIM3", additional_ids=(), links_text=""),
    )
    draft = AssetDraft(
        draft_id="d1",
        assets=assets,
        group_title="SEASON 31",
        group_animator_id="U_GROUP_ANIM",
        group_additional_ids=("U_GROUP_ADD1",),
        group_links_text="Miro: https://miro.com/1",
        selections=selections,
        channel_members=(
            ChannelMemberOption("U_ANIM1", "Anim One (@uanim1)"),
            ChannelMemberOption("U_ANIM3", "Anim Three (@uanim3)"),
            ChannelMemberOption("U_ADD1", "Add One (@uadd1)"),
            ChannelMemberOption("U_GROUP_ANIM", "Group Animator (@ugroupanim)"),
            ChannelMemberOption("U_GROUP_ADD1", "Group Add (@ugroupadd1)"),
        ),
    )
    view = render_asset_page(draft, page_index=0)
    state = _extract_state_from_view(view)
    decoded = decode_asset_page_state(state, page_index=0)

    assert isinstance(decoded, DecodedAssetPage)
    assert decoded.page_index == 0
    assert decoded.group_title == "SEASON 31"
    assert decoded.group_animator_id == "U_GROUP_ANIM"
    assert decoded.group_additional_ids == ("U_GROUP_ADD1",)
    assert decoded.group_links_text == "Miro: https://miro.com/1"
    assert len(decoded.asset_states) == 3
    assert decoded.asset_states[0].entity_id == 100
    assert decoded.asset_states[0].included is True
    assert decoded.asset_states[0].animator_id == "U_ANIM1"
    assert decoded.asset_states[0].additional_ids == ("U_ADD1",)
    assert decoded.asset_states[0].links_text == "A: https://a.example.com"
    assert decoded.asset_states[1].entity_id == 101
    assert decoded.asset_states[1].included is False
    assert decoded.asset_states[1].animator_id is None
    assert decoded.asset_states[2].entity_id == 102
    assert decoded.asset_states[2].included is True


def test_decode_empty_values_returns_empty_assets() -> None:
    """Empty view state values returns decoded page with no asset states."""
    decoded = decode_asset_page_state({"values": {}}, page_index=0)
    assert decoded.asset_states == ()


def test_decode_checkbox_absent_means_not_included() -> None:
    """Missing include block in view state means the asset is not included."""
    # Build a state with no checkboxes key at all for the asset
    state = {
        "values": {
            BID_GROUP_TITLE: {BID_GROUP_TITLE: {"type": "plain_text_input", "value": "G"}},
            BID_GROUP_ANIMATOR: {BID_GROUP_ANIMATOR: {"type": "users_select", "selected_user": None}},
            BID_GROUP_ADDITIONAL: {BID_GROUP_ADDITIONAL: {"type": "multi_users_select", "selected_users": []}},
            BID_GROUP_LINKS: {BID_GROUP_LINKS: {"type": "plain_text_input", "value": ""}},
        }
    }
    decoded = decode_asset_page_state(state, page_index=0)
    assert decoded.asset_states == ()


def test_decode_checkbox_present_empty_means_not_included() -> None:
    """Empty selected_options in the include block means the asset is not included."""
    state: dict[str, Any] = {
        "values": {
            "asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": []}},
            "asset_100_animator": {"asset_100_animator": {"type": "users_select", "selected_user": None}},
            "asset_100_additional": {"asset_100_additional": {"type": "multi_users_select", "selected_users": []}},
            "asset_100_links": {"asset_100_links": {"type": "plain_text_input", "value": ""}},
        }
    }
    decoded = decode_asset_page_state(state, page_index=0)
    assert decoded.asset_states[0].included is False


def test_decode_checkbox_present_filled_means_included() -> None:
    """selected_options with 'included' value means the asset is included."""
    state: dict[str, Any] = {
        "values": {
            "asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": [{"value": "included"}]}},
            "asset_100_animator": {"asset_100_animator": {"type": "users_select", "selected_user": None}},
            "asset_100_additional": {"asset_100_additional": {"type": "multi_users_select", "selected_users": []}},
            "asset_100_links": {"asset_100_links": {"type": "plain_text_input", "value": ""}},
        }
    }
    decoded = decode_asset_page_state(state, page_index=0)
    assert decoded.asset_states[0].included is True


def test_decode_malformed_checkboxes_raises() -> None:
    """Wrong type for selected_options raises ValidationError."""
    state: dict[str, Any] = {"values": {"asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": "not-a-list"}}}}
    with pytest.raises(ValidationError):
        decode_asset_page_state(state, page_index=0)


def test_decode_malformed_users_select_raises() -> None:
    """Wrong structure in users_select block raises ValidationError."""
    state: dict[str, Any] = {
        "values": {
            "asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": []}},
            "asset_100_animator": {"asset_100_animator": {"type": "users_select", "selected_user": 12345}},  # int, not str/None
            "asset_100_additional": {"asset_100_additional": {"type": "multi_users_select", "selected_users": []}},
            "asset_100_links": {"asset_100_links": {"type": "plain_text_input", "value": ""}},
        }
    }
    with pytest.raises(ValidationError):
        decode_asset_page_state(state, page_index=0)


@pytest.mark.parametrize("selected_users", [None, pytest.param([], id="empty-list")])
def test_decode_multi_user_select_accepts_empty_values(selected_users: object) -> None:
    """Missing-like multi-select values decode as an empty tuple."""
    state: dict[str, Any] = {
        "values": {
            "asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": []}},
            "asset_100_additional": {"asset_100_additional": {"type": "multi_users_select", "selected_users": selected_users}},
        }
    }

    decoded = decode_asset_page_state(state, page_index=0)
    assert decoded.asset_states[0].additional_ids == ()


def test_decode_multi_user_select_accepts_missing_selected_users() -> None:
    """A missing selected_users key decodes as an empty tuple."""
    state: dict[str, Any] = {
        "values": {
            "asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": []}},
            "asset_100_additional": {"asset_100_additional": {"type": "multi_users_select"}},
        }
    }

    decoded = decode_asset_page_state(state, page_index=0)
    assert decoded.asset_states[0].additional_ids == ()


def test_decode_multi_user_select_rejects_non_list() -> None:
    """A non-list selected_users value raises a safe ValidationError."""
    state: dict[str, Any] = {
        "values": {
            "asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": []}},
            "asset_100_additional": {"asset_100_additional": {"type": "multi_users_select", "selected_users": "U_BAD"}},
        }
    }

    with pytest.raises(ValidationError, match="selected_users must be a list"):
        decode_asset_page_state(state, page_index=0)


def test_decode_multi_user_select_rejects_non_string_member() -> None:
    """A non-string selected_users member raises a safe ValidationError."""
    state: dict[str, Any] = {
        "values": {
            "asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": []}},
            "asset_100_additional": {"asset_100_additional": {"type": "multi_users_select", "selected_users": ["U_OK", 42]}},
        }
    }

    with pytest.raises(ValidationError, match="string user IDs"):
        decode_asset_page_state(state, page_index=0)


def test_decode_invalid_page_index_raises() -> None:
    """Page index outside {0,1} raises ValidationError."""
    with pytest.raises(ValidationError):
        decode_asset_page_state({"values": {}}, page_index=2)
    with pytest.raises(ValidationError):
        decode_asset_page_state({"values": {}}, page_index=-1)


def test_decode_preserves_asset_order() -> None:
    """Decoded asset states appear in block order (ShotGrid order)."""
    state: dict[str, Any] = {
        "values": {
            "asset_301_include": {"asset_301_include": {"type": "checkboxes", "selected_options": []}},
            "asset_301_animator": {"asset_301_animator": {"type": "users_select", "selected_user": None}},
            "asset_301_additional": {"asset_301_additional": {"type": "multi_users_select", "selected_users": []}},
            "asset_301_links": {"asset_301_links": {"type": "plain_text_input", "value": ""}},
            "asset_202_include": {"asset_202_include": {"type": "checkboxes", "selected_options": [{"value": "included"}]}},
            "asset_202_animator": {"asset_202_animator": {"type": "users_select", "selected_user": None}},
            "asset_202_additional": {"asset_202_additional": {"type": "multi_users_select", "selected_users": []}},
            "asset_202_links": {"asset_202_links": {"type": "plain_text_input", "value": ""}},
        }
    }
    decoded = decode_asset_page_state(state, page_index=0)
    assert [s.entity_id for s in decoded.asset_states] == [301, 202]


def test_decode_entity_id_comes_from_block_id_not_value() -> None:
    """Entity ID is extracted from the block_id key, not from user-editable values."""
    # entity_id 100 in block key; any value in the element
    state: dict[str, Any] = {
        "values": {
            "asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": [{"value": "included"}]}},
            "asset_100_animator": {"asset_100_animator": {"type": "users_select", "selected_user": "U_CORRECT"}},
            "asset_100_additional": {"asset_100_additional": {"type": "multi_users_select", "selected_users": []}},
            "asset_100_links": {"asset_100_links": {"type": "plain_text_input", "value": ""}},
        }
    }
    decoded = decode_asset_page_state(state, page_index=0)
    assert decoded.asset_states[0].entity_id == 100  # from block key, not value


def test_decode_repeated_asset_fields_form_one_asset_state() -> None:
    """The four distinct field keys for one entity decode to one asset state."""
    state: dict[str, Any] = {
        "values": {
            "asset_100_include": {"asset_100_include": {"type": "checkboxes", "selected_options": []}},
            "asset_100_animator": {"asset_100_animator": {"type": "users_select", "selected_user": None}},
            "asset_100_additional": {"asset_100_additional": {"type": "multi_users_select", "selected_users": []}},
            "asset_100_links": {"asset_100_links": {"type": "plain_text_input", "value": ""}},
        }
    }
    decoded = decode_asset_page_state(state, page_index=0)
    assert len(decoded.asset_states) == 1


# ---------------------------------------------------------------------------
# confirmation view
# ---------------------------------------------------------------------------


def test_confirmation_view_type_is_modal() -> None:
    """Confirmation view is a modal."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C_CHANNEL",
        group_title="SEASON 31 PROP REQUEST THREADS",
        included_count=5,
        deduped_row_count=5,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    view = render_confirmation_view(ctx)
    assert view["type"] == "modal"


def test_confirmation_view_has_submit_button() -> None:
    """Confirmation view has a submit button (not action-only)."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C_CHANNEL",
        group_title="G",
        included_count=3,
        deduped_row_count=3,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    view = render_confirmation_view(ctx)
    assert "submit" in view


def test_confirmation_view_private_metadata_is_draft_id() -> None:
    """Confirmation view private_metadata is the draft ID."""
    ctx = ConfirmationContext(
        draft_id="conf-draft-42",
        target_channel_id="C1",
        group_title="G",
        included_count=1,
        deduped_row_count=1,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    view = render_confirmation_view(ctx)
    assert view["private_metadata"] == "conf-draft-42"


def test_confirmation_view_shows_group_title() -> None:
    """Group title appears in the confirmation view."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C1",
        group_title="SEASON 31 UNIQUE TITLE",
        included_count=1,
        deduped_row_count=1,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    view = render_confirmation_view(ctx)
    rendered = json.dumps(view)
    assert "SEASON 31 UNIQUE TITLE" in rendered


def test_confirmation_group_title_is_required_editable_input() -> None:
    """Confirmation exposes a stable required input prefilled with the group title."""
    context = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C1",
        group_title="SEASON 31 UNIQUE TITLE",
        included_count=1,
        deduped_row_count=1,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    view = render_confirmation_view(context)
    title = next(block for block in view["blocks"] if block.get("block_id") == BID_CONFIRM_GROUP_TITLE)  # type: ignore[union-attr]

    assert title["type"] == "input"
    assert title["optional"] is False
    assert title["element"]["type"] == "plain_text_input"  # type: ignore[index]
    assert title["element"]["action_id"] == AID_CONFIRM_GROUP_TITLE  # type: ignore[index]
    assert title["element"]["initial_value"] == context.group_title  # type: ignore[index]


def test_confirmation_view_shows_included_count() -> None:
    """Included asset count appears in the confirmation view."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C1",
        group_title="G",
        included_count=7,
        deduped_row_count=7,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    view = render_confirmation_view(ctx)
    rendered = json.dumps(view)
    assert "7" in rendered


def test_confirmation_view_shows_duplicate_threads() -> None:
    """Existing duplicate thread count and links appear when non-zero."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C1",
        group_title="G",
        included_count=3,
        deduped_row_count=2,
        existing_duplicate_thread_count=2,
        existing_duplicate_thread_links=("https://slack.com/thread/1", "https://slack.com/thread/2"),
        warnings=(),
    )
    view = render_confirmation_view(ctx)
    rendered = json.dumps(view)
    assert "2" in rendered
    assert "slack.com/thread/1" in rendered


def test_confirmation_view_no_duplicate_section_when_zero() -> None:
    """No duplicate thread section when existing_duplicate_thread_count is 0."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C1",
        group_title="G",
        included_count=3,
        deduped_row_count=3,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    view = render_confirmation_view(ctx)
    rendered = json.dumps(view)
    assert "slack.com/thread" not in rendered


def test_confirmation_view_shows_warnings() -> None:
    """Warnings appear in the confirmation view."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C1",
        group_title="G",
        included_count=1,
        deduped_row_count=1,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=("UNIQUE_WARNING_MESSAGE_XYZ",),
    )
    view = render_confirmation_view(ctx)
    rendered = json.dumps(view)
    assert "UNIQUE_WARNING_MESSAGE_XYZ" in rendered


def test_confirmation_view_contains_cancellation_disclaimer() -> None:
    """Confirmation view warns that processing cannot be cancelled."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C1",
        group_title="G",
        included_count=1,
        deduped_row_count=1,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    view = render_confirmation_view(ctx)
    rendered = json.dumps(view)
    # some form of "cannot be cancelled" or "cannot cancel" text
    assert "cancel" in rendered.lower() or "cannot" in rendered.lower()


def test_confirmation_view_all_blocks_have_block_id() -> None:
    """Every block in the confirmation view has a block_id."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C1",
        group_title="G",
        included_count=1,
        deduped_row_count=1,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    view = render_confirmation_view(ctx)
    for block in view["blocks"]:  # type: ignore[union-attr]
        assert "block_id" in block, f"block missing block_id: {block!r}"


def test_confirmation_view_json_serializable() -> None:
    """Confirmation view is JSON-serializable."""
    ctx = ConfirmationContext(
        draft_id="d1",
        target_channel_id="C1",
        group_title="G",
        included_count=1,
        deduped_row_count=1,
        existing_duplicate_thread_count=0,
        existing_duplicate_thread_links=(),
        warnings=(),
    )
    json.dumps(render_confirmation_view(ctx))


# ---------------------------------------------------------------------------
# mrkdwn escaping in views
# ---------------------------------------------------------------------------


def test_mrkdwn_escape_ampersand() -> None:
    """Ampersand in user text is escaped to &amp; in the rendered view."""
    ctx = CanvasPreflightContext(draft_id="d1", canvas_name="R&D Canvas", channel_id="C1")
    view = render_canvas_preflight_view(ctx)
    rendered = json.dumps(view)
    assert "&amp;" in rendered


def test_mrkdwn_escape_lt() -> None:
    """Less-than in user text is escaped to &lt; in the rendered view."""
    ctx = CanvasPreflightContext(draft_id="d1", canvas_name="Canvas <test>", channel_id="C1")
    view = render_canvas_preflight_view(ctx)
    rendered = json.dumps(view)
    assert "&lt;" in rendered


def test_mrkdwn_escape_gt() -> None:
    """Greater-than in user text is escaped to &gt; in the rendered view."""
    ctx = CanvasPreflightContext(draft_id="d1", canvas_name="Canvas >test<", channel_id="C1")
    view = render_canvas_preflight_view(ctx)
    rendered = json.dumps(view)
    assert "&gt;" in rendered
