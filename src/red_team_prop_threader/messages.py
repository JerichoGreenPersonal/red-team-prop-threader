"""Deterministic group-summary and asset-root Slack message renderers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from datetime import datetime, timezone
from dataclasses import dataclass

from red_team_prop_threader._errors import ValidationError


if TYPE_CHECKING:
    from collections.abc import Mapping

    from red_team_prop_threader.domain import SupportingLink


__all__ = (
    "AID_EDIT_ASSET_DETAILS",
    "AID_EDIT_GROUP_DETAILS",
    "AssetRootContext",
    "GroupSummaryContext",
    "coalesce_ids",
    "coalesce_str",
    "migrate_people_snapshot",
    "render_asset_root",
    "render_group_summary",
)

# ---------------------------------------------------------------------------
# stable action ID constants
# ---------------------------------------------------------------------------

AID_EDIT_GROUP_DETAILS = "edit_group_details"
AID_EDIT_ASSET_DETAILS = "edit_asset_details"

# ---------------------------------------------------------------------------
# Slack limits
# ---------------------------------------------------------------------------

_SECTION_TEXT_MAX = 3000
_BUTTON_TEXT_MAX = 75
_BUTTON_VALUE_MAX = 2000

# ---------------------------------------------------------------------------
# context dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GroupSummaryContext:
    """immutable context for rendering a group summary message.

    Args:
        group_title: normalized group title string.
        creative_stakeholder_id: Slack user ID of the Creative Stakeholder (notifying mention), or None/empty when unassigned.
        additional_stakeholder_ids: Slack user IDs of additional group stakeholders (notifying).
        links: ordered group supporting links.
        included_asset_count: number of assets included in this group.
        processing_status: current processing status string.
        summary_identity: opaque identity value for the edit button payload.
        completion_count: number of assets successfully posted, or None.
        failure_count: number of assets that failed to post, or None.
        canvas_url: channel-canvas URL, or None if not yet available.
    """

    group_title: str
    creative_stakeholder_id: str | None
    additional_stakeholder_ids: tuple[str, ...]
    links: tuple[SupportingLink, ...]
    included_asset_count: int
    processing_status: str
    summary_identity: str
    completion_count: int | None = None
    failure_count: int | None = None
    canvas_url: str | None = None


@dataclass(frozen=True, slots=True)
class AssetRootContext:
    """immutable context for rendering an asset root message.

    Args:
        asset_entity_id: ShotGrid entity ID for the asset.
        asset_name: display name of the asset.
        asset_url: ShotGrid URL for the asset.
        group_title: normalized group title.
        created_ts: unix timestamp of the original thread creation.
        ic_poc_id: Slack user ID of the IC POC (notifying mention), or empty when unassigned.
        additional_ic_ids: Slack user IDs of additional ICs (notifying).
        creative_stakeholder_display: display name of the Creative Stakeholder (non-notifying), or empty when unassigned.
        additional_stakeholder_displays: display names of additional stakeholders (non-notifying).
        group_links: group-level supporting links.
        asset_links: asset-level supporting links.
        message_identity: opaque identity value for the edit button payload.
        is_latest: whether this is the current latest root for the asset.
        has_prior_thread: whether an older thread exists for this asset (drives the latest label).
        last_editor_display: display name of the last editor, or None.
        updated_ts: unix timestamp of the last edit, or None.
    """

    asset_entity_id: int
    asset_name: str
    asset_url: str
    group_title: str
    created_ts: int
    ic_poc_id: str
    additional_ic_ids: tuple[str, ...]
    creative_stakeholder_display: str
    additional_stakeholder_displays: tuple[str, ...]
    group_links: tuple[SupportingLink, ...]
    asset_links: tuple[SupportingLink, ...]
    message_identity: str
    is_latest: bool = False
    has_prior_thread: bool = False
    last_editor_display: str | None = None
    updated_ts: int | None = None


# ---------------------------------------------------------------------------
# snapshot / job-payload people keys
# ---------------------------------------------------------------------------

_LEGACY_PEOPLE_KEYS = (
    ("ic_poc_id", "asset_animator_id"),
    ("additional_ic_ids", "asset_additional_ids"),
    ("creative_stakeholder_id", "group_animator_id"),
    ("additional_stakeholder_ids", "group_additional_ids"),
    ("creative_stakeholder_display", "group_animator_display"),
    ("additional_stakeholder_displays", "group_additional_displays"),
)


def coalesce_str(data: Mapping[str, Any], *keys: str) -> str:
    """Return the first present key as a stripped string.

    A present key wins even when empty, so a cleared POC does not fall back
    to a legacy animator_* value still stored on the same snapshot.
    """
    for key in keys:
        if key not in data:
            continue
        return str(data.get(key) or "").strip()
    return ""


def coalesce_ids(data: Mapping[str, Any], *keys: str) -> tuple[str, ...]:
    """Return the first present key as a tuple of stripped ids.

    A present key wins even when empty.
    """
    for key in keys:
        if key not in data:
            continue
        raw = data.get(key) or ()
        if isinstance(raw, str):
            return (raw.strip(),) if raw.strip() else ()
        return tuple(str(item) for item in raw if str(item).strip())
    return ()


def migrate_people_snapshot(snapshot: dict[str, Any]) -> None:
    """Copy legacy animator_* keys into new names, then drop the old keys.

    Presence of a new key (even empty) wins. Used on write so the next Edit
    POCs save stops carrying animator_* without rewriting Slack history first.
    """
    for new_key, old_key in _LEGACY_PEOPLE_KEYS:
        if new_key not in snapshot and old_key in snapshot:
            snapshot[new_key] = snapshot[old_key]
        snapshot.pop(old_key, None)


# ---------------------------------------------------------------------------
# private helpers
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    """Escape user-controlled text for Slack mrkdwn.

    Args:
        text: raw user-supplied string.

    Returns:
        str: string with &, <, and > replaced by HTML entities.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _mention(slack_id: str) -> str:
    """Return a notifying Slack user mention.

    Args:
        slack_id: Slack user ID.

    Returns:
        str: ``<@UXXXXXXX>`` mention string.
    """
    return f"<@{slack_id}>"


