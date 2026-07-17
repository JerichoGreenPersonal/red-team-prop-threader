"""Slack Block Kit modal view renderers and state decoders for prop-threader."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from datetime import datetime, timezone
from dataclasses import dataclass

from red_team_prop_threader._errors import ValidationError


if TYPE_CHECKING:
    from red_team_prop_threader.domain import ImportedAsset


__all__ = (
    "AID_CANVAS_CREATE",
    "AID_CANVAS_DECLINE",
    "AID_CANVAS_RENAME",
    "AID_IMPORT_RESUME",
    "AID_IMPORT_START_OVER",
    "AID_NAV_BACK",
    "AID_NAV_CONFIRM",
    "AID_NAV_NEXT",
    "BID_GROUP_ADDITIONAL",
    "BID_GROUP_ANIMATOR",
    "BID_GROUP_LINKS",
    "BID_GROUP_TITLE",
    "AssetDraft",
    "AssetSelection",
    "CanvasPreflightContext",
    "ConfirmationContext",
    "DecodedAssetPage",
    "DecodedAssetState",
    "ImportContext",
    "decode_asset_page_state",
    "render_asset_page",
    "render_canvas_preflight_view",
    "render_confirmation_view",
    "render_import_view",
)

# ---------------------------------------------------------------------------
# stable action ID constants
# ---------------------------------------------------------------------------

AID_CANVAS_CREATE = "canvas_create"
AID_CANVAS_RENAME = "canvas_rename"
AID_CANVAS_DECLINE = "canvas_decline"
AID_IMPORT_RESUME = "import_resume"
AID_IMPORT_START_OVER = "import_start_over"
AID_NAV_BACK = "nav_back"
AID_NAV_NEXT = "nav_next"
AID_NAV_CONFIRM = "nav_confirm"

# ---------------------------------------------------------------------------
# stable block ID constants for group fields
# ---------------------------------------------------------------------------

BID_GROUP_TITLE = "group_title"
BID_GROUP_ANIMATOR = "group_animator"
BID_GROUP_ADDITIONAL = "group_additional"
BID_GROUP_LINKS = "group_links"

# ---------------------------------------------------------------------------
# Slack limits
# ---------------------------------------------------------------------------

_PAGE_SIZE = 15
_MAX_ASSETS = 30
_BLOCK_MAX = 100
_MODAL_TITLE_MAX = 24
_HEADER_TEXT_MAX = 150
_SECTION_TEXT_MAX = 3000
_BUTTON_TEXT_MAX = 75
_PLAIN_TEXT_INPUT_MAX = 3000
_DRAFT_ID_MAX = 255

# pattern to find asset_include block ids, used in decode
_ASSET_INCLUDE_RE = re.compile(r"^asset_(\d+)_include$")

# ---------------------------------------------------------------------------
# input context dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanvasPreflightContext:
    """context for the canvas preflight confirmation modal.

    Args:
        draft_id: opaque draft identifier stored in private_metadata.
        canvas_name: proposed or existing canvas name to display.
        channel_id: target channel ID for display purposes.
    """

    draft_id: str
    canvas_name: str
    channel_id: str


@dataclass(frozen=True, slots=True)
class ImportContext:
    """context for the import-from-ShotGrid modal.

    Args:
        draft_id: opaque draft identifier stored in private_metadata.
        prefilled_url: optional ShotGrid page URL to prefill in the input.
        existing_draft_id: if set, a resume/start-over prompt is shown.
        import_snapshot_ts: unix timestamp of the existing draft's import snapshot.
    """

    draft_id: str
    prefilled_url: str | None = None
    existing_draft_id: str | None = None
    import_snapshot_ts: int | None = None


@dataclass(frozen=True, slots=True)
class AssetSelection:
    """immutable per-asset form selection captured from a modal page.

    Args:
        entity_id: ShotGrid entity ID; must match the paired ImportedAsset.
        included: whether this asset is flagged for thread creation.
        animator_id: Slack user ID of the selected animator, or None.
        additional_ids: ordered Slack user IDs for additional people.
        links_text: raw multiline supporting-link text entered by the user.
    """

    entity_id: int
    included: bool
    animator_id: str | None
    additional_ids: tuple[str, ...]
    links_text: str


@dataclass(frozen=True, slots=True)
class AssetDraft:
    """immutable draft holding all assets and their current form selections.

    Args:
        draft_id: opaque draft identifier (bounded string).
        assets: all imported assets in ShotGrid source_index order.
        group_title: current group title text.
        group_animator_id: Slack user ID of the group animator, or None.
        group_additional_ids: ordered Slack user IDs for group additional people.
        group_links_text: raw multiline supporting-link text for the group.
        selections: per-asset selections; must be parallel to assets.

    Raises:
        ValidationError: if asset count exceeds 30, entity IDs are duplicated, or
            selections do not match assets.
    """

    draft_id: str
    assets: tuple[ImportedAsset, ...]
    group_title: str
    group_animator_id: str | None
    group_additional_ids: tuple[str, ...]
    group_links_text: str
    selections: tuple[AssetSelection, ...]

    def __post_init__(self) -> None:
        """Validate constraints on construction."""
        if len(self.assets) > _MAX_ASSETS:
            raise ValidationError(f"draft has {len(self.assets)} assets; maximum is {_MAX_ASSETS}")
        entity_ids = [a.entity_id for a in self.assets]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValidationError("draft contains duplicate asset entity IDs")
        if len(self.selections) != len(self.assets):
            raise ValidationError(f"selections length {len(self.selections)} does not match assets length {len(self.assets)}")
        selection_ids = [s.entity_id for s in self.selections]
        if selection_ids != entity_ids:
            raise ValidationError("selection entity_ids do not match asset entity_ids in order")


# ---------------------------------------------------------------------------
# decoded state dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecodedAssetState:
    """immutable decoded state for one asset extracted from Slack view_state.

    Args:
        entity_id: ShotGrid entity ID inferred from the block ID.
        included: true when the include checkbox was checked.
        animator_id: selected Slack user ID, or None.
        additional_ids: selected Slack user IDs for additional people.
        links_text: raw supporting-link text value.
    """

    entity_id: int
    included: bool
    animator_id: str | None
    additional_ids: tuple[str, ...]
    links_text: str


@dataclass(frozen=True, slots=True)
class DecodedAssetPage:
    """immutable decoded page state from a Slack asset-page modal submission.

    Args:
        page_index: the page index (0 or 1) this state corresponds to.
        group_title: decoded group title text.
        group_animator_id: decoded group animator Slack user ID, or None.
        group_additional_ids: decoded group additional Slack user IDs.
        group_links_text: decoded group supporting-link text.
        asset_states: decoded per-asset states in block order.
    """

    page_index: int
    group_title: str
    group_animator_id: str | None
    group_additional_ids: tuple[str, ...]
    group_links_text: str
    asset_states: tuple[DecodedAssetState, ...]


# ---------------------------------------------------------------------------
# confirmation context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConfirmationContext:
    """context for the final confirmation modal before posting threads.

    Args:
        draft_id: opaque draft identifier stored in private_metadata.
        target_channel_id: Slack channel ID where threads will be posted.
        group_title: normalized group title.
        included_count: number of assets marked for inclusion.
        deduped_row_count: number of unique deduplicated rows.
        existing_duplicate_thread_count: number of pre-existing threads that will
            be replaced.
        existing_duplicate_thread_links: Slack permalinks to existing threads.
        warnings: zero or more user-visible warning strings.
    """

    draft_id: str
    target_channel_id: str
    group_title: str
    included_count: int
    deduped_row_count: int
    existing_duplicate_thread_count: int
    existing_duplicate_thread_links: tuple[str, ...]
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# private block-builder helpers
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    """Escape user-controlled text for Slack mrkdwn.

    Args:
        text: raw user-supplied string.

    Returns:
        str: string with &, <, and > replaced by HTML entities.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _plain(text: str, max_len: int = 2000) -> dict[str, object]:
    """Return a Slack plain_text object, truncating if necessary.

    Args:
        text: text content (not escaped; no mrkdwn interpretation).
        max_len: maximum character length allowed by the field.

    Returns:
        dict[str, object]: Slack plain_text composition object.
    """
    if len(text) > max_len:
        text = text[: max_len - 1] + "\u2026"
    return {"type": "plain_text", "text": text}


