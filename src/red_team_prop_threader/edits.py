"""latest-only post-completion editors for group summaries and asset roots."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol
from dataclasses import dataclass

from red_team_prop_threader.canvas import IndexedAsset, CanvasService, GroupIndexRequest
from red_team_prop_threader.domain import SupportingLink
from red_team_prop_threader._errors import ValidationError, ExternalServiceError
from red_team_prop_threader.messages import (
    AID_EDIT_ASSET_DETAILS,
    AID_EDIT_GROUP_DETAILS,
    AssetRootContext,
    GroupSummaryContext,
    render_asset_root,
    render_group_summary,
)
from red_team_prop_threader.validation import parse_supporting_links, validate_channel_members
from red_team_prop_threader.repositories import MessageKind


if TYPE_CHECKING:
    from datetime import datetime

    from red_team_prop_threader.repositories import Repositories, MessageRecord


__all__ = (
    "AID_EDIT_ASSET_DETAILS",
    "AID_EDIT_GROUP_DETAILS",
    "CALLBACK_ASSET_EDIT",
    "CALLBACK_GROUP_EDIT",
    "AssetEditRequest",
    "EditOpenResult",
    "EditService",
    "GroupEditRequest",
    "MessageRef",
    "decode_edit_submission",
    "edit_validation_errors",
)

CALLBACK_ASSET_EDIT = "asset_edit_submit"
CALLBACK_GROUP_EDIT = "group_edit_submit"

_BID_ANIMATOR = "edit_animator"
_BID_ADDITIONAL = "edit_additional"
_BID_LINKS = "edit_links"


class Clock(Protocol):
    """minimal utc clock."""

    def now(self) -> datetime:
        """Return the current UTC-aware instant."""


class EditSlackGateway(Protocol):
    """slack methods required by post-completion editors."""

    def open_view(self, trigger_id: str, view: dict[str, Any]) -> dict[str, Any]:
        """Open a modal."""

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Update a bot message without creating a new notification."""

    def get_conversation_members(self, channel_id: str) -> tuple[str, ...]:
        """List channel members."""

    def get_user_info(self, user_id: str) -> dict[str, object]:
        """Fetch user profile data."""


@dataclass(frozen=True, slots=True)
class MessageRef:
    """reference to a clicked summary or asset-root message."""

    workspace_id: str
    channel_id: str
    user_id: str
    message_ts: str
    message_identity: str
    trigger_id: str | None = None


@dataclass(frozen=True, slots=True)
class EditOpenResult:
    """outcome of attempting to open an editor modal."""

    refused: bool
    latest_permalink: str | None = None
    view: dict[str, Any] | None = None
    ephemeral_text: str | None = None


@dataclass(frozen=True, slots=True)
class GroupEditRequest:
    """validated group edit submission payload."""

    workspace_id: str
    channel_id: str
    user_id: str
    message_ts: str
    animator_id: str
    additional_ids: tuple[str, ...]
    links_text: str


@dataclass(frozen=True, slots=True)
class AssetEditRequest:
    """validated asset edit submission payload."""

    workspace_id: str
    channel_id: str
    user_id: str
    message_ts: str
    animator_id: str
    additional_ids: tuple[str, ...]
    links_text: str