def _link(url: str, label: str) -> str:
    """Return a Slack mrkdwn link.

    Args:
        url: absolute URL (trusted, already validated).
        label: human-readable label (escaped by caller if user-supplied).

    Returns:
        str: ``<URL|label>`` link string.
    """
    return f"<{url}|{_escape(label)}>"


def _slack_date(ts: int) -> str:
    """Return a Slack viewer-localized date markup string with a fallback.

    Args:
        ts: unix timestamp.

    Returns:
        str: ``<!date^TS^{date_short} at {time}|fallback>`` markup.
    """
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    fallback = f"{dt.strftime('%b')} {dt.day}, {dt.year} at {dt.strftime('%I').lstrip('0') or '12'}:{dt.strftime('%M')} {dt.strftime('%p')} UTC"
    return f"<!date^{ts}^{{date_short}} at {{time}}|{fallback}>"


def _plain(text: str, max_len: int = 2000) -> dict[str, object]:
    """Return a Slack plain_text composition object.

    Args:
        text: plain text string.
        max_len: maximum allowed length; long text is truncated with ellipsis.

    Returns:
        dict[str, object]: Slack plain_text composition object.
    """
    if len(text) > max_len:
        text = text[: max_len - 1] + "\u2026"
    return {"type": "plain_text", "text": text}