def _mrkdwn(text: str) -> dict[str, object]:
    """Return a Slack mrkdwn text object.

    Args:
        text: mrkdwn-formatted string; caller must escape user-supplied parts.

    Returns:
        dict[str, object]: Slack mrkdwn composition object.
    """
    return {"type": "mrkdwn", "text": text}


def _section(bid: str, text: dict[str, object]) -> dict[str, object]:
    """Return a Slack section block.

    Args:
        bid: stable block_id.
        text: composition text object.

    Returns:
        dict[str, object]: Slack section block.
    """
    return {"type": "section", "block_id": bid, "text": text}


def _context_block(bid: str, elements: list[dict[str, object]]) -> dict[str, object]:
    """Return a Slack context block.

    Args:
        bid: stable block_id.
        elements: list of composition text objects.

    Returns:
        dict[str, object]: Slack context block.
    """
    return {"type": "context", "block_id": bid, "elements": elements}


def _input_block(bid: str, label: str, element: dict[str, object], optional: bool = False, hint: str | None = None) -> dict[str, object]:
    """Return a Slack input block.

    Args:
        bid: stable block_id (also used as action_id of the element).
        label: plain-text label for the input.
        element: Slack interactive element dict.
        optional: whether the input may be left empty.
        hint: optional plain-text hint shown below the input.

    Returns:
        dict[str, object]: Slack input block.
    """
    block: dict[str, object] = {"type": "input", "block_id": bid, "label": _plain(label), "element": element, "optional": optional}
    if hint is not None:
        block["hint"] = _plain(hint, max_len=2000)
    return block