class EditService:
    """guards and applies latest-only group/asset detail edits."""

    def __init__(
        self,
        *,
        repositories: Repositories,
        slack: EditSlackGateway,
        canvas_slack: Any,
        clock: Clock,
        primary_asset_index_channel_id: str = "",
    ) -> None:
        """Wire repositories, slack, canvas gateway, and clock.

        Args:
            repositories: transaction-scoped repositories.
            slack: messaging gateway for updates and membership checks.
            canvas_slack: gateway satisfying CanvasService needs.
            clock: utc clock.
            primary_asset_index_channel_id: channel id for the primary asset index canvas.
        """
        self._repos = repositories
        self._slack = slack
        self._canvas = CanvasService(canvas_slack)
        self._clock = clock
        self._primary_asset_index_channel_id = primary_asset_index_channel_id.strip()

    def open_asset_editor(self, ref: MessageRef) -> EditOpenResult:
        """Open the asset editor, or refuse a historical root.

        Args:
            ref: clicked message reference.

        Returns:
            EditOpenResult: modal view or refusal with latest permalink.
        """
        return self._open_editor(ref, expected_kind=MessageKind.ASSET_ROOT, callback_id=CALLBACK_ASSET_EDIT, title="Edit POCs")

    def open_group_editor(self, ref: MessageRef) -> EditOpenResult:
        """Open the group editor, or refuse a historical summary.

        Args:
            ref: clicked message reference.

        Returns:
            EditOpenResult: modal view or refusal with latest permalink.
        """
        return self._open_editor(ref, expected_kind=MessageKind.GROUP_SUMMARY, callback_id=CALLBACK_GROUP_EDIT, title="Edit Group Details")

    def apply_asset_edit(self, request: AssetEditRequest) -> None:
        """Apply an asset edit to the current latest root only.

        Args:
            request: validated asset edit submission.

        Raises:
            ValidationError: when membership/link validation fails or the root is not latest.
            LookupError: when the message cannot be found.
        """
        message = self._require_latest_message(request.workspace_id, request.channel_id, request.message_ts, MessageKind.ASSET_ROOT)
        self._require_channel_member(request.channel_id, request.user_id)
        links = parse_supporting_links(request.links_text) if request.links_text.strip() else ()
        people = {uid for uid in (request.animator_id, *request.additional_ids) if uid.strip()}
        self._require_selected_members(request.channel_id, people)
        snapshot = _edit_snapshot(message)
        snapshot["asset_animator_id"] = request.animator_id.strip()
        snapshot["asset_additional_ids"] = [uid for uid in request.additional_ids if uid.strip()]
        snapshot["asset_links"] = [{"label": link.label, "url": link.url} for link in links]
        now = self._clock.now()
        editor_display = self._display_name(request.user_id)
        context = _asset_context_from_snapshot(snapshot, message, editor_display=editor_display, updated_ts=int(now.timestamp()))
        rendered = render_asset_root(context)
        self._slack.update_message(message.channel_id, message.slack_ts, text=str(rendered["text"]), blocks=_blocks(rendered))
        metadata = dict(message.canvas_metadata or {})
        metadata["edit"] = snapshot
        self._repos.history.touch_editor(message.id, editor_id=request.user_id, now=now, canvas_metadata=metadata)

    def apply_group_edit(self, request: GroupEditRequest) -> None:
        """Apply a group edit to summary, canvas, and all latest asset roots.

        Args:
            request: validated group edit submission.

        Raises:
            ValidationError: when membership/link validation fails or the summary is not latest.
            LookupError: when the summary cannot be found.
        """
        summary = self._require_latest_message(request.workspace_id, request.channel_id, request.message_ts, MessageKind.GROUP_SUMMARY)
        self._require_channel_member(request.channel_id, request.user_id)
        links = parse_supporting_links(request.links_text) if request.links_text.strip() else ()
        people = {uid for uid in (request.animator_id, *request.additional_ids) if uid.strip()}
        self._require_selected_members(request.channel_id, people)
        now = self._clock.now()
        editor_display = self._display_name(request.user_id)
        updated_ts = int(now.timestamp())

        summary_snapshot = _edit_snapshot(summary)
        summary_snapshot["group_animator_id"] = request.animator_id.strip()
        summary_snapshot["group_additional_ids"] = [uid for uid in request.additional_ids if uid.strip()]
        summary_snapshot["group_links"] = [{"label": link.label, "url": link.url} for link in links]
        animator_id = str(summary_snapshot["group_animator_id"])
        additional_ids = tuple(str(item) for item in summary_snapshot["group_additional_ids"])
        summary_snapshot["group_animator_display"] = self._display_name(animator_id) if animator_id else ""
        summary_snapshot["group_additional_displays"] = [self._display_name(user_id) for user_id in additional_ids]

        summary_context = _summary_context_from_snapshot(summary_snapshot, summary)
        rendered_summary = render_group_summary(summary_context)
        self._slack.update_message(summary.channel_id, summary.slack_ts, text=str(rendered_summary["text"]), blocks=_blocks(rendered_summary))
        summary_metadata = dict(summary.canvas_metadata or {})
        summary_metadata["edit"] = summary_snapshot
        self._repos.history.touch_editor(summary.id, editor_id=request.user_id, now=now, canvas_metadata=summary_metadata)

        roots = self._repos.history.list_latest_asset_roots_for_group(summary.group_id)
        for root in roots:
            root_snapshot = _edit_snapshot(root)
            root_snapshot["group_animator_id"] = animator_id
            root_snapshot["group_additional_ids"] = list(additional_ids)
            root_snapshot["group_links"] = list(summary_snapshot["group_links"])
            root_snapshot["group_animator_display"] = summary_snapshot["group_animator_display"]
            root_snapshot["group_additional_displays"] = list(summary_snapshot["group_additional_displays"])
            context = _asset_context_from_snapshot(root_snapshot, root, editor_display=editor_display, updated_ts=updated_ts)
            rendered = render_asset_root(context)
            self._slack.update_message(root.channel_id, root.slack_ts, text=str(rendered["text"]), blocks=_blocks(rendered))
            root_metadata = dict(root.canvas_metadata or {})
            root_metadata["edit"] = root_snapshot
            self._repos.history.touch_editor(root.id, editor_id=request.user_id, now=now, canvas_metadata=root_metadata)

        canvas_id = str((summary.canvas_metadata or {}).get("canvas_id") or summary_snapshot.get("canvas_id") or "")
        if canvas_id:
            self._canvas.index_batch(
                GroupIndexRequest(
                    channel_id=summary.channel_id,
                    canvas_id=canvas_id,
                    group_title=str(summary_snapshot["group_title"]),
                    animator_display=str(summary_snapshot["group_animator_display"]),
                    additional_displays=tuple(str(item) for item in summary_snapshot.get("group_additional_displays") or ()),
                    links=tuple(SupportingLink(str(item["label"]), str(item["url"])) for item in summary_snapshot.get("group_links") or ()),
                    assets=self._indexed_assets(roots),
                )
            )

        primary_channel = self._primary_asset_index_channel_id
        if primary_channel and summary.channel_id != primary_channel:
            try:
                primary_canvas_id = self._canvas.ensure_primary_canvas(primary_channel)
                self._canvas.index_batch(
                    GroupIndexRequest(
                        channel_id=summary.channel_id,
                        canvas_id=primary_canvas_id,
                        group_title=str(summary_snapshot["group_title"]),
                        animator_display=str(summary_snapshot["group_animator_display"]),
                        additional_displays=tuple(str(item) for item in summary_snapshot.get("group_additional_displays") or ()),
                        links=tuple(
                            SupportingLink(str(item["label"]), str(item["url"]))
                            for item in summary_snapshot.get("group_links") or ()
                        ),
                        assets=self._indexed_assets(roots),
                        for_primary=True,
                        source_channel_display=str(summary_snapshot.get("source_channel_display") or summary.channel_id),
                    )
                )
            except Exception:
                logging.getLogger(__name__).warning("primary asset index update failed", exc_info=True)

    def _open_editor(self, ref: MessageRef, *, expected_kind: MessageKind, callback_id: str, title: str) -> EditOpenResult:
        """Shared open path for asset/group editors."""
        self._require_channel_member(ref.channel_id, ref.user_id)
        message = self._repos.history.get_by_channel_ts(workspace_id=ref.workspace_id, channel_id=ref.channel_id, slack_ts=ref.message_ts)
        if message is None:
            raise LookupError("tracked message not found")
        if message.kind is not expected_kind:
            raise ValidationError("message kind does not match edit action")
        if not message.is_latest:
            latest = self._latest_for(message)
            permalink = latest.permalink if latest is not None else None
            text = "This message is historical. Open the current Latest message to edit."
            if permalink:
                text = f"{text}\n<{permalink}|Open latest>"
            return EditOpenResult(refused=True, latest_permalink=permalink, ephemeral_text=text)

        snapshot = _edit_snapshot(message)
        members = self._channel_member_options(message.channel_id)
        view = _render_edit_view(
            callback_id=callback_id,
            title=title,
            channel_id=message.channel_id,
            message_ts=message.slack_ts,
            snapshot=snapshot,
            is_asset=expected_kind is MessageKind.ASSET_ROOT,
            members=members,
        )
        return EditOpenResult(refused=False, view=view)

    def _require_latest_message(self, workspace_id: str, channel_id: str, message_ts: str, kind: MessageKind) -> MessageRecord:
        """Fetch a latest message or raise."""
        message = self._repos.history.get_by_channel_ts(workspace_id=workspace_id, channel_id=channel_id, slack_ts=message_ts)
        if message is None:
            raise LookupError("tracked message not found")
        if message.kind is not kind or not message.is_latest:
            raise ValidationError("only the current Latest message may be edited")
        return message

    def _latest_for(self, message: MessageRecord) -> MessageRecord | None:
        """Resolve the current latest message for the same edit scope."""
        if message.kind is MessageKind.GROUP_SUMMARY:
            return self._repos.history.latest_group_summary(message.group_id)
        if message.asset_entity_id is None:
            return None
        return self._repos.history.latest_asset_root(message.workspace_id, message.channel_id, message.asset_entity_id)

    def _require_channel_member(self, channel_id: str, user_id: str) -> None:
        """Refuse edits from non-members."""
        members = set(self._slack.get_conversation_members(channel_id))
        if user_id not in members:
            raise ValidationError("only channel members may edit prop threads")

    def _require_selected_members(self, channel_id: str, selected: set[str]) -> None:
        """Ensure selected people are channel members."""
        members = set(self._slack.get_conversation_members(channel_id))
        missing = validate_channel_members(selected, members)
        if missing:
            raise ValidationError("selected users must be members of the target channel")

    def _display_name(self, user_id: str) -> str:
        """Resolve a non-notifying display name."""
        try:
            info = self._slack.get_user_info(user_id)
        except ExternalServiceError:
            return user_id
        profile = info.get("profile") if isinstance(info.get("profile"), dict) else {}
        for key in ("display_name", "real_name"):
            value = profile.get(key) if isinstance(profile, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
        return user_id

    def _channel_member_options(self, channel_id: str) -> tuple[tuple[str, str], ...]:
        """Return (user_id, verbose_label) pairs for human channel members."""
        options: list[tuple[str, str]] = []
        for user_id in self._slack.get_conversation_members(channel_id):
            if len(options) >= 100:
                break
            label = self._verbose_member_label(user_id)
            if label is None:
                continue
            options.append((user_id, label))
        options.sort(key=lambda item: item[1].casefold())
        return tuple(options)

    def _verbose_member_label(self, user_id: str) -> str | None:
        """Return a verbose picker label, or None for bots/apps to exclude."""
        try:
            info = self._slack.get_user_info(user_id)
        except ExternalServiceError:
            return user_id
        if info.get("deleted") is True or info.get("is_bot") is True or user_id == "USLACKBOT":
            return None
        profile = info.get("profile") if isinstance(info.get("profile"), dict) else {}
        real_name = ""
        display_name = ""
        if isinstance(profile, dict):
            real_name = str(profile.get("real_name") or "").strip()
            display_name = str(profile.get("display_name") or "").strip()
        username = str(info.get("name") or "").strip()
        primary = real_name or display_name or username or user_id
        if username and primary.casefold() != username.casefold():
            label = f"{primary} (@{username})"
        elif username:
            label = f"@{username}"
        else:
            label = primary
        return label[:75]

    def _indexed_assets(self, roots: list[MessageRecord]) -> tuple[IndexedAsset, ...]:
        """Build canvas index entries from latest roots."""
        from datetime import datetime, timezone

        entries: list[IndexedAsset] = []
        for root in roots:
            snapshot = _edit_snapshot(root)
            created_ts = int(snapshot.get("created_ts") or self._clock.now().timestamp())
            entries.append(
                IndexedAsset(
                    entity_id=int(snapshot["entity_id"]),
                    name=str(snapshot["asset_name"]),
                    asset_url=str(snapshot["asset_url"]),
                    permalink=root.permalink,
                    created_at=datetime.fromtimestamp(created_ts, tz=timezone.utc),
                    is_latest=True,
                )
            )
        return tuple(entries)


def _edit_snapshot(message: MessageRecord) -> dict[str, Any]:
    """Return a mutable copy of the stored edit snapshot."""
    metadata = message.canvas_metadata or {}
    edit = metadata.get("edit")
    if not isinstance(edit, dict):
        raise ValidationError("message is missing editable snapshot metadata")
    return dict(edit)


def _asset_context_from_snapshot(snapshot: dict[str, Any], message: MessageRecord, *, editor_display: str | None, updated_ts: int | None) -> AssetRootContext:
    """Build an asset root render context from a snapshot."""
    return AssetRootContext(
        asset_entity_id=int(snapshot["entity_id"]),
        asset_name=str(snapshot["asset_name"]),
        asset_url=str(snapshot["asset_url"]),
        group_title=str(snapshot["group_title"]),
        created_ts=int(snapshot["created_ts"]),
        asset_animator_id=str(snapshot["asset_animator_id"]),
        asset_additional_ids=tuple(str(item) for item in snapshot.get("asset_additional_ids") or ()),
        group_animator_display=str(snapshot.get("group_animator_display") or ""),
        group_additional_displays=tuple(str(item) for item in snapshot.get("group_additional_displays") or ()),
        group_links=tuple(SupportingLink(str(item["label"]), str(item["url"])) for item in snapshot.get("group_links") or ()),
        asset_links=tuple(SupportingLink(str(item["label"]), str(item["url"])) for item in snapshot.get("asset_links") or ()),
        message_identity=str(snapshot.get("message_identity") or message.id),
        is_latest=True,
        has_prior_thread=bool(snapshot.get("has_prior_thread")),
        last_editor_display=editor_display,
        updated_ts=updated_ts,
    )


def _summary_context_from_snapshot(snapshot: dict[str, Any], message: MessageRecord) -> GroupSummaryContext:
    """Build a group summary render context from a snapshot."""
    return GroupSummaryContext(
        group_title=str(snapshot["group_title"]),
        animator_id=str(snapshot["group_animator_id"]),
        additional_ids=tuple(str(item) for item in snapshot.get("group_additional_ids") or ()),
        links=tuple(SupportingLink(str(item["label"]), str(item["url"])) for item in snapshot.get("group_links") or ()),
        included_asset_count=int(snapshot.get("included_asset_count") or 0),
        processing_status=str(snapshot.get("processing_status") or "Complete"),
        summary_identity=str(snapshot.get("message_identity") or message.id),
        completion_count=snapshot.get("completion_count"),
        failure_count=snapshot.get("failure_count"),
        canvas_url=None,
    )


def _render_edit_view(
    *,
    callback_id: str,
    title: str,
    channel_id: str,
    message_ts: str,
    snapshot: dict[str, Any],
    is_asset: bool,
    members: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    """Render a people/links edit modal limited to channel members."""
    if is_asset:
        animator = str(snapshot.get("asset_animator_id") or "").strip()
        additional = tuple(str(item) for item in snapshot.get("asset_additional_ids") or () if str(item).strip())
        links = _links_text(snapshot.get("asset_links"))
    else:
        animator = str(snapshot.get("group_animator_id") or "").strip()
        additional = tuple(str(item) for item in snapshot.get("group_additional_ids") or () if str(item).strip())
        links = _links_text(snapshot.get("group_links"))
    options = _member_option_objects(members)
    animator_element: dict[str, Any] = {
        "type": "static_select",
        "action_id": _BID_ANIMATOR,
        "placeholder": {"type": "plain_text", "text": "Select a channel member"},
        "options": options,
    }
    initial_animator = _member_option_object(members, animator)
    if initial_animator is not None:
        animator_element["initial_option"] = initial_animator
    additional_element: dict[str, Any] = {
        "type": "multi_static_select",
        "action_id": _BID_ADDITIONAL,
        "placeholder": {"type": "plain_text", "text": "Select channel members"},
        "options": options,
    }
    initial_additional = [option for user_id in additional if (option := _member_option_object(members, user_id)) is not None]
    if initial_additional:
        additional_element["initial_options"] = initial_additional
    return {
        "type": "modal",
        "callback_id": callback_id,
        "private_metadata": f"{channel_id}|{message_ts}",
        "title": {"type": "plain_text", "text": title[:24]},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": _BID_ANIMATOR,
                "optional": True,
                "label": {"type": "plain_text", "text": "Requestor" if is_asset else "Creative Stakeholder"},
                "hint": {"type": "plain_text", "text": "Only people already in this channel are listed."},
                "element": animator_element,
            },
            {
                "type": "input",
                "block_id": _BID_ADDITIONAL,
                "optional": True,
                "label": {"type": "plain_text", "text": "Additional requestors" if is_asset else "Additional stakeholders"},
                "hint": {"type": "plain_text", "text": "Only people already in this channel are listed."},
                "element": additional_element,
            },
            {
                "type": "input",
                "block_id": _BID_LINKS,
                "optional": True,
                "label": {"type": "plain_text", "text": "Links" if is_asset else "Group links"},
                "element": _links_input_element(links),
            },
        ],
    }


