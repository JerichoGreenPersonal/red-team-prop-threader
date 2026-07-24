"""unit tests for SlackGateway error translation and method wrappers."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from slack_sdk.errors import SlackApiError

from red_team_prop_threader.config import Settings
from red_team_prop_threader._errors import ConflictError, NotFoundError, ExternalServiceError, PermissionDeniedError, RetryableExternalServiceError
from red_team_prop_threader.slack_gateway import SlackGateway


class _Resp:
    """minimal slack response object."""

    def __init__(self, data: dict[str, Any], *, status_code: int = 200, headers: dict[str, Any] | None = None) -> None:
        self.data = data
        self.status_code = status_code
        self.headers = headers or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


def _api_error(code: str, *, status_code: int = 400, headers: dict[str, Any] | None = None, data: dict[str, Any] | None = None) -> SlackApiError:
    payload = {"ok": False, "error": code}
    if data:
        payload.update(data)
        payload.setdefault("ok", False)
        payload.setdefault("error", code)
    response = _Resp(payload, status_code=status_code, headers=headers)
    return SlackApiError(message=code, response=response)


@pytest.fixture
def client() -> MagicMock:
    """Mock WebClient."""
    return MagicMock()


@pytest.fixture
def gateway(client: MagicMock) -> SlackGateway:
    """Gateway under test."""
    return SlackGateway(client)


def test_from_settings_builds_client() -> None:
    """from_settings wires the bot token into a WebClient-backed gateway."""
    settings = Settings(
        slack_bot_token="xoxb-test",
        slack_signing_secret="secret",
        slack_app_token="xapp-test",
        shotgrid_script_name="script",
        shotgrid_script_key="key",
        shotgrid_url="https://respawn.shotgunstudio.com",
        slack_public_base_url="https://prop-threader-dev.example.invalid",
        shotgrid_test_page_id=23280,
        database_url="sqlite:///:memory:",
        test_postgres_url=None,
        canvas_timezone="America/Los_Angeles",
        web_host="127.0.0.1",
        web_port=3000,
        worker_poll_seconds=2,
        tunnel_command=None,
        tunnel_health_url=None,
        primary_asset_index_channel_id="C04H4QZEYUE",
    )
    gw = SlackGateway.from_settings(settings)
    assert isinstance(gw, SlackGateway)


def test_auth_and_conversation_helpers(gateway: SlackGateway, client: MagicMock) -> None:
    """Core read helpers return typed payloads."""
    client.auth_test.return_value = _Resp({"ok": True, "user_id": "Ubot"})
    client.conversations_info.return_value = _Resp({"ok": True, "channel": {"id": "C1"}})
    client.conversations_members.side_effect = [
        _Resp({"ok": True, "members": ["U1"], "response_metadata": {"next_cursor": "c2"}}),
        _Resp({"ok": True, "members": ["U2"], "response_metadata": {"next_cursor": ""}}),
    ]
    client.files_info.return_value = _Resp({"ok": True, "file": {"id": "F1", "title": "INDEX"}})
    client.users_info.return_value = _Resp({"ok": True, "user": {"id": "U1", "profile": {"display_name": "Ada"}}})

    assert gateway.auth_test()["user_id"] == "Ubot"
    assert gateway.get_conversation_info("C1")["id"] == "C1"
    assert gateway.get_conversation_members("C1") == ("U1", "U2")
    assert gateway.get_file_info("F1")["id"] == "F1"
    assert gateway.get_user_info("U1")["id"] == "U1"


def test_message_and_view_helpers(gateway: SlackGateway, client: MagicMock) -> None:
    """post/update/view helpers forward arguments."""
    client.views_open.return_value = _Resp({"ok": True})
    client.views_update.return_value = _Resp({"ok": True})
    client.conversations_open.return_value = _Resp({"ok": True, "channel": {"id": "D1"}})
    client.chat_postMessage.return_value = _Resp({"ok": True, "ts": "1.1", "channel": "C1"})
    client.chat_update.return_value = _Resp({"ok": True})
    client.chat_getPermalink.return_value = _Resp({"ok": True, "permalink": "https://slack.example/p"})

    assert gateway.open_view("trig", {"type": "modal"})["ok"] is True
    assert gateway.update_view("V1", {"type": "modal"}, view_hash="h")["ok"] is True
    assert gateway.open_dm("U1") == "D1"
    assert gateway.post_message("C1", text="hi", blocks=[{"type": "section"}], thread_ts="1.0")["ts"] == "1.1"
    assert gateway.update_message("C1", "1.1", text="bye", blocks=[])["ok"] is True
    assert gateway.get_permalink("C1", "1.1") == "https://slack.example/p"


def test_canvas_helpers(gateway: SlackGateway, client: MagicMock) -> None:
    """Canvas create/lookup/edit/rename helpers."""
    client.conversations_canvases_create.return_value = _Resp({"ok": True, "canvas_id": "Fcanvas"})
    client.canvases_sections_lookup.return_value = _Resp({"ok": True, "sections": [{"id": "S1"}, "bad"]})
    client.canvases_edit.return_value = _Resp({"ok": True})

    assert gateway.create_channel_canvas("C1", title="INDEX OF PROP REQUESTS") == "Fcanvas"
    sections = gateway.lookup_sections("Fcanvas", contains_text="Latest", section_types=("any_header",))
    assert sections == [{"id": "S1"}]
    client.canvases_sections_lookup.assert_called_with(canvas_id="Fcanvas", criteria={"section_types": ["any_header"], "contains_text": "Latest"})
    gateway.lookup_sections("Fcanvas", contains_text="Latest", section_types=())
    client.canvases_sections_lookup.assert_called_with(canvas_id="Fcanvas", criteria={"contains_text": "Latest"})
    gateway.edit_canvas("Fcanvas", operation="insert_at_start", markdown="# hi")
    gateway.edit_canvas("Fcanvas", operation="replace", markdown="x", section_id="S1")
    gateway.rename_canvas("Fcanvas", title="INDEX OF PROP REQUESTS")
    assert client.canvases_edit.call_count == 3


def test_invalid_arguments_includes_response_metadata(gateway: SlackGateway, client: MagicMock) -> None:
    """Slack invalid_arguments errors surface response_metadata.messages."""
    client.canvases_sections_lookup.side_effect = _api_error(
        "invalid_arguments", status_code=400, data={"response_metadata": {"messages": ["[ERROR] must be a valid enum value"]}}
    )
    with pytest.raises(ExternalServiceError, match="must be a valid enum value"):
        gateway.lookup_sections("Fcanvas", contains_text="Latest", section_types=())


@pytest.mark.parametrize(
    ("code", "status", "headers", "exc_type"),
    [
        ("ratelimited", 429, {"Retry-After": "1.5"}, RetryableExternalServiceError),
        ("missing_scope", 403, {}, PermissionDeniedError),
        ("channel_not_found", 404, {}, NotFoundError),
        ("conflict", 409, {}, ConflictError),
        ("unknown_error", 500, {"Retry-After": "nope"}, ExternalServiceError),
    ],
)
def test_error_translation(gateway: SlackGateway, client: MagicMock, code: str, status: int, headers: dict[str, str], exc_type: type[Exception]) -> None:
    """SlackApiError codes map to typed application errors."""
    client.auth_test.side_effect = _api_error(code, status_code=status, headers=headers)
    with pytest.raises(exc_type):
        gateway.auth_test()


def test_invalid_payloads_raise(gateway: SlackGateway, client: MagicMock) -> None:
    """Malformed success payloads raise ExternalServiceError."""
    client.conversations_info.return_value = _Resp({"ok": True, "channel": "bad"})
    with pytest.raises(ExternalServiceError):
        gateway.get_conversation_info("C1")

    client.conversations_canvases_create.return_value = _Resp({"ok": True, "canvas_id": ""})
    with pytest.raises(ExternalServiceError):
        gateway.create_channel_canvas("C1", title="x")

    client.chat_getPermalink.return_value = _Resp({"ok": True, "permalink": ""})
    with pytest.raises(ExternalServiceError):
        gateway.get_permalink("C1", "1.1")

    client.auth_test.return_value = "not-a-dict"
    with pytest.raises(ExternalServiceError):
        gateway.auth_test()

    client.auth_test.return_value = _Resp({"ok": False, "error": "x"})
    with pytest.raises(ExternalServiceError):
        gateway.auth_test()