def _actions_block(bid: str, elements: list[dict[str, object]]) -> dict[str, object]:
    """Return a Slack actions block.

    Args:
        bid: stable block_id.
        elements: list of interactive element dicts.

    Returns:
        dict[str, object]: Slack actions block.
    """
    return {"type": "actions", "block_id": bid, "elements": elements}


def _button(text: str, action_id: str, value: str = "", style: str | None = None) -> dict[str, object]:
    """Return a Slack button element.

    Args:
        text: button label (plain text, max 75 chars).
        action_id: stable action ID for listener dispatch.
        value: optional opaque payload value.
        style: optional style string ('primary' or 'danger').

    Returns:
        dict[str, object]: Slack button element.
    """
    btn: dict[str, object] = {"type": "button", "text": _plain(text, max_len=_BUTTON_TEXT_MAX), "action_id": action_id, "value": value}
    if style is not None:
        btn["style"] = style
    return btn


def _users_select(action_id: str, placeholder: str, initial_user: str | None) -> dict[str, object]:
    """Return a Slack users_select element.

    Args:
        action_id: stable action ID.
        placeholder: placeholder text.
        initial_user: Slack user ID to pre-select, or None.

    Returns:
        dict[str, object]: Slack users_select element.
    """
    elem: dict[str, object] = {"type": "users_select", "action_id": action_id, "placeholder": _plain(placeholder)}
    if initial_user is not None:
        elem["initial_user"] = initial_user
    return elem


def _multi_users_select(action_id: str, placeholder: str, initial_users: tuple[str, ...]) -> dict[str, object]:
    """Return a Slack multi_users_select element.

    Args:
        action_id: stable action ID.
        placeholder: placeholder text.
        initial_users: Slack user IDs to pre-select.

    Returns:
        dict[str, object]: Slack multi_users_select element.
    """
    elem: dict[str, object] = {"type": "multi_users_select", "action_id": action_id, "placeholder": _plain(placeholder)}
    if initial_users:
        elem["initial_users"] = list(initial_users)
    return elem


def _plain_text_input(action_id: str, placeholder: str, initial_value: str | None, multiline: bool = False) -> dict[str, object]:
    """Return a Slack plain_text_input element.

    Args:
        action_id: stable action ID.
        placeholder: placeholder text.
        initial_value: pre-filled text value, or None.
        multiline: whether the input is multi-line.

    Returns:
        dict[str, object]: Slack plain_text_input element.
    """
    elem: dict[str, object] = {"type": "plain_text_input", "action_id": action_id, "placeholder": _plain(placeholder), "multiline": multiline}
    if initial_value:
        elem["initial_value"] = initial_value
    return elem


def _checkboxes(action_id: str, included: bool) -> dict[str, object]:
    """Return a Slack checkboxes element for the asset include toggle.

    Args:
        action_id: stable action ID.
        included: whether the include option should be pre-checked.

    Returns:
        dict[str, object]: Slack checkboxes element.
    """
    option: dict[str, object] = {"text": _plain("Include"), "value": "included"}
    elem: dict[str, object] = {"type": "checkboxes", "action_id": action_id, "options": [option]}
    if included:
        elem["initial_options"] = [option]
    return elem


