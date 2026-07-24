"""Deterministic group-summary and asset-root Slack message renderers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import datetime, timezone
from dataclasses import dataclass

from red_team_prop_threader._errors import ValidationError


if TYPE_CHECKING:
    from red_team_prop_threader.domain import SupportingLink


__all__ = ("AID_EDIT_ASSET_DETAILS", "AID_EDIT_GROUP_DETAILS", "AssetRootContext", "GroupSummaryContext", "render_asset_root", "render_group_summary")

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
        animator_id: Slack user ID of the group animator (notifying mention), or None/empty when unassigned.
        additional_ids: Slack user IDs of additional group people (notifying).
        links: ordered group supporting links.
        included_asset_count: number of assets included in this group.
        processing_status: current processing status string.
        summary_identity: opaque identity value for the edit button payload.
        completion_count: number of assets successfully posted, or None.
        failure_count: number of assets that failed to post, or None.
        canvas_url: channel-canvas URL, or None if not yet available.
    """

    group_title: str
    animator_id: str | None
    additional_ids: tuple[str, ...]
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
        asset_animator_id: Slack user ID of the asset animator (notifying mention), or empty when unassigned.
        asset_additional_ids: Slack user IDs of asset additional people (notifying).
        group_animator_display: display name of the group animator (non-notifying), or empty when unassigned.
        group_additional_displays: display names of group additional people (non-notifying).
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
    asset_animator_id: str
    asset_additional_ids: tuple[str, ...]
    group_animator_display: str
    group_additional_displays: tuple[str, ...]
    group_links: tuple[SupportingLink, ...]
    asset_links: tuple[SupportingLink, ...]
    message_identity: str
    is_latest: bool = False
    has_prior_thread: bool = False
    last_editor_display: str | None = None
    updated_ts: int | None = None


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

    animator_id = (context.animator_id or "").strip()
    stakeholder_parts: list[str] = []
    if animator_id:
        stakeholder_parts.append(f"*Creative Stakeholder:* {_mention(animator_id)}")
    if context.additional_ids:
        additional_str = " ".join(_mention(uid) for uid in context.additional_ids if uid)
        if additional_str:
            stakeholder_parts.append(f"*Additional:* {additional_str}")
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

    Asset requestors are rendered as notifying Slack mentions. Group people are
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

    # Asset / Group / Requestor / Group POCs share one section so Slack does not
    # insert section padding between them (reads as four tight lines).
    asset_link = f":shotgrid: <{context.asset_url}|{escaped_name}>"
    asset_line = f":threadparrot: *Asset:* {asset_link} (ShotGrid ID: {context.asset_entity_id})"
    if context.is_latest and context.has_prior_thread:
        asset_line += " (latest thread)"
    asset_line += " :threadparrot:"

    asset_animator_id = (context.asset_animator_id or "").strip()
    requestor_parts: list[str] = []
    if asset_animator_id:
        requestor_parts.append(f"*Requestor:* {_mention(asset_animator_id)}")
    if context.asset_additional_ids:
        add_str = " ".join(_mention(uid) for uid in context.asset_additional_ids if uid)
        if add_str:
            requestor_parts.append(f"*Additional:* {add_str}")
    requestor_line = "*Requestor:* unassigned" if not requestor_parts else "  ".join(requestor_parts)

    pocs: list[str] = []
    if (context.group_animator_display or "").strip():
        pocs.append(_escape(context.group_animator_display.strip()))
    pocs.extend(_escape(name) for name in context.group_additional_displays if name.strip())
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
