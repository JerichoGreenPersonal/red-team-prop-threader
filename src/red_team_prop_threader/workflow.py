"""slash-command workflow: canvas preflight, import, paginated drafts, confirmation."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Protocol, cast
from datetime import timedelta
from dataclasses import dataclass

from red_team_prop_threader.views import (
    AssetDraft,
    ImportContext,
    AssetSelection,
    ConfirmationContext,
    CanvasPreflightContext,
    render_asset_page,
    render_import_view,
    decode_asset_page_state,
    render_confirmation_view,
    render_canvas_preflight_view,
)
from red_team_prop_threader.canvas import CANVAS_TITLE, PreflightState
from red_team_prop_threader._errors import ValidationError, ExternalServiceError, PermissionDeniedError
from red_team_prop_threader.shotgrid import parse_page_id, parse_export_csv
from red_team_prop_threader.validation import infer_group_title, normalize_group_title, parse_supporting_links, validate_channel_members


if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

    from red_team_prop_threader.canvas import CanvasService
    from red_team_prop_threader.domain import ImportedAsset
    from red_team_prop_threader.leases import ChannelLeaseRepository


__all__ = ("CommandRequest", "ConfirmResponse", "DraftBook", "DraftSession", "Workflow")

_LEASE_TTL = timedelta(minutes=10)
_CALLBACK_PREFLIGHT = "canvas_preflight"
_CALLBACK_IMPORT = "import_assets"
_CALLBACK_ASSET = "asset_page"
_CALLBACK_CONFIRM = "confirm_batch"


class Clock(Protocol):
    """clock providing timezone-aware utc now."""

    def now(self) -> datetime:
        """Return the current utc instant."""


class SlackClient(Protocol):
    """subset of slack operations used by the workflow."""

    def open_view(self, trigger_id: str, view: dict[str, Any]) -> dict[str, Any]:
        """Open a modal."""

    def update_view(self, view_id: str, view: dict[str, Any], *, view_hash: str | None = None) -> dict[str, Any]:
        """Update an open modal."""

    def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Fetch user profile data."""

    def get_conversation_members(self, channel_id: str) -> tuple[str, ...]:
        """List channel members."""


class ShotGridClient(Protocol):
    """subset of shotgrid operations used by the workflow."""

    def export_page(self, page_id: int) -> str:
        """Export a page as CSV text."""


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """incoming /create-prop-threads invocation."""

    workspace_id: str
    channel_id: str
    user_id: str
    trigger_id: str
    text: str = ""
    response_url: str = ""


@dataclass(frozen=True, slots=True)
class ConfirmResponse:
    """result of attempting to confirm a draft batch."""

    draft_id: str
    private_text: str
    accepted: bool
    lease_token: str | None = None


@dataclass
class DraftSession:
    """mutable in-memory draft used across modal steps."""

    draft_id: str
    workspace_id: str
    channel_id: str
    user_id: str
    page_url: str
    assets: tuple[ImportedAsset, ...]
    duplicate_count: int
    group_title: str
    group_animator_id: str | None
    group_additional_ids: tuple[str, ...]
    group_links_text: str
    included_entity_ids: tuple[int, ...]
    asset_animators: dict[int, str]
    asset_additional: dict[int, tuple[str, ...]]
    asset_links_text: dict[int, str]
    imported_at: datetime
    canvas_id: str | None
    page_index: int = 0
    view_id: str | None = None
    view_hash: str | None = None
    preflight_state: str | None = None
    command_url: str = ""