def _validate_draft_id(draft_id: str) -> None:
    """Validate that draft_id is non-empty and within the maximum length.

    Args:
        draft_id: the draft identifier to validate.

    Raises:
        ValidationError: if draft_id is empty or exceeds the maximum length.
    """
    if not draft_id:
        raise ValidationError("draft_id must not be empty")
    if len(draft_id) > _DRAFT_ID_MAX:
        raise ValidationError(f"draft_id length {len(draft_id)} exceeds maximum {_DRAFT_ID_MAX}")


def _page_count(total: int) -> int:
    """Return the number of pages required for a given asset count.

    Args:
        total: number of assets.

    Returns:
        int: number of pages (minimum 1).
    """
    return max(1, -(-total // _PAGE_SIZE))  # ceiling division


def _page_assets(assets: tuple[ImportedAsset, ...], page_index: int) -> tuple[ImportedAsset, ...]:
    """Slice assets for the given page index.

    Args:
        assets: all assets in source order.
        page_index: zero-based page index.

    Returns:
        tuple[ImportedAsset, ...]: the subset of assets for this page.
    """
    start = page_index * _PAGE_SIZE
    return assets[start : start + _PAGE_SIZE]


def _page_selections(selections: tuple[AssetSelection, ...], page_index: int) -> tuple[AssetSelection, ...]:
    """Slice selections to match the page's asset subset.

    Args:
        selections: all selections in source order.
        page_index: zero-based page index.

    Returns:
        tuple[AssetSelection, ...]: selections for assets on this page.
    """
    start = page_index * _PAGE_SIZE
    return selections[start : start + _PAGE_SIZE]


def _group_blocks(draft: AssetDraft) -> list[dict[str, object]]:
    """Build the group-field input blocks that appear once per page.

    Args:
        draft: the current asset draft.

    Returns:
        list[dict[str, object]]: group title, animator, additional, and links blocks.
    """
    return [
        _input_block(BID_GROUP_TITLE, "Group title", _plain_text_input(BID_GROUP_TITLE, "SEASON N PROP REQUEST THREADS", draft.group_title or None)),
        _input_block(BID_GROUP_ANIMATOR, "Group animator", _users_select(BID_GROUP_ANIMATOR, "Select animator", draft.group_animator_id)),
        _input_block(
            BID_GROUP_ADDITIONAL,
            "Group additional people",
            _multi_users_select(BID_GROUP_ADDITIONAL, "Select additional people", draft.group_additional_ids),
            optional=True,
        ),
        _input_block(
            BID_GROUP_LINKS,
            "Group supporting links",
            _plain_text_input(BID_GROUP_LINKS, "Label: https://...", draft.group_links_text or None, multiline=True),
            optional=True,
        ),
    ]


def _asset_blocks(asset: ImportedAsset, sel: AssetSelection) -> list[dict[str, object]]:
    """Build the four input blocks and one context block for a single asset.

    Args:
        asset: the ImportedAsset for display.
        sel: the current AssetSelection for pre-filling initial values.

    Returns:
        list[dict[str, object]]: context block followed by 4 input blocks.
    """
    eid = asset.entity_id
    ctx_bid = f"ctx_asset_{eid}"
    return [
        _context_block(ctx_bid, [_mrkdwn(f"<{asset.url}|{_escape(asset.name)}> \u00b7 ShotGrid ID: {eid}")]),
        _input_block(f"asset_{eid}_include", f"{_escape(asset.name)} (ID: {eid})", _checkboxes(f"asset_{eid}_include", sel.included), optional=True),
        _input_block(f"asset_{eid}_animator", "Animator", _users_select(f"asset_{eid}_animator", "Select animator", sel.animator_id), optional=True),
        _input_block(
            f"asset_{eid}_additional",
            "Additional people",
            _multi_users_select(f"asset_{eid}_additional", "Select additional people", sel.additional_ids),
            optional=True,
        ),
        _input_block(
            f"asset_{eid}_links",
            "Supporting links",
            _plain_text_input(f"asset_{eid}_links", "Label: https://...", sel.links_text or None, multiline=True),
            optional=True,
        ),
    ]


# ---------------------------------------------------------------------------
# public render functions
# ---------------------------------------------------------------------------


def render_canvas_preflight_view(context: CanvasPreflightContext) -> dict[str, object]:
    """Render the canvas preflight confirmation modal.

    Presents create/rename/decline actions with accessible explanatory text.
    No mutation is implied until the user confirms.

    Args:
        context: preflight context including canvas name and draft ID.

    Returns:
        dict[str, object]: Slack modal view payload.

    Raises:
        ValidationError: if draft_id exceeds the maximum length.
    """
    _validate_draft_id(context.draft_id)
    escaped_name = _escape(context.canvas_name)
    blocks: list[dict[str, object]] = [
        _section(
            "preflight_intro",
            _mrkdwn(f"*An existing channel canvas was found:* {escaped_name}\n\nChoose how to proceed before any changes are made to the channel."),
        ),
        _actions_block(
            "preflight_actions",
            [
                _button("Create New Canvas", AID_CANVAS_CREATE, value=context.draft_id, style="primary"),
                _button("Rename Existing", AID_CANVAS_RENAME, value=context.draft_id),
                _button("Cancel / Decline", AID_CANVAS_DECLINE, value=context.draft_id, style="danger"),
            ],
        ),
    ]
    return {"type": "modal", "title": _plain("Canvas Check"), "close": _plain("Cancel"), "private_metadata": context.draft_id, "blocks": blocks}


def render_import_view(context: ImportContext) -> dict[str, object]:
    """Render the import-from-ShotGrid URL modal.

    Optionally shows a resume/start-over prompt when an existing draft is present.

    Args:
        context: import context with optional prefilled URL and existing-draft info.

    Returns:
        dict[str, object]: Slack modal view payload.

    Raises:
        ValidationError: if draft_id exceeds the maximum length.
    """
    _validate_draft_id(context.draft_id)
    blocks: list[dict[str, object]] = [
        _input_block("import_url", "ShotGrid page URL", _plain_text_input("import_url", "https://sg.example.com/page/...", context.prefilled_url))
    ]

    if context.existing_draft_id is not None:
        ts = context.import_snapshot_ts
        if ts is not None:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            time_str = dt.strftime("%Y-%m-%d %H:%M UTC")
        else:
            time_str = "unknown time"
        blocks.append(
            _section(
                "import_existing_draft",
                _mrkdwn(f"*Existing draft found* \u2014 imported {time_str}.\nResume where you left off, or start over with a fresh import."),
            )
        )
        blocks.append(
            _actions_block(
                "import_resume_actions",
                [
                    _button("Resume", AID_IMPORT_RESUME, value=context.existing_draft_id, style="primary"),
                    _button("Start Over", AID_IMPORT_START_OVER, value=context.existing_draft_id, style="danger"),
                ],
            )
        )

    return {
        "type": "modal",
        "title": _plain("Import Assets"),
        "submit": _plain("Import"),
        "close": _plain("Cancel"),
        "private_metadata": context.draft_id,
        "blocks": blocks,
    }


def render_asset_page(draft: AssetDraft, page_index: int) -> dict[str, object]:
    """Render one paginated asset-detail modal page for a draft.

    At most 15 assets and 100 blocks are rendered per page. Group fields
    appear once per page. Navigation buttons adapt to the page position.

    Args:
        draft: the current draft with all assets and form selections.
        page_index: zero-based page index (0 or 1).

    Returns:
        dict[str, object]: Slack modal view payload.

    Raises:
        ValidationError: if page_index is invalid, or the draft violates limits.
    """
    _validate_draft_id(draft.draft_id)
    if page_index not in (0, 1):
        raise ValidationError(f"page_index must be 0 or 1; got {page_index}")
    total = len(draft.assets)
    pages = _page_count(total)
    if page_index >= pages:
        raise ValidationError(f"page_index {page_index} is out of range for {total} assets ({pages} page(s))")

    page_assets = _page_assets(draft.assets, page_index)
    page_sels = _page_selections(draft.selections, page_index)

    total_pages = _page_count(total)
    page_label = (
        f"Page {page_index + 1} of {total_pages} \u2014 {_escape(draft.group_title)}" if draft.group_title else f"Page {page_index + 1} of {total_pages}"
    )

    blocks: list[dict[str, object]] = [_section("page_intro", _mrkdwn(page_label))]
    blocks.extend(_group_blocks(draft))

    for asset, sel in zip(page_assets, page_sels, strict=True):
        blocks.extend(_asset_blocks(asset, sel))

    # navigation actions
    nav_elements: list[dict[str, object]] = []
    if page_index > 0:
        nav_elements.append(_button("Back", AID_NAV_BACK, value=draft.draft_id))
    if page_index < total_pages - 1:
        nav_elements.append(_button("Next", AID_NAV_NEXT, value=draft.draft_id, style="primary"))
    else:
        nav_elements.append(_button("Confirm", AID_NAV_CONFIRM, value=draft.draft_id, style="primary"))

    blocks.append(_actions_block("nav_actions", nav_elements))

    if len(blocks) > _BLOCK_MAX:
        raise ValidationError(f"rendered {len(blocks)} blocks; maximum is {_BLOCK_MAX}")

    return {"type": "modal", "title": _plain(f"Assets p.{page_index + 1}"), "close": _plain("Cancel"), "private_metadata": draft.draft_id, "blocks": blocks}


def render_confirmation_view(context: ConfirmationContext) -> dict[str, object]:
    """Render the confirmation modal shown before posting threads.

    Presents the target channel, group title, included count, deduplication
    summary, any existing duplicate threads, warnings, and a non-cancellation
    disclaimer.

    Args:
        context: all confirmation details.

    Returns:
        dict[str, object]: Slack modal view payload.

    Raises:
        ValidationError: if draft_id exceeds the maximum length.
    """
    _validate_draft_id(context.draft_id)
    escaped_title = _escape(context.group_title)
    blocks: list[dict[str, object]] = [
        _section("conf_channel", _mrkdwn(f"*Target channel:* <#{context.target_channel_id}>")),
        _section("conf_title", _mrkdwn(f"*Group title:* {escaped_title}")),
        _section("conf_counts", _mrkdwn(f"*{context.included_count}* asset(s) included \u2014 *{context.deduped_row_count}* unique deduplicated row(s).")),
    ]

    if context.existing_duplicate_thread_count > 0:
        link_lines = "\n".join(f"\u2022 <{url}|View thread>" for url in context.existing_duplicate_thread_links)
        blocks.append(_section("conf_duplicates", _mrkdwn(f"*{context.existing_duplicate_thread_count}* existing thread(s) will be replaced:\n{link_lines}")))

    for i, warning in enumerate(context.warnings):
        blocks.append(_section(f"conf_warning_{i}", _mrkdwn(f":warning: {_escape(warning)}")))

    blocks.append(_section("conf_disclaimer", _mrkdwn("*Note:* Once confirmed, thread posting cannot be cancelled. The process runs as a background job.")))

    return {
        "type": "modal",
        "title": _plain("Confirm"),
        "submit": _plain("Post Threads"),
        "close": _plain("Cancel"),
        "private_metadata": context.draft_id,
        "blocks": blocks,
    }


# ---------------------------------------------------------------------------
# decode function
# ---------------------------------------------------------------------------


def decode_asset_page_state(view_state: dict[str, object], page_index: int) -> DecodedAssetPage:
    """Decode a Slack modal view_state into a structured asset page state.

    Entity identity is read from validated block IDs, never from user-editable
    value fields. Checkbox absence is treated as not-included; malformed types
    raise ValidationError.

    Args:
        view_state: the ``state`` object from a Slack view payload, containing
            a ``values`` mapping of block_id → action_id → field dict.
        page_index: the expected page index (0 or 1) for the decoded state.

    Returns:
        DecodedAssetPage: structured decoded page state.

    Raises:
        ValidationError: if page_index is invalid, the view_state is structurally
            malformed, or field types within known asset blocks are unexpected.
    """
    if page_index not in (0, 1):
        raise ValidationError(f"page_index must be 0 or 1; got {page_index}")

    if not isinstance(view_state, dict):
        raise ValidationError("view_state must be a dict")
    values_raw = view_state.get("values")
    if not isinstance(values_raw, dict):
        raise ValidationError("view_state must contain a 'values' dict")
    # narrow the type explicitly; keys from Slack are always strings
    values: dict[str, object] = {str(k): v for k, v in values_raw.items()}

    # decode group fields (absent keys default to empty/None)
    group_title = _decode_plain_text(values, BID_GROUP_TITLE)
    group_animator_id = _decode_user_select(values, BID_GROUP_ANIMATOR)
    group_additional_ids = _decode_multi_user_select(values, BID_GROUP_ADDITIONAL)
    group_links_text = _decode_plain_text(values, BID_GROUP_LINKS)

    # collect asset entity IDs from _include block keys, in dict-insertion order
    seen_ids: set[int] = set()
    ordered_ids: list[int] = []
    for bid in values:
        m = _ASSET_INCLUDE_RE.match(bid)
        if m:
            eid = int(m.group(1))
            if eid in seen_ids:
                raise ValidationError(f"duplicate entity ID {eid} in view_state")
            seen_ids.add(eid)
            ordered_ids.append(eid)

    asset_states: list[DecodedAssetState] = []
    for eid in ordered_ids:
        included = _decode_checkbox(values, f"asset_{eid}_include", eid)
        animator_id = _decode_user_select(values, f"asset_{eid}_animator")
        additional_ids = _decode_multi_user_select(values, f"asset_{eid}_additional")
        links_text = _decode_plain_text(values, f"asset_{eid}_links")
        asset_states.append(DecodedAssetState(entity_id=eid, included=included, animator_id=animator_id, additional_ids=additional_ids, links_text=links_text))

    return DecodedAssetPage(
        page_index=page_index,
        group_title=group_title,
        group_animator_id=group_animator_id,
        group_additional_ids=group_additional_ids,
        group_links_text=group_links_text,
        asset_states=tuple(asset_states),
    )


def _decode_plain_text(values: dict[str, object], bid: str) -> str:
    """Extract a plain_text_input value from view state values.

    Args:
        values: the view_state.values dict.
        bid: block ID and action ID to look up.

    Returns:
        str: the text value, or empty string if absent.
    """
    block_entry = values.get(bid)
    if block_entry is None:
        return ""
    if not isinstance(block_entry, dict):
        return ""
    action_entry = block_entry.get(bid)
    if not isinstance(action_entry, dict):
        return ""
    val = action_entry.get("value")
    return val if isinstance(val, str) else ""


def _decode_user_select(values: dict[str, object], bid: str) -> str | None:
    """Extract a users_select selected_user from view state values.

    Args:
        values: the view_state.values dict.
        bid: block ID and action ID to look up.

    Returns:
        str | None: the selected user ID, or None if absent.

    Raises:
        ValidationError: if selected_user is present but not a string or None.
    """
    block_entry = values.get(bid)
    if block_entry is None:
        return None
    if not isinstance(block_entry, dict):
        return None
    action_entry = block_entry.get(bid)
    if not isinstance(action_entry, dict):
        return None
    val = action_entry.get("selected_user")
    if val is None:
        return None
    if not isinstance(val, str):
        raise ValidationError(f"block '{bid}': selected_user must be a string or None, got {type(val).__name__}")
    return val


def _decode_multi_user_select(values: dict[str, object], bid: str) -> tuple[str, ...]:
    """Extract a multi_users_select selected_users from view state values.

    Args:
        values: the view_state.values dict.
        bid: block ID and action ID to look up.

    Returns:
        tuple[str, ...]: selected user IDs, or empty tuple if absent.
    """
    block_entry = values.get(bid)
    if block_entry is None:
        return ()
    if not isinstance(block_entry, dict):
        return ()
    action_entry = block_entry.get(bid)
    if not isinstance(action_entry, dict):
        return ()
    val = action_entry.get("selected_users")
    if not isinstance(val, list):
        return ()
    return tuple(str(u) for u in val if isinstance(u, str))


def _decode_checkbox(values: dict[str, object], bid: str, entity_id: int) -> bool:
    """Extract the include/exclude state from a checkboxes block.

    Absence of the block key is treated as not included (no user interaction).
    A present but empty selected_options means explicitly unchecked.

    Args:
        values: the view_state.values dict.
        bid: block ID and action ID to look up.
        entity_id: the asset entity ID (used in error messages).

    Returns:
        bool: True if the 'included' option is selected.

    Raises:
        ValidationError: if selected_options has an unexpected type.
    """
    block_entry = values.get(bid)
    if block_entry is None:
        return False
    if not isinstance(block_entry, dict):
        raise ValidationError(f"asset {entity_id}: include block entry is malformed")
    action_entry = block_entry.get(bid)
    if not isinstance(action_entry, dict):
        raise ValidationError(f"asset {entity_id}: include action entry is malformed")
    selected = action_entry.get("selected_options")
    if selected is None:
        return False
    if not isinstance(selected, list):
        raise ValidationError(f"asset {entity_id}: selected_options must be a list, got {type(selected).__name__}")
    return any(isinstance(opt, dict) and opt.get("value") == "included" for opt in selected)
