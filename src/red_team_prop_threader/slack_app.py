"""bolt listener registration for RED Team Prop Threader."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from slack_bolt import App

from red_team_prop_threader.edits import (
    CALLBACK_ASSET_EDIT,
    CALLBACK_GROUP_EDIT,
    AID_EDIT_ASSET_DETAILS,
    AID_EDIT_GROUP_DETAILS,
    MessageRef,
    AssetEditRequest,
    GroupEditRequest,
    decode_edit_submission,
)
from red_team_prop_threader.views import AID_NAV_BACK, AID_NAV_NEXT, AID_NAV_CONFIRM, AID_CANVAS_CREATE, AID_CANVAS_RENAME, AID_CANVAS_DECLINE
from red_team_prop_threader._errors import ValidationError, ExternalServiceError, ImportValidationError


if TYPE_CHECKING:
    from collections.abc import Callable

    from red_team_prop_threader.edits import EditService
    from red_team_prop_threader.workflow import Workflow


__all__ = ("create_bolt_app", "register_listeners")

_CALLBACK_IMPORT = "import_assets"
_CALLBACK_CONFIRM = "confirm_batch"


def create_bolt_app(*, bot_token: str, signing_secret: str, process_before_response: bool = False) -> App:
    """Create a Bolt App configured for HTTPS request handling.

    Token verification at startup is disabled so local tests and cold starts do
    not require a live auth.test round-trip; request signature verification still
    uses the signing secret.

    Args:
        bot_token: slack bot token.
        signing_secret: slack signing secret.
        process_before_response: when False, ack can return before listener work finishes.

    Returns:
        App: configured Bolt application.
    """
    return App(token=bot_token, signing_secret=signing_secret, process_before_response=process_before_response, token_verification_enabled=False)


def register_listeners(app: App, workflow_factory: Callable[[], Workflow], edit_factory: Callable[[], EditService] | None = None) -> None:
    """Register slash-command, modal, and edit listeners.

    Args:
        app: bolt application.
        workflow_factory: callable returning a Workflow bound to request-scoped deps.
        edit_factory: optional callable returning an EditService for post-completion edits.
    """

    @app.command("/create-prop-threads")
    def handle_create_prop_threads(ack: Any, command: dict[str, Any], logger: Any) -> None:
        """Handle /create-prop-threads by acking then running preflight."""
        ack()
        workflow = workflow_factory()
        from red_team_prop_threader.workflow import CommandRequest

        try:
            workflow.handle_command(
                CommandRequest(
                    workspace_id=str(command.get("team_id") or ""),
                    channel_id=str(command.get("channel_id") or ""),
                    user_id=str(command.get("user_id") or ""),
                    trigger_id=str(command.get("trigger_id") or ""),
                    text=str(command.get("text") or ""),
                    response_url=str(command.get("response_url") or ""),
                )
            )
        except Exception:
            logger.exception("create-prop-threads failed")

    @app.action(AID_CANVAS_CREATE)
    def handle_canvas_create(ack: Any, body: dict[str, Any], client: Any) -> None:
        """Create canvas then show import modal."""
        ack()
        workflow = workflow_factory()
        draft_id = _action_value(body)
        view = workflow.confirm_canvas_create(draft_id)
        _replace_view(client, body, view)

    @app.action(AID_CANVAS_RENAME)
    def handle_canvas_rename(ack: Any, body: dict[str, Any], client: Any) -> None:
        """Rename canvas then show import modal."""
        ack()
        workflow = workflow_factory()
        draft_id = _action_value(body)
        view = workflow.confirm_canvas_rename(draft_id)
        _replace_view(client, body, view)

    @app.action(AID_CANVAS_DECLINE)
    def handle_canvas_decline(ack: Any, body: dict[str, Any]) -> None:
        """Decline canvas changes and discard the draft."""
        ack()
        workflow = workflow_factory()
        workflow.decline_canvas(_action_value(body))

    @app.view(_CALLBACK_IMPORT)
    def handle_import_submit(ack: Any, body: dict[str, Any], view: dict[str, Any], client: Any) -> None:
        """Export ShotGrid page and open asset page 0."""
        workflow = workflow_factory()
        draft_id = str(view.get("private_metadata") or "")
        page_url = _import_url_from_view(view)
        try:
            next_view = workflow.submit_import_url(draft_id=draft_id, page_url=page_url)
        except (ValidationError, ImportValidationError, ExternalServiceError) as exc:
            ack(response_action="errors", errors={"import_url": str(exc)})
            return
        ack(response_action="update", view=next_view)

    @app.action(AID_NAV_NEXT)
    def handle_nav_next(ack: Any, body: dict[str, Any], client: Any) -> None:
        """Save current page and open the next asset page."""
        ack()
        _navigate(workflow_factory(), body, client, delta=1)

    @app.action(AID_NAV_BACK)
    def handle_nav_back(ack: Any, body: dict[str, Any], client: Any) -> None:
        """Save current page and open the previous asset page."""
        ack()
        _navigate(workflow_factory(), body, client, delta=-1)

    @app.action(AID_NAV_CONFIRM)
    def handle_nav_confirm(ack: Any, body: dict[str, Any], client: Any) -> None:
        """Save final asset page and open confirmation."""
        ack()
        workflow = workflow_factory()
        draft_id = _action_value(body)
        view = _as_dict(body.get("view"))
        state = _as_dict(view.get("state"))
        draft = workflow.drafts.get(draft_id)
        page_index = draft.page_index if draft is not None else 0
        workflow.save_asset_page(draft_id=draft_id, page_index=page_index, view_state=state)
        next_view = workflow.open_confirmation(draft_id)
        _replace_view(client, body, next_view)

    @app.view(_CALLBACK_CONFIRM)
    def handle_confirm_submit(ack: Any, body: dict[str, Any], view: dict[str, Any], client: Any) -> None:
        """Acquire lease and accept or reject the batch."""
        workflow = workflow_factory()
        draft_id = str(view.get("private_metadata") or "")
        draft = workflow.drafts.get(draft_id)
        if draft is None:
            ack(response_action="errors", errors={"confirm_group_title": "draft not found or expired"})
            return
        title = _confirm_title_from_view(view)
        if title:
            draft.group_title = title
        try:
            workflow._validate_draft_for_confirm(draft)
        except ValidationError as exc:
            ack(response_action="errors", errors={"confirm_group_title": str(exc)})
            return
        response = workflow.confirm_batch(draft)
        if not response.accepted:
            ack()
            client.chat_postEphemeral(channel=draft.channel_id, user=draft.user_id, text=response.private_text)
            return
        ack()
        client.chat_postEphemeral(channel=draft.channel_id, user=draft.user_id, text=response.private_text)

    if edit_factory is not None:
        _register_edit_listeners(app, edit_factory)


def _register_edit_listeners(app: App, edit_factory: Callable[[], EditService]) -> None:
    """Register latest-only asset/group edit action and view handlers."""

    @app.action(AID_EDIT_ASSET_DETAILS)
    def handle_edit_asset_details(ack: Any, body: dict[str, Any], client: Any) -> None:
        """Open the asset editor or refuse a historical root."""
        ack()
        result = edit_factory().open_asset_editor(_message_ref_from_action(body))
        if result.refused:
            _post_ephemeral(client, body, result.ephemeral_text or "This message is historical.")
            return
        if result.view is not None:
            client.views_open(trigger_id=str(body.get("trigger_id") or ""), view=result.view)

    @app.action(AID_EDIT_GROUP_DETAILS)
    def handle_edit_group_details(ack: Any, body: dict[str, Any], client: Any) -> None:
        """Open the group editor or refuse a historical summary."""
        ack()
        result = edit_factory().open_group_editor(_message_ref_from_action(body))
        if result.refused:
            _post_ephemeral(client, body, result.ephemeral_text or "This message is historical.")
            return
        if result.view is not None:
            client.views_open(trigger_id=str(body.get("trigger_id") or ""), view=result.view)

    @app.view(CALLBACK_ASSET_EDIT)
    def handle_asset_edit_submit(ack: Any, body: dict[str, Any], view: dict[str, Any]) -> None:
        """Apply a latest-only asset edit."""
        channel_id, message_ts, animator_id, additional_ids, links_text = decode_edit_submission(view)
        try:
            edit_factory().apply_asset_edit(
                AssetEditRequest(
                    workspace_id=_workspace_id_from_body(body),
                    channel_id=channel_id,
                    user_id=_user_id_from_body(body),
                    message_ts=message_ts,
                    animator_id=animator_id,
                    additional_ids=additional_ids,
                    links_text=links_text,
                )
            )
        except ValidationError as exc:
            ack(response_action="errors", errors={"edit_animator": str(exc)})
            return
        ack()

    @app.view(CALLBACK_GROUP_EDIT)
    def handle_group_edit_submit(ack: Any, body: dict[str, Any], view: dict[str, Any]) -> None:
        """Apply a latest-only group edit across summary, roots, and canvas."""
        channel_id, message_ts, animator_id, additional_ids, links_text = decode_edit_submission(view)
        try:
            edit_factory().apply_group_edit(
                GroupEditRequest(
                    workspace_id=_workspace_id_from_body(body),
                    channel_id=channel_id,
                    user_id=_user_id_from_body(body),
                    message_ts=message_ts,
                    animator_id=animator_id,
                    additional_ids=additional_ids,
                    links_text=links_text,
                )
            )
        except ValidationError as exc:
            ack(response_action="errors", errors={"edit_animator": str(exc)})
            return
        ack()


def _message_ref_from_action(body: dict[str, Any]) -> MessageRef:
    """Build a MessageRef from a block-action payload."""
    user = _as_dict(body.get("user"))
    team = _as_dict(body.get("team"))
    container = _as_dict(body.get("container"))
    channel = _as_dict(body.get("channel"))
    message = _as_dict(body.get("message"))
    message_ts = str(container.get("message_ts") or message.get("ts") or "")
    return MessageRef(
        workspace_id=str(team.get("id") or body.get("team_id") or ""),
        channel_id=str(channel.get("id") or container.get("channel_id") or ""),
        user_id=str(user.get("id") or ""),
        message_ts=message_ts,
        message_identity=_action_value(body),
        trigger_id=str(body.get("trigger_id") or "") or None,
    )


def _workspace_id_from_body(body: dict[str, Any]) -> str:
    """Extract workspace/team id from an interactivity body."""
    team = _as_dict(body.get("team"))
    return str(team.get("id") or body.get("team_id") or "")


def _user_id_from_body(body: dict[str, Any]) -> str:
    """Extract user id from an interactivity body."""
    user = _as_dict(body.get("user"))
    return str(user.get("id") or "")


def _post_ephemeral(client: Any, body: dict[str, Any], text: str) -> None:
    """Post an ephemeral reply for a refused edit."""
    user = _as_dict(body.get("user"))
    channel = _as_dict(body.get("channel"))
    container = _as_dict(body.get("container"))
    channel_id = str(channel.get("id") or container.get("channel_id") or "")
    user_id = str(user.get("id") or "")
    if channel_id and user_id:
        client.chat_postEphemeral(channel=channel_id, user=user_id, text=text)


def _navigate(workflow: Workflow, body: dict[str, Any], client: Any, *, delta: int) -> None:
    """Save the current page and open page_index + delta."""
    draft_id = _action_value(body)
    view = _as_dict(body.get("view"))
    state = _as_dict(view.get("state"))
    draft = workflow.drafts.get(draft_id)
    page_index = draft.page_index if draft is not None else 0
    workflow.save_asset_page(draft_id=draft_id, page_index=page_index, view_state=state)
    next_view = workflow.open_asset_page(draft_id, page_index + delta)
    _replace_view(client, body, next_view)


def _replace_view(client: Any, body: dict[str, Any], view: dict[str, Any]) -> None:
    """Update the active modal from an action payload."""
    current = _as_dict(body.get("view"))
    view_id = str(current.get("id") or "")
    view_hash = str(current.get("hash") or "") or None
    if view_id:
        client.views_update(view_id=view_id, hash=view_hash, view=view)


def _action_value(body: dict[str, Any]) -> str:
    """Extract the first action value from an interactivity body."""
    actions = body.get("actions") if isinstance(body.get("actions"), list) else []
    if not actions:
        return ""
    first = actions[0]
    if isinstance(first, dict):
        return str(first.get("value") or "")
    return ""


def _as_dict(value: object) -> dict[str, Any]:
    """Return value when it is a dict, otherwise an empty dict."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _nested_value(view: dict[str, Any], block_id: str, action_id: str) -> str:
    """Read a plain-text input value from a modal view state."""
    state = _as_dict(view.get("state"))
    values = _as_dict(state.get("values"))
    block = _as_dict(values.get(block_id))
    field = _as_dict(block.get(action_id))
    return str(field.get("value") or "").strip()


def _import_url_from_view(view: dict[str, Any]) -> str:
    """Read the ShotGrid URL from the import modal state."""
    return _nested_value(view, "import_url", "import_url")


def _confirm_title_from_view(view: dict[str, Any]) -> str:
    """Read the editable group title from the confirmation modal."""
    return _nested_value(view, "confirm_group_title", "confirm_group_title")