def _member_option_objects(members: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    """Build Slack option objects for edit-modal people pickers."""
    if not members:
        return [{"text": {"type": "plain_text", "text": "No channel members available"}, "value": "__none__"}]
    return [{"text": {"type": "plain_text", "text": label[:75]}, "value": user_id} for user_id, label in members[:100]]


def _member_option_object(members: tuple[tuple[str, str], ...], user_id: str) -> dict[str, Any] | None:
    """Return one option object for a user id when present."""
    if not user_id:
        return None
    for member_id, label in members:
        if member_id == user_id:
            return {"text": {"type": "plain_text", "text": label[:75]}, "value": user_id}
    return None


def _links_input_element(links: str) -> dict[str, Any]:
    """Build the supporting-links plain_text_input, omitting empty initial_value."""
    element: dict[str, Any] = {
        "type": "plain_text_input",
        "action_id": _BID_LINKS,
        "multiline": True,
        "placeholder": {"type": "plain_text", "text": "Label: https://..."},
    }
    if links:
        element["initial_value"] = links
    return element


def _links_text(raw: Any) -> str:
    """Convert stored link dicts into editable multiline text."""
    if not raw:
        return ""
    lines: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            lines.append(f"{item.get('label', '')}: {item.get('url', '')}".strip())
    return "\n".join(lines)


def _blocks(rendered: dict[str, object]) -> list[dict[str, Any]]:
    """Extract typed blocks from a renderer payload."""
    blocks = rendered.get("blocks")
    if not isinstance(blocks, list):
        return []
    typed: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict):
            typed.append({str(key): value for key, value in block.items()})
    return typed