class DraftBook:
    """in-memory draft index keyed by draft id."""

    def __init__(self) -> None:
        """Initialize an empty draft book."""
        self._items: dict[str, DraftSession] = {}

    def put(self, draft: DraftSession) -> None:
        """Store or replace a draft session.

        Args:
            draft: draft session to retain.
        """
        self._items[draft.draft_id] = draft

    def get(self, draft_id: str) -> DraftSession | None:
        """Return a draft by id, if present.

        Args:
            draft_id: opaque draft identifier.

        Returns:
            DraftSession | None: the draft, or None.
        """
        return self._items.get(draft_id)

    def exists(self, draft_id: str) -> bool:
        """Return whether a draft id is retained.

        Args:
            draft_id: opaque draft identifier.

        Returns:
            bool: True when the draft is present.
        """
        return draft_id in self._items

    def discard(self, draft_id: str) -> None:
        """Remove a draft if present.

        Args:
            draft_id: opaque draft identifier.
        """
        self._items.pop(draft_id, None)


class Workflow:
    """orchestrates slash-command preflight, import, pagination, and confirmation."""

    def __init__(
        self,
        *,
        slack: SlackClient,
        shotgrid: ShotGridClient,
        canvas: CanvasService,
        leases: ChannelLeaseRepository,
        clock: Clock,
        shotgrid_base_url: str,
        session: Session | None = None,
        drafts: DraftBook | None = None,
    ) -> None:
        """Initialize workflow dependencies.

        Args:
            slack: slack client or test double.
            shotgrid: shotgrid client or test double.
            canvas: canvas preflight/index service.
            leases: channel lease repository.
            clock: utc clock.
            shotgrid_base_url: absolute HTTPS ShotGrid base URL.
            session: optional sqlalchemy session for persistence hooks.
            drafts: optional draft book; a new one is created when omitted.
        """
        self.slack = slack
        self.shotgrid = shotgrid
        self.canvas = canvas
        self.leases = leases
        self.clock = clock
        self.shotgrid_base_url = shotgrid_base_url.rstrip("/")
        self.shotgrid_host = self.shotgrid_base_url.removeprefix("https://").removeprefix("http://")
        self.session = session
        self.drafts = drafts or DraftBook()

    def handle_command(self, command: CommandRequest) -> None:
        """Acknowledge by opening preflight, then refine the modal.

        Opens a canvas_preflight modal immediately, runs canvas preflight, and
        updates the modal to import, confirmation actions, or a blocked error.
        ShotGrid export is intentionally deferred until import submission.

        Args:
            command: slash-command request payload.
        """
        draft_id = str(uuid.uuid4())
        command_url = command.text.strip()
        draft = DraftSession(
            draft_id=draft_id,
            workspace_id=command.workspace_id,
            channel_id=command.channel_id,
            user_id=command.user_id,
            page_url=command_url,
            assets=(),
            duplicate_count=0,
            group_title="",
            group_animator_id=None,
            group_additional_ids=(),
            group_links_text="",
            included_entity_ids=(),
            asset_animators={},
            asset_additional={},
            asset_links_text={},
            imported_at=self.clock.now(),
            canvas_id=None,
            command_url=command_url,
        )
        self.drafts.put(draft)

        loading = render_canvas_preflight_view(CanvasPreflightContext(draft_id=draft_id, canvas_name=CANVAS_TITLE, channel_id=command.channel_id))
        loading = {**loading, "callback_id": _CALLBACK_PREFLIGHT}
        opened = self.slack.open_view(command.trigger_id, loading)
        raw_view = opened.get("view")
        view_meta = cast("dict[str, Any]", raw_view) if isinstance(raw_view, dict) else {}
        draft.view_id = str(view_meta.get("id") or "") or None
        draft.view_hash = str(view_meta.get("hash") or "") or None

        try:
            result = self.canvas.preflight(command.channel_id)
        except (PermissionDeniedError, ExternalServiceError) as exc:
            self._update_draft_view(draft, _blocked_view(draft_id, str(exc)))
            return

        draft.preflight_state = result.state.value
        draft.canvas_id = result.canvas_id

        if result.state is PreflightState.BLOCKED:
            detail = result.detail or "canvas access is blocked"
            self._update_draft_view(draft, _blocked_view(draft_id, detail))
            return

        if result.state is PreflightState.READY:
            import_view = render_import_view(ImportContext(draft_id=draft_id, prefilled_url=command_url or None))
            self._update_draft_view(draft, {**import_view, "callback_id": _CALLBACK_IMPORT})
            return

        # create or rename confirmation uses the same preflight actions view
        canvas_name = result.current_title or CANVAS_TITLE
        preflight_view = render_canvas_preflight_view(CanvasPreflightContext(draft_id=draft_id, canvas_name=canvas_name, channel_id=command.channel_id))
        self._update_draft_view(draft, {**preflight_view, "callback_id": _CALLBACK_PREFLIGHT})

    def confirm_canvas_create(self, draft_id: str) -> dict[str, Any]:
        """Create a missing channel canvas after user confirmation.

        Args:
            draft_id: draft identifier from the preflight modal.

        Returns:
            dict[str, Any]: import modal view payload.

        Raises:
            ValidationError: if the draft is unknown.
            ExternalServiceError: if canvas creation fails.
        """
        draft = self._require_draft(draft_id)
        canvas_id = self.canvas.ensure_canvas(draft.channel_id, create=True)
        draft.canvas_id = canvas_id
        draft.preflight_state = PreflightState.READY.value
        view = render_import_view(ImportContext(draft_id=draft_id, prefilled_url=draft.command_url or None))
        return {**view, "callback_id": _CALLBACK_IMPORT}

    def confirm_canvas_rename(self, draft_id: str) -> dict[str, Any]:
        """Rename the channel canvas after user confirmation.

        Args:
            draft_id: draft identifier from the preflight modal.

        Returns:
            dict[str, Any]: import modal view payload.

        Raises:
            ValidationError: if the draft is unknown.
            ExternalServiceError: if rename fails.
        """
        draft = self._require_draft(draft_id)
        canvas_id = self.canvas.ensure_canvas(draft.channel_id, rename=True)
        draft.canvas_id = canvas_id
        draft.preflight_state = PreflightState.READY.value
        view = render_import_view(ImportContext(draft_id=draft_id, prefilled_url=draft.command_url or None))
        return {**view, "callback_id": _CALLBACK_IMPORT}

    def decline_canvas(self, draft_id: str) -> None:
        """End the workflow without canvas changes.

        Args:
            draft_id: draft identifier from the preflight modal.
        """
        self.drafts.discard(draft_id)

    def submit_import_url(self, *, draft_id: str, page_url: str) -> dict[str, Any]:
        """Export ShotGrid assets and open the first asset page.

        Args:
            draft_id: draft identifier.
            page_url: ShotGrid page URL submitted by the user.

        Returns:
            dict[str, Any]: asset page modal payload.

        Raises:
            ValidationError: if the draft is unknown or URL/export invalid.
            ImportValidationError: if the export fails validation.
            ExternalServiceError: if ShotGrid export fails.
        """
        draft = self._require_draft(draft_id)
        page_id = parse_page_id(page_url, self.shotgrid_host)
        csv_text = self.shotgrid.export_page(page_id)
        imported = parse_export_csv(csv_text, self.shotgrid_base_url)
        title = infer_group_title(asset.name for asset in imported.assets)
        if title.endswith(":"):
            title = title[:-1].rstrip()

        draft.page_url = page_url
        draft.assets = imported.assets
        draft.duplicate_count = imported.duplicate_count
        draft.group_title = title
        draft.included_entity_ids = tuple(asset.entity_id for asset in imported.assets)
        draft.asset_animators = {}
        draft.asset_additional = {}
        draft.asset_links_text = {asset.entity_id: "" for asset in imported.assets}
        draft.imported_at = self.clock.now()
        draft.page_index = 0
        self.drafts.put(draft)

        asset_draft = self._to_asset_draft(draft)
        view = render_asset_page(asset_draft, 0)
        return {**view, "callback_id": _CALLBACK_ASSET}

    def save_asset_page(self, *, draft_id: str, page_index: int, view_state: dict[str, object]) -> DraftSession:
        """Decode and persist one asset page into the draft.

        Args:
            draft_id: draft identifier.
            page_index: page being saved.
            view_state: slack view state object.

        Returns:
            DraftSession: updated draft.

        Raises:
            ValidationError: if decode fails or draft is unknown.
        """
        draft = self._require_draft(draft_id)
        decoded = decode_asset_page_state(view_state, page_index)
        draft.group_title = decoded.group_title
        draft.group_animator_id = decoded.group_animator_id
        draft.group_additional_ids = decoded.group_additional_ids
        draft.group_links_text = decoded.group_links_text

        included = list(draft.included_entity_ids)
        for state in decoded.asset_states:
            if state.included:
                if state.entity_id not in included:
                    included.append(state.entity_id)
            elif state.entity_id in included:
                included = [entity_id for entity_id in included if entity_id != state.entity_id]
            if state.animator_id:
                draft.asset_animators[state.entity_id] = state.animator_id
            draft.asset_additional[state.entity_id] = state.additional_ids
            draft.asset_links_text[state.entity_id] = state.links_text
        draft.included_entity_ids = tuple(included)
        # recompute inferred title after exclusions when still season-shaped
        names = [asset.name for asset in draft.assets if asset.entity_id in draft.included_entity_ids]
        inferred = infer_group_title(names)
        if inferred and not draft.group_title.strip():
            draft.group_title = inferred[:-1].rstrip() if inferred.endswith(":") else inferred
        draft.page_index = page_index
        self.drafts.put(draft)
        return draft

    def open_asset_page(self, draft_id: str, page_index: int) -> dict[str, Any]:
        """Render an asset page for the draft.

        Args:
            draft_id: draft identifier.
            page_index: zero-based page index.

        Returns:
            dict[str, Any]: asset page modal payload.
        """
        draft = self._require_draft(draft_id)
        view = render_asset_page(self._to_asset_draft(draft), page_index)
        return {**view, "callback_id": _CALLBACK_ASSET}

    def open_confirmation(self, draft_id: str) -> dict[str, Any]:
        """Validate the draft and render the confirmation modal.

        Args:
            draft_id: draft identifier.

        Returns:
            dict[str, Any]: confirmation modal payload.

        Raises:
            ValidationError: if required fields or membership checks fail.
        """
        draft = self._require_draft(draft_id)
        self._validate_draft_for_confirm(draft)
        included = [asset for asset in draft.assets if asset.entity_id in set(draft.included_entity_ids)]
        context = ConfirmationContext(
            draft_id=draft.draft_id,
            target_channel_id=draft.channel_id,
            group_title=normalize_group_title(draft.group_title),
            included_count=len(included),
            deduped_row_count=len(draft.assets),
            existing_duplicate_thread_count=0,
            existing_duplicate_thread_links=(),
            warnings=(),
        )
        view = render_confirmation_view(context)
        return {**view, "callback_id": _CALLBACK_CONFIRM}

    def confirm_batch(self, draft: DraftSession) -> ConfirmResponse:
        """Acquire the channel lease and accept the batch, or report busy.

        Args:
            draft: draft session to confirm.

        Returns:
            ConfirmResponse: accepted lease result or busy private message.
        """
        self.drafts.put(draft)
        lease = self.leases.acquire(draft.channel_id, draft.user_id, self.clock.now(), _LEASE_TTL, workspace_id=draft.workspace_id)
        if not lease.acquired:
            owner_name = self._display_name(lease.owner_user_id)
            text = f"RED Team Prop Threader is currently creating threads for @{owner_name}."
            return ConfirmResponse(draft_id=draft.draft_id, private_text=text, accepted=False)

        if self.session is not None:
            self.session.commit()
        return ConfirmResponse(draft_id=draft.draft_id, private_text="Batch accepted. Creating threads…", accepted=True, lease_token=lease.token)

    def _validate_draft_for_confirm(self, draft: DraftSession) -> None:
        """Validate title, inclusion, people, and links before confirmation."""
        if not draft.included_entity_ids:
            raise ValidationError("at least one asset must remain included")
        title = normalize_group_title(draft.group_title)
        if not title:
            raise ValidationError("group title is required")
        if draft.group_animator_id is None:
            raise ValidationError("group animator is required")
        members = set(self.slack.get_conversation_members(draft.channel_id))
        people: set[str] = set(draft.group_additional_ids)
        if draft.group_animator_id is not None:
            people.add(draft.group_animator_id)
        for entity_id in draft.included_entity_ids:
            animator = draft.asset_animators.get(entity_id)
            if not animator:
                raise ValidationError(f"animator is required for asset {entity_id}")
            people.add(animator)
            people.update(draft.asset_additional.get(entity_id, ()))
        missing = validate_channel_members(people, members)
        if missing:
            raise ValidationError("selected users must be members of the target channel")
        if draft.group_links_text.strip():
            parse_supporting_links(draft.group_links_text)
        for entity_id in draft.included_entity_ids:
            links_text = draft.asset_links_text.get(entity_id, "")
            if links_text.strip():
                parse_supporting_links(links_text)

    def _to_asset_draft(self, draft: DraftSession) -> AssetDraft:
        """Convert a session draft into an AssetDraft for view rendering."""
        included = set(draft.included_entity_ids)
        selections = tuple(
            AssetSelection(
                entity_id=asset.entity_id,
                included=asset.entity_id in included,
                animator_id=draft.asset_animators.get(asset.entity_id),
                additional_ids=draft.asset_additional.get(asset.entity_id, ()),
                links_text=draft.asset_links_text.get(asset.entity_id, ""),
            )
            for asset in draft.assets
        )
        return AssetDraft(
            draft_id=draft.draft_id,
            assets=draft.assets,
            group_title=draft.group_title,
            group_animator_id=draft.group_animator_id,
            group_additional_ids=draft.group_additional_ids,
            group_links_text=draft.group_links_text,
            selections=selections,
        )

    def _require_draft(self, draft_id: str) -> DraftSession:
        """Return a draft or raise ValidationError."""
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ValidationError("draft not found or expired")
        return draft

    def _update_draft_view(self, draft: DraftSession, view: dict[str, Any]) -> None:
        """Update the open modal when a view id is available."""
        if not draft.view_id:
            return
        self.slack.update_view(draft.view_id, view, view_hash=draft.view_hash)

    def _display_name(self, user_id: str) -> str:
        """Resolve a non-notifying display name for busy-owner copy."""
        if not user_id:
            return "another user"
        try:
            info = self.slack.get_user_info(user_id)
        except ExternalServiceError:
            return user_id
        profile = info.get("profile") if isinstance(info.get("profile"), dict) else {}
        for key in ("display_name", "real_name"):
            value = profile.get(key) if isinstance(profile, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
        return user_id


def _blocked_view(draft_id: str, detail: str) -> dict[str, Any]:
    """Build a user-safe blocked preflight modal."""
    safe = detail.strip() or "canvas access is blocked"
    return {
        "type": "modal",
        "callback_id": _CALLBACK_PREFLIGHT,
        "title": {"type": "plain_text", "text": "Canvas Check"},
        "close": {"type": "plain_text", "text": "Close"},
        "private_metadata": draft_id,
        "blocks": [
            {
                "type": "section",
                "block_id": "preflight_blocked",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Canvas preflight blocked*\n"
                        f"{safe}\n\n"
                        "Invite the bot to this channel, confirm canvas permissions, "
                        "and verify the workspace plan supports channel canvases."
                    ),
                },
            }
        ],
    }
