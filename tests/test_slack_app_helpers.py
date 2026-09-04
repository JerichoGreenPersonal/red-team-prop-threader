"""tests for slack_app helper parsing and listener registration."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from red_team_prop_threader.edits import CALLBACK_ASSET_EDIT, CALLBACK_GROUP_EDIT, EditOpenResult
from red_team_prop_threader._errors import ValidationError
from red_team_prop_threader.messages import AID_EDIT_ASSET_DETAILS, AID_EDIT_GROUP_DETAILS
from red_team_prop_threader.slack_app import (
    _as_dict,
    _action_value,
    _post_ephemeral,
    create_bolt_app,
    _user_id_from_body,
    register_listeners,
    _import_url_from_view,
    _workspace_id_from_body,
    _confirm_title_from_view,
    _message_ref_from_action,
)


def test_create_bolt_app_disables_startup_token_check() -> None:
    """Bolt app is constructed without live auth.test."""
    with patch("red_team_prop_threader.slack_app.App") as app_cls:
        create_bolt_app(bot_token="xoxb-t", signing_secret="s", process_before_response=False)
    kwargs = app_cls.call_args.kwargs
    assert kwargs["token_verification_enabled"] is False
    assert kwargs["process_before_response"] is False


def test_body_helpers() -> None:
    """Helper extractors read nested interactivity payloads."""
    body = {
        "team": {"id": "T1"},
        "user": {"id": "U1"},
        "channel": {"id": "C1"},
        "container": {"channel_id": "C1", "message_ts": "9.9"},
        "message": {"ts": "9.9"},
        "trigger_id": "trig",
        "actions": [{"value": "identity"}],
    }
    assert _as_dict(None) == {}
    assert _action_value(body) == "identity"
    assert _action_value({}) == ""
    assert _workspace_id_from_body(body) == "T1"
    assert _workspace_id_from_body({"user": {"id": "U1", "team_id": "T_USER"}}) == "T_USER"
    assert _user_id_from_body(body) == "U1"
    ref = _message_ref_from_action(body)
    assert ref.channel_id == "C1"
    assert ref.message_ts == "9.9"
    assert ref.message_identity == "identity"
    assert _import_url_from_view({"state": {"values": {"import_url": {"import_url": {"value": " https://x "}}}}}) == "https://x"
    assert _confirm_title_from_view({"state": {"values": {"confirm_group_title": {"confirm_group_title": {"value": " TITLE "}}}}}) == "TITLE"

    client = MagicMock()
    _post_ephemeral(client, body, "hello")
    client.chat_postEphemeral.assert_called_once()


def test_register_listeners_wires_edit_handlers() -> None:
    """Edit factory registers action and view callbacks."""
    app = MagicMock()
    registered: dict[str, Any] = {}

    def _command(name: str):
        def deco(fn: Any) -> Any:
            registered[f"command:{name}"] = fn
            return fn

        return deco

    def _action(name: str):
        def deco(fn: Any) -> Any:
            registered[f"action:{name}"] = fn
            return fn

        return deco

    def _view(name: str):
        def deco(fn: Any) -> Any:
            registered[f"view:{name}"] = fn
            return fn

        return deco

    app.command.side_effect = _command
    app.action.side_effect = _action
    app.view.side_effect = _view

    workflow = MagicMock()
    edit = MagicMock()
    edit.open_asset_editor.return_value = EditOpenResult(refused=True, ephemeral_text="historical")
    edit.open_group_editor.return_value = EditOpenResult(refused=False, view={"type": "modal"})

    register_listeners(app, lambda: workflow, lambda: edit)

    assert f"action:{AID_EDIT_ASSET_DETAILS}" in registered
    assert f"action:{AID_EDIT_GROUP_DETAILS}" in registered
    assert f"view:{CALLBACK_ASSET_EDIT}" in registered
    assert f"view:{CALLBACK_GROUP_EDIT}" in registered

    ack = MagicMock()
    client = MagicMock()
    logger = MagicMock()
    client.views_open.return_value = {"ok": True, "view": {"id": "Vedit"}}
    body = {
        "team": {"id": "T1"},
        "user": {"id": "U1"},
        "channel": {"id": "C1"},
        "container": {"message_ts": "1.1", "channel_id": "C1"},
        "trigger_id": "trig",
        "actions": [{"value": "x"}],
    }
    registered[f"action:{AID_EDIT_ASSET_DETAILS}"](ack, body, client, logger)
    client.views_open.assert_called()
    opened_view = client.views_open.call_args.kwargs["view"]
    assert "Loading channel members" in str(opened_view)
    client.chat_postEphemeral.assert_called()

    client.reset_mock()
    client.views_open.return_value = {"ok": True, "view": {"id": "Vedit"}}
    registered[f"action:{AID_EDIT_GROUP_DETAILS}"](ack, body, client, logger)
    client.views_open.assert_called()
    client.views_update.assert_called()


def test_register_listeners_command_and_nav_paths() -> None:
    """Slash command and navigation listeners invoke the workflow factory."""
    app = MagicMock()
    registered: dict[str, Any] = {}

    def _wrap(kind: str):
        def deco_factory(name: str):
            def deco(fn: Any) -> Any:
                registered[f"{kind}:{name}"] = fn
                return fn

            return deco

        return deco_factory

    app.command.side_effect = _wrap("command")
    app.action.side_effect = _wrap("action")
    app.view.side_effect = _wrap("view")

    workflow = MagicMock()
    workflow.drafts.get.return_value = MagicMock(page_index=0, view_id="V1", view_hash="h")
    workflow.open_asset_page.return_value = {"type": "modal"}
    workflow.open_confirmation.return_value = {"type": "modal", "callback_id": "confirm_batch"}
    workflow.confirm_batch.return_value = MagicMock(accepted=True, private_text="ok")
    from red_team_prop_threader.views import AID_NAV_BACK, AID_NAV_NEXT, AID_NAV_CONFIRM

    register_listeners(app, lambda: workflow, None)
    ack = MagicMock()
    client = MagicMock()
    body = {"view": {"id": "V1", "hash": "h", "state": {"values": {}}}, "actions": [{"value": "draft-1"}]}

    registered["command:/create-prop-threads"](
        ack, {"team_id": "T1", "channel_id": "C1", "user_id": "U1", "trigger_id": "t", "text": "", "response_url": ""}, MagicMock()
    )
    workflow.handle_command.assert_called_once()
    ack.assert_called_once()

    registered[f"action:{AID_NAV_NEXT}"](ack, body, client)
    registered[f"action:{AID_NAV_BACK}"](ack, body, client)
    registered[f"action:{AID_NAV_CONFIRM}"](ack, body, client, MagicMock())
    assert workflow.save_asset_page.call_count >= 3
    workflow.open_confirmation.assert_called()


def test_register_listeners_adopt_command() -> None:
    """Slash /adopt-prop-threads acks then runs AdoptService."""
    app = MagicMock()
    registered: dict[str, Any] = {}

    def _wrap(kind: str):
        def deco_factory(name: str):
            def deco(fn: Any) -> Any:
                registered[f"{kind}:{name}"] = fn
                return fn

            return deco

        return deco_factory

    app.command.side_effect = _wrap("command")
    app.action.side_effect = _wrap("action")
    app.view.side_effect = _wrap("view")

    adopt = MagicMock()
    adopt.run.return_value = MagicMock(adopted=(1,), unmatched=(), history_available=True, detail=None)
    register_listeners(app, MagicMock, None, lambda: adopt)
    ack = MagicMock()
    client = MagicMock()
    registered["command:/adopt-prop-threads"](
        ack, {"channel_id": "C1", "user_id": "U1"}, client, MagicMock()
    )
    ack.assert_called_once()
    adopt.run.assert_called_once_with("C1")
    client.chat_postEphemeral.assert_called_once()


def test_view_submits_ack_before_slow_work() -> None:
    """Import, asset confirm, and post-threads must ack before Slack API work."""
    app = MagicMock()
    registered: dict[str, Any] = {}

    def _wrap(kind: str):
        def deco_factory(name: str):
            def deco(fn: Any) -> Any:
                registered[f"{kind}:{name}"] = fn
                return fn

            return deco

        return deco_factory

    app.command.side_effect = _wrap("command")
    app.action.side_effect = _wrap("action")
    app.view.side_effect = _wrap("view")

    workflow = MagicMock()
    draft = MagicMock(page_index=0, channel_id="C1", user_id="U1", assets=())
    workflow.drafts.get.return_value = draft
    workflow._confirm_field_errors.return_value = {}

    register_listeners(app, lambda: workflow, None)
    ack = MagicMock()
    client = MagicMock()
    logger = MagicMock()
    view_body = {"view": {"id": "V1", "hash": "h", "private_metadata": "draft-1", "state": {"values": {}}}}

    def _submit_import(**kwargs: Any) -> dict[str, Any]:
        assert ack.called
        return {"type": "modal", "callback_id": "asset_page"}

    workflow.submit_import_url.side_effect = _submit_import
    registered["view:import_assets"](ack, view_body, {"private_metadata": "draft-1", "state": {"values": {}}}, client, logger)
    assert ack.call_args.kwargs["response_action"] == "update"
    client.views_update.assert_called()

    ack.reset_mock()
    client.reset_mock()
    workflow.open_asset_page.side_effect = ValidationError("page_index 1 is out of range")

    def _open_confirmation(draft_id: str) -> dict[str, Any]:
        del draft_id
        assert ack.called
        return {"type": "modal", "callback_id": "confirm_batch"}

    workflow.open_confirmation.side_effect = _open_confirmation
    registered["view:asset_page"](ack, view_body, {"private_metadata": "draft-1", "state": {"values": {}}}, client, logger)
    assert ack.call_args.kwargs["response_action"] == "update"
    client.views_update.assert_called()

    ack.reset_mock()
    client.reset_mock()

    def _confirm_batch(draft: Any) -> Any:
        del draft
        assert ack.called
        return MagicMock(accepted=True, private_text="Batch accepted. Creating threads…")

    workflow.confirm_batch.side_effect = _confirm_batch
    registered["view:confirm_batch"](ack, view_body, {"private_metadata": "draft-1", "state": {"values": {}}}, client, logger)
    ack.assert_called_once_with()
    client.chat_postEphemeral.assert_called()


def test_asset_edit_submit_acks_before_apply() -> None:
    """Saving Edit POCs must ack before Slack membership and chat.update work."""
    app = MagicMock()
    registered: dict[str, Any] = {}

    def _wrap(kind: str):
        def deco_factory(name: str):
            def deco(fn: Any) -> Any:
                registered[f"{kind}:{name}"] = fn
                return fn

            return deco

        return deco_factory

    app.command.side_effect = _wrap("command")
    app.action.side_effect = _wrap("action")
    app.view.side_effect = _wrap("view")

    workflow = MagicMock()
    edit = MagicMock()
    ack = MagicMock()
    client = MagicMock()
    logger = MagicMock()

    def _apply(request: Any) -> None:
        del request
        assert ack.called

    edit.apply_asset_edit.side_effect = _apply
    register_listeners(app, lambda: workflow, lambda: edit)
    view = {"private_metadata": "C1|1.1", "state": {"values": {}}}
    registered["view:asset_edit_submit"](ack, {"team": {"id": "T1"}, "user": {"id": "U1"}, "channel": {"id": "C1"}}, view, client, logger)
    ack.assert_called_once_with()
    edit.apply_asset_edit.assert_called_once()
