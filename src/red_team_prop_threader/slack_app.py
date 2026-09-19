"""bolt listener registration for RED Team Prop Threader."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from slack_bolt import App

from red_team_prop_threader.adopt import format_adopt_ephemeral
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
from red_team_prop_threader.views import (
    AID_NAV_BACK,
    AID_NAV_NEXT,
    AID_NAV_CONFIRM,
    AID_CANVAS_CREATE,
    AID_CANVAS_RENAME,
    AID_CANVAS_DECLINE,
    render_working_view,
    with_form_error_notice,
    constrain_asset_page_errors,
)
from red_team_prop_threader._errors import ValidationError, ExternalServiceError, ImportValidationError


if TYPE_CHECKING:
    from collections.abc import Callable

    from red_team_prop_threader.adopt import AdoptService
    from red_team_prop_threader.edits import EditService
    from red_team_prop_threader.workflow import Workflow


__all__ = ("create_bolt_app", "register_listeners")

_CALLBACK_IMPORT = "import_assets"
_CALLBACK_ASSET = "asset_page"
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


def register_listeners(
    app: App,
    workflow_factory: Callable[[], Workflow],
    edit_factory: Callable[[], EditService] | None = None,
    adopt_factory: Callable[[], AdoptService] | None = None,
) -> None:
    """Register slash-command, modal, and edit listeners.

    Args:
        app: bolt application.
        workflow_factory: callable returning a Workflow bound to request-scoped deps.
        edit_factory: optional callable returning an EditService for post-completion edits.
        adopt_factory: optional callable returning an AdoptService for /adopt-prop-threads.
    """

    @app.command("/create-prop-threads")
    def handle_create_prop_threads(ack: Any, command: dict[str, Any], logger: Any) -> None:
        """Ack immediately, then open a loading modal and finish preflight.

        Slack times out slash commands at about three seconds. Preflight and
        ShotGrid export must not hold the ack or the trigger_id.
        """
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
        except Exception as exc:
            logger.exception("create-prop-threads failed: %s", exc)

    @app.command("/adopt-prop-threads")
    def handle_adopt_prop_threads(ack: Any, command: dict[str, Any], client: Any, logger: Any) -> None:
        """Ack immediately, then adopt INDEX Latest and leftover roots."""
        ack()
        channel_id = str(command.get("channel_id") or "")
        user_id = str(command.get("user_id") or "")
        if adopt_factory is None:
            _post_command_ephemeral(client, channel_id, user_id, "Adopt is not configured.")
            return
        try:
            result = adopt_factory().run(channel_id)
            _post_command_ephemeral(client, channel_id, user_id, format_adopt_ephemeral(result))
        except Exception as exc:
            logger.exception("adopt-prop-threads failed: %s", exc)
            _post_command_ephemeral(client, channel_id, user_id, "Adopt failed. Try again.")

    @app.action(AID_CANVAS_CREATE)
    def handle_canvas_create(ack: Any, body: dict[str, Any], client: Any, logger: Any) -> None:
        """Create canvas then show import or Assets p.1 (when a command URL exists)."""
        ack()
        workflow = workflow_factory()
        draft_id = _action_value(body)
        try:
            view = workflow.confirm_canvas_create(draft_id)
            _replace_view(client, body, view)
        except Exception:
            logger.exception("canvas create failed")

    @app.action(AID_CANVAS_RENAME)
    def handle_canvas_rename(ack: Any, body: dict[str, Any], client: Any, logger: Any) -> None:
        """Rename canvas then show import or Assets p.1 (when a command URL exists)."""
        ack()
        workflow = workflow_factory()
        draft_id = _action_value(body)
        try:
            view = workflow.confirm_canvas_rename(draft_id)
            _replace_view(client, body, view)
        except Exception:
            logger.exception("canvas rename failed")

    @app.action(AID_CANVAS_DECLINE)
    def handle_canvas_decline(ack: Any, body: dict[str, Any]) -> None:
        """Decline canvas changes and discard the draft."""
        ack()
        workflow = workflow_factory()
        workflow.decline_canvas(_action_value(body))

    @app.view(_CALLBACK_IMPORT)
    def handle_import_submit(ack: Any, body: dict[str, Any], view: dict[str, Any], client: Any, logger: Any) -> None:
        """Ack a loading view, then export ShotGrid and open asset page 0.

        ShotGrid export and channel-member hydration can exceed Slack's three
        second view-submit window, especially on Respawn-hosted channels.
        """
        workflow = workflow_factory()
        draft_id = str(view.get("private_metadata") or "")
        page_url = _import_url_from_view(view)
        ack(response_action="update", view=render_working_view(draft_id, title="Import Assets", message="Importing from ShotGrid…"))
        try:
            next_view = workflow.submit_import_url(draft_id=draft_id, page_url=page_url)
        except (ValidationError, ImportValidationError, ExternalServiceError) as exc:
            logger.warning("import submit blocked draft_id=%s error=%s", draft_id, exc)
            _replace_view(client, body, _import_retry_view(draft_id, page_url), include_hash=False)
            _notify_draft_user(client, workflow.drafts.get(draft_id), str(exc), logger)
            return
        except Exception:
            logger.exception("import submit failed draft_id=%s", draft_id)
            _replace_view(client, body, _import_retry_view(draft_id, page_url), include_hash=False)
            _notify_draft_user(client, workflow.drafts.get(draft_id), "import failed; try again", logger)
            return
        _replace_view(client, body, next_view, include_hash=False)

    @app.view(_CALLBACK_ASSET)
    def handle_asset_page_submit(ack: Any, body: dict[str, Any], view: dict[str, Any], client: Any, logger: Any) -> None:
        """Handle the required modal submit on an asset page (Next or Confirm).

        Local save can fail-fast with field errors. Member checks and picker
        hydration run after ack so Slack Connect / Respawn channels cannot
        expire the view submission.
        """
        workflow = workflow_factory()
        draft_id = str(view.get("private_metadata") or "")
        state = _as_dict(view.get("state"))
        draft = workflow.drafts.get(draft_id)
        page_index = draft.page_index if draft is not None else 0
        try:
            workflow.save_asset_page(draft_id=draft_id, page_index=page_index, view_state=state)
        except ValidationError as exc:
            ack(response_action="errors", errors=with_form_error_notice({"group_title": str(exc)}))
            return

        ack(response_action="update", view=render_working_view(draft_id, title="Assets", message="Saving and checking names…"))
        try:
            next_view = workflow.open_asset_page(draft_id, page_index + 1)
        except ValidationError:
            draft = workflow.drafts.get(draft_id)
            if draft is None:
                logger.warning("asset page submit lost draft_id=%s", draft_id)
                return
            try:
                field_errors = workflow._confirm_field_errors(draft)
            except ExternalServiceError as exc:
                logger.exception("asset page confirm membership check failed draft_id=%s", draft_id)
                _notify_draft_user(client, draft, str(exc), logger)
                _restore_asset_page(workflow, client, body, draft_id, page_index, logger)
                return
            if field_errors:
                logger.warning("asset page confirm blocked draft_id=%s errors=%s", draft_id, field_errors)
                _restore_asset_page(workflow, client, body, draft_id, page_index, logger)
                constrained = constrain_asset_page_errors(
                    field_errors, page_index=draft.page_index, entity_ids=tuple(asset.entity_id for asset in draft.assets)
                )
                message = next(iter(constrained.values()), next(iter(field_errors.values())))
                _notify_draft_user(client, draft, message, logger)
                return
            try:
                next_view = workflow.open_confirmation(draft_id)
            except (ValidationError, ExternalServiceError) as exc:
                _notify_draft_user(client, draft, str(exc), logger)
                _restore_asset_page(workflow, client, body, draft_id, page_index, logger)
                return
        except Exception:
            logger.exception("asset page submit failed draft_id=%s", draft_id)
            _notify_draft_user(client, workflow.drafts.get(draft_id), "could not continue; try again", logger)
            return
        _replace_view(client, body, next_view, include_hash=False)

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
    def handle_nav_confirm(ack: Any, body: dict[str, Any], client: Any, logger: Any) -> None:
        """Save final asset page and open confirmation."""
        ack()
        workflow = workflow_factory()
        draft_id = _action_value(body)
        view = _as_dict(body.get("view"))
        state = _as_dict(view.get("state"))
        draft = workflow.drafts.get(draft_id)
        page_index = draft.page_index if draft is not None else 0
        try:
            workflow.save_asset_page(draft_id=draft_id, page_index=page_index, view_state=state)
            next_view = workflow.open_confirmation(draft_id)
            _replace_view(client, body, next_view)
        except ValidationError as exc:
            draft = workflow.drafts.get(draft_id)
            if draft is not None:
                client.chat_postEphemeral(channel=draft.channel_id, user=draft.user_id, text=str(exc))
            else:
                logger.warning("nav confirm validation failed: %s", exc)
        except Exception:
            logger.exception("nav confirm failed")

    @app.view(_CALLBACK_CONFIRM)
    def handle_confirm_submit(ack: Any, body: dict[str, Any], view: dict[str, Any], client: Any, logger: Any) -> None:
        """Close the modal immediately, then lease and enqueue the batch.

        Membership checks and persistence must not hold the view ack. A late
        ack looks like the prompt closed with nothing posted.
        """
        del body
        workflow = workflow_factory()
        draft_id = str(view.get("private_metadata") or "")
        draft = workflow.drafts.get(draft_id)
        if draft is None:
            ack(response_action="errors", errors={"confirm_group_title": "draft not found or expired"})
            return
        title = _confirm_title_from_view(view)
        if title:
            draft.group_title = title
        ack()
        try:
            field_errors = workflow._confirm_field_errors(draft)
            if field_errors:
                message = field_errors.get("group_animator") or field_errors.get("group_title") or next(iter(field_errors.values()))
                _notify_draft_user(client, draft, message, logger)
                return
            response = workflow.confirm_batch(draft)
            _notify_draft_user(client, draft, response.private_text, logger)
        except Exception:
            logger.exception("confirm submit failed draft_id=%s", draft_id)
            _notify_draft_user(client, draft, "could not start posting; invite the bot to this channel and try again", logger)

    if edit_factory is not None:
        _register_edit_listeners(app, edit_factory)


def _register_edit_listeners(app: App, edit_factory: Callable[[], EditService]) -> None:
    """Register latest-only asset/group edit action and view handlers."""

    @app.action(AID_EDIT_ASSET_DETAILS)
    def handle_edit_asset_details(ack: Any, body: dict[str, Any], client: Any, logger: Any) -> None:
        """Open the asset editor or refuse a historical root."""
        _open_edit_modal(ack, body, client, logger, title="Edit POCs", opener=lambda ref: edit_factory().open_asset_editor(ref))

    @app.action(AID_EDIT_GROUP_DETAILS)
    def handle_edit_group_details(ack: Any, body: dict[str, Any], client: Any, logger: Any) -> None:
        """Open the group editor or refuse a historical summary."""
        _open_edit_modal(ack, body, client, logger, title="Edit Group Details", opener=lambda ref: edit_factory().open_group_editor(ref))

    @app.view(CALLBACK_ASSET_EDIT)
    def handle_asset_edit_submit(ack: Any, body: dict[str, Any], view: dict[str, Any], client: Any, logger: Any) -> None:
        """Ack immediately, then apply a latest-only asset edit."""
        channel_id, message_ts, animator_id, additional_ids, links_text = decode_edit_submission(view)
        ack()
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
            _post_ephemeral(client, body, str(exc))
        except Exception:
            logger.exception("asset edit apply failed")
            _post_ephemeral(client, body, "Could not save the edit. Try again.")

    @app.view(CALLBACK_GROUP_EDIT)
    def handle_group_edit_submit(ack: Any, body: dict[str, Any], view: dict[str, Any], client: Any, logger: Any) -> None:
        """Ack immediately, then apply a latest-only group edit."""
        channel_id, message_ts, animator_id, additional_ids, links_text = decode_edit_submission(view)
        ack()
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
            _post_ephemeral(client, body, str(exc))
        except Exception:
            logger.exception("group edit apply failed")
            _post_ephemeral(client, body, "Could not save the edit. Try again.")


def _open_edit_modal(ack: Any, body: dict[str, Any], client: Any, logger: Any, *, title: str, opener: Any) -> None:
    """Ack, spend the trigger_id on a loading modal, then replace it with the editor.

    Block-action trigger ids expire in about three seconds. Building the people
    pickers calls conversations.members and users.info, which is too slow to do
    before views.open on Respawn-hosted or Slack Connect channels.

    Args:
        ack: bolt ack callable.
        body: block-action payload.
        client: slack web client.
        logger: bolt logger.
        title: modal title for loading and error screens.
        opener: callable taking a MessageRef and returning EditOpenResult.
    """
    ack()
    trigger_id = str(body.get("trigger_id") or "")
    loading = render_working_view("edit-modal", title=title, message="Loading channel members…")
    try:
        opened = client.views_open(trigger_id=trigger_id, view=loading)
    except Exception:
        logger.exception("edit modal views.open failed title=%s", title)
        _post_ephemeral(client, body, "Could not open the editor. Try again.")
        return
    view_id = _view_id_from_open(opened)
    try:
        result = opener(_message_ref_from_action(body))
    except Exception:
        logger.exception("edit modal open failed title=%s", title)
        _replace_opened_view(client, view_id, render_working_view("edit-modal", title=title, message="Could not open the editor. Try again."))
        _post_ephemeral(client, body, "Could not open the editor. Try again.")
        return
    if result.refused:
        message = result.ephemeral_text or "This message is historical."
        _post_ephemeral(client, body, message)
        _replace_opened_view(client, view_id, render_working_view("edit-modal", title=title, message=message))
        return
    if result.view is not None:
        _replace_opened_view(client, view_id, result.view)


def _view_id_from_open(opened: Any) -> str:
    """Read the view id from a views.open response."""
    data = opened.data if hasattr(opened, "data") and isinstance(opened.data, dict) else opened
    if not isinstance(data, dict):
        return ""
    view = data.get("view")
    if not isinstance(view, dict):
        return ""
    return str(view.get("id") or "")


def _replace_opened_view(client: Any, view_id: str, view: dict[str, Any]) -> None:
    """Replace a modal opened in this handler, omitting a stale hash."""
    if not view_id:
        return
    client.views_update(view_id=view_id, view=view)


def _message_ref_from_action(body: dict[str, Any]) -> MessageRef:
    """Build a MessageRef from a block-action payload."""
    user = _as_dict(body.get("user"))
    container = _as_dict(body.get("container"))
    channel = _as_dict(body.get("channel"))
    message = _as_dict(body.get("message"))
    message_ts = str(container.get("message_ts") or message.get("ts") or "")
    return MessageRef(
        workspace_id=_workspace_id_from_body(body),
        channel_id=str(channel.get("id") or container.get("channel_id") or ""),
        user_id=str(user.get("id") or ""),
        message_ts=message_ts,
        message_identity=_action_value(body),
        trigger_id=str(body.get("trigger_id") or "") or None,
    )


def _workspace_id_from_body(body: dict[str, Any]) -> str:
    """Extract workspace/team id from an interactivity body.

    Slack Connect and Grid payloads may put the team on ``team``, ``team_id``,
    or ``user.team_id``. Prefer the top-level team, then the user's home team.
    """
    team = _as_dict(body.get("team"))
    user = _as_dict(body.get("user"))
    return str(team.get("id") or body.get("team_id") or user.get("team_id") or "")


def _user_id_from_body(body: dict[str, Any]) -> str:
    """Extract user id from an interactivity body."""
    user = _as_dict(body.get("user"))
    return str(user.get("id") or "")


def _post_command_ephemeral(client: Any, channel_id: str, user_id: str, text: str) -> None:
    """Post an ephemeral reply for a slash command."""
    if channel_id and user_id:
        client.chat_postEphemeral(channel=channel_id, user=user_id, text=text)


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


def _replace_view(client: Any, body: dict[str, Any], view: dict[str, Any], *, include_hash: bool = True) -> None:
    """Update the active modal from an action or view-submit payload.

    After a view-submit ack with response_action=update, the original hash is
    stale and must be omitted or Slack rejects the follow-up views.update.

    Args:
        client: slack web client.
        body: interactivity payload containing the current view id/hash.
        view: replacement modal payload.
        include_hash: when False, omit hash (required after view-submit ack).
    """
    current = _as_dict(body.get("view"))
    view_id = str(current.get("id") or "")
    view_hash = str(current.get("hash") or "") or None
    if not view_id:
        return
    kwargs: dict[str, Any] = {"view_id": view_id, "view": view}
    if include_hash and view_hash:
        kwargs["hash"] = view_hash
    client.views_update(**kwargs)


def _import_retry_view(draft_id: str, page_url: str) -> dict[str, Any]:
    """Re-open the import modal after a post-ack import failure."""
    from red_team_prop_threader.views import ImportContext, render_import_view

    view = render_import_view(ImportContext(draft_id=draft_id, prefilled_url=page_url or None))
    return {**view, "callback_id": _CALLBACK_IMPORT}


def _restore_asset_page(workflow: Any, client: Any, body: dict[str, Any], draft_id: str, page_index: int, logger: Any) -> None:
    """Put the saved asset page back on screen after a post-ack confirm failure."""
    try:
        next_view = workflow.open_asset_page(draft_id, page_index)
    except Exception:
        logger.exception("could not restore asset page draft_id=%s", draft_id)
        return
    _replace_view(client, body, next_view, include_hash=False)


def _notify_draft_user(client: Any, draft: Any, text: str, logger: Any) -> None:
    """Post an ephemeral to the draft channel, logging if Slack refuses it."""
    if draft is None:
        return
    channel_id = str(getattr(draft, "channel_id", "") or "")
    user_id = str(getattr(draft, "user_id", "") or "")
    if not channel_id or not user_id:
        return
    try:
        client.chat_postEphemeral(channel=channel_id, user=user_id, text=text)
    except Exception:
        logger.exception("ephemeral failed channel=%s user=%s", channel_id, user_id)


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