def decode_edit_submission(view: dict[str, Any]) -> tuple[str, str, str, tuple[str, ...], str]:
    """Decode channel, message timestamp, and people/link fields from an edit modal.

    Args:
        view: slack modal view payload.

    Returns:
        tuple: channel_id, message_ts, animator_id, additional_ids, links_text.
    """
    meta = str(view.get("private_metadata") or "")
    if "|" in meta:
        channel_id, message_ts = meta.split("|", 1)
    else:
        channel_id, message_ts = "", meta
    state = view.get("state") if isinstance(view.get("state"), dict) else {}
    values = state.get("values") if isinstance(state, dict) and isinstance(state.get("values"), dict) else {}
    animator_block = values.get(_BID_ANIMATOR) if isinstance(values, dict) else {}
    animator_field = animator_block.get(_BID_ANIMATOR) if isinstance(animator_block, dict) else {}
    animator_id = ""
    if isinstance(animator_field, dict):
        selected_option = animator_field.get("selected_option")
        if isinstance(selected_option, dict):
            animator_id = str(selected_option.get("value") or "").strip()
        else:
            animator_id = str(animator_field.get("selected_user") or "").strip()
    if animator_id == "__none__":
        animator_id = ""
    additional_block = values.get(_BID_ADDITIONAL) if isinstance(values, dict) else {}
    additional_field = additional_block.get(_BID_ADDITIONAL) if isinstance(additional_block, dict) else {}
    additional_ids: tuple[str, ...] = ()
    if isinstance(additional_field, dict):
        selected_options = additional_field.get("selected_options")
        if isinstance(selected_options, list):
            additional_ids = tuple(
                str(option.get("value") or "").strip()
                for option in selected_options
                if isinstance(option, dict) and str(option.get("value") or "").strip() and str(option.get("value") or "").strip() != "__none__"
            )
        else:
            selected = additional_field.get("selected_users")
            additional_ids = tuple(str(item) for item in selected) if isinstance(selected, list) else ()
    links_block = values.get(_BID_LINKS) if isinstance(values, dict) else {}
    links_field = links_block.get(_BID_LINKS) if isinstance(links_block, dict) else {}
    links_text = str(links_field.get("value") or "") if isinstance(links_field, dict) else ""
    return channel_id, message_ts, animator_id, additional_ids, links_text


def edit_validation_errors(exc: ValidationError) -> dict[str, str]:
    """Map an edit ValidationError onto the correct modal block_id.

    Link parse failures must surface on Supporting Links — not Animator.
    """
    message = str(exc)
    if (
        message.startswith("line ")
        or "Supporting links require a label" in message
        or message.startswith("URL ")
        or " URL " in message
    ):
        return {_BID_LINKS: message}
    return {_BID_ANIMATOR: message}