def _mrkdwn(text: str) -> dict[str, object]:
    """Return a Slack mrkdwn text composition object.

    Args:
        text: mrkdwn-formatted string.

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


def _actions(bid: str, elements: list[dict[str, object]]) -> dict[str, object]:
    """Return a Slack actions block.

    Args:
        bid: stable block_id.
        elements: interactive element dicts.

    Returns:
        dict[str, object]: Slack actions block.
    """
    return {"type": "actions", "block_id": bid, "elements": elements}


def _button(text: str, action_id: str, value: str = "") -> dict[str, object]:
    """Return a Slack button element.

    Args:
        text: button label (max 75 chars).
        action_id: stable action ID.
        value: opaque payload value.

    Returns:
        dict[str, object]: Slack button element.

    Raises:
        ValidationError: if value exceeds Slack's 2000-character limit.
    """
    if len(value) > _BUTTON_VALUE_MAX:
        raise ValidationError(f"button value exceeds Slack limit of {_BUTTON_VALUE_MAX} characters")
    return {"type": "button", "text": _plain(text, max_len=_BUTTON_TEXT_MAX), "action_id": action_id, "value": value}


def _validate_section_text(text: str, field: str) -> None:
    """Raise ValidationError if text exceeds the Slack section text limit.

    Args:
        text: the text to validate.
        field: a human-readable field name used in the error message.

    Raises:
        ValidationError: if text exceeds _SECTION_TEXT_MAX characters.
    """
    if len(text) > _SECTION_TEXT_MAX:
        raise ValidationError(f"{field} exceeds Slack section text limit of {_SECTION_TEXT_MAX} characters")


def _render_links(links: tuple[SupportingLink, ...]) -> str:
    """Render supporting links as mrkdwn list lines.

    Args:
        links: supporting links to render.

    Returns:
        str: newline-separated ``<url|label>`` strings, or empty string.
    """
    if not links:
        return ""
    return "\n".join(_link(lnk.url, lnk.label) for lnk in links)


# ---------------------------------------------------------------------------
# public render functions
# ---------------------------------------------------------------------------


def render_group_summary(context: GroupSummaryContext) -> dict[str, object]:
    """Render a deterministic group summary message payload.

    The message includes a notifying Creative Stakeholder mention and additional
    stakeholder mentions, group links, asset count, and an edit button.
    Completion/failure counts and canvas link appear when provided.

    Args:
        context: all content for the group summary.

    Returns:
        dict[str, object]: Slack message payload with ``text`` and ``blocks``.

    Raises:
        ValidationError: if group_title exceeds the Slack section text limit.
    """
    escaped_title = _escape(context.group_title)
    _validate_section_text(escaped_title, "group_title")

    fallback = f"Group summary: {context.group_title}"
    blocks: list[dict[str, object]] = []

    # Title / Creative Stakeholder / Group Links / count share one section so
    # Slack does not insert section padding between them.
    header_lines: list[str] = [f"*{escaped_title}*"]

    creative_stakeholder_id = (context.creative_stakeholder_id or "").strip()
    stakeholder_parts: list[str] = []
    if creative_stakeholder_id:
        stakeholder_parts.append(f"*Creative Stakeholder:* {_mention(creative_stakeholder_id)}")
    if context.additional_stakeholder_ids:
        additional_str = " ".join(_mention(uid) for uid in context.additional_stakeholder_ids if uid)
        if additional_str:
            stakeholder_parts.append(f"*Additional stakeholders:* {additional_str}")
    if not stakeholder_parts:
        header_lines.append("*Creative Stakeholder:* unassigned")
    else:
        header_lines.append("  ".join(stakeholder_parts))

    links_str = _render_links(context.links)
    if links_str:
        header_lines.append(f"*Group Links:*\n{links_str}")

    header_lines.append(f"*{context.included_asset_count}* asset(s) included.")
    blocks.append(_section("gs_header", _mrkdwn("\n".join(header_lines))))

    # completion/failure counts
    if context.completion_count is not None or context.failure_count is not None:
        comp = context.completion_count or 0
        fail = context.failure_count or 0
        result_text = f"*Completed:* {comp} \u2014 *Failed:* {fail}"
        if context.canvas_url is not None:
            result_text += f"\n*Canvas:* <{context.canvas_url}|View canvas>"
        blocks.append(_section("gs_results", _mrkdwn(result_text)))
    elif context.canvas_url is not None:
        blocks.append(_section("gs_canvas", _mrkdwn(f"*Canvas:* <{context.canvas_url}|View canvas>")))

    # edit button
    blocks.append(_actions("gs_actions", [_button("Edit Group Details", AID_EDIT_GROUP_DETAILS, value=context.summary_identity)]))

    return {"text": fallback, "blocks": blocks}


def render_asset_root(context: AssetRootContext) -> dict[str, object]:
    """Render a deterministic asset root message payload.

    Asset IC POCs are rendered as notifying Slack mentions. Group people are
    rendered as plain escaped display names (never as @-mentions). Deterministic
    block order ensures reproducible message updates.

    Args:
        context: all content for the asset root.

    Returns:
        dict[str, object]: Slack message payload with ``text`` and ``blocks``.
    """
    escaped_name = _escape(context.asset_name)
    fallback = f":threadparrot: Asset: {context.asset_name} \u2014 {context.group_title} :threadparrot:"
    blocks: list[dict[str, object]] = []

    # asset / group / ic poc / additional ics / group pocs share one section so slack does not
    # insert section padding between them (reads as four tight lines).
    asset_link = f":shotgrid: <{context.asset_url}|{escaped_name}>"
    asset_line = f":threadparrot: *Asset:* {asset_link} (ShotGrid ID: {context.asset_entity_id})"
    if context.is_latest and context.has_prior_thread:
        asset_line += " (latest thread)"
    asset_line += " :threadparrot:"

    ic_poc_id = (context.ic_poc_id or "").strip()
    requestor_parts: list[str] = []
    if ic_poc_id:
        requestor_parts.append(f"*IC POC:* {_mention(ic_poc_id)}")
    if context.additional_ic_ids:
        add_str = " ".join(_mention(uid) for uid in context.additional_ic_ids if uid)
        if add_str:
            requestor_parts.append(f"*Additional ICs:* {add_str}")
    requestor_line = "*IC POC:* unassigned" if not requestor_parts else "  ".join(requestor_parts)

    pocs: list[str] = []
    if (context.creative_stakeholder_display or "").strip():
        pocs.append(_escape(context.creative_stakeholder_display.strip()))
    pocs.extend(_escape(name) for name in context.additional_stakeholder_displays if name.strip())
    pocs_str = ", ".join(pocs) if pocs else "unassigned"

    header_lines = (asset_line, f"*Group:* {_escape(context.group_title)}", requestor_line, f"*Group POCs:* {pocs_str}")
    blocks.append(_section("ar_header", _mrkdwn("\n".join(header_lines))))

    # Asset-level links only (group links stay on the group summary).
    asset_links_str = _render_links(context.asset_links)
    if asset_links_str:
        blocks.append(_section("ar_links", _mrkdwn(f"*Links:*\n{asset_links_str}")))

    # edit info for the latest root (editor name and update timestamp)
    if context.is_latest and context.last_editor_display is not None and context.updated_ts is not None:
        update_markup = _slack_date(context.updated_ts)
        blocks.append(_section("ar_edited", _mrkdwn(f"_Last edited by {_escape(context.last_editor_display)} \u2014 {update_markup}_")))

    # edit button
    blocks.append(_actions("ar_actions", [_button("Edit POCs", AID_EDIT_ASSET_DETAILS, value=context.message_identity)]))

    return {"text": fallback, "blocks": blocks}
