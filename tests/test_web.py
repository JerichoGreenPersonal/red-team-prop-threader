"""tests for flask health, readiness, and app factory wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from red_team_prop_threader.web import main, create_app, start_socket_mode
from red_team_prop_threader.config import Settings
from red_team_prop_threader.tables import Base


if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Engine
    from flask.testing import FlaskClient


@pytest.fixture
def settings() -> Settings:
    """non-secret settings suitable for local web tests."""
    return Settings(
        slack_bot_token="xoxb-test-token",
        slack_signing_secret="signing-secret",
        slack_app_token="xapp-test-token",
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


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    """in-memory sqlite engine with schema created."""
    e = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def client(settings: Settings, engine: Engine) -> FlaskClient:
    """Flask test client against a healthy database."""
    app = create_app(settings, engine=engine)
    return app.test_client()


@pytest.fixture
def broken_database() -> Engine:
    """Engine whose connect() always fails."""
    engine = MagicMock()
    engine.connect.side_effect = OperationalError("SELECT 1", None, Exception("db down"))
    return engine


def test_health_is_live_but_readiness_checks_database(settings: Settings, broken_database: Engine) -> None:
    """Healthz stays up when the database is unavailable; readyz returns 503."""
    app = create_app(settings, engine=broken_database)
    client = app.test_client()
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503


def test_readyz_ok_when_database_available(client: FlaskClient) -> None:
    """Readyz returns 200 when configuration and database checks succeed."""
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"


def test_create_app_exposes_bolt_app(settings: Settings, engine: Engine) -> None:
    """create_app stores the Bolt app for Socket Mode startup."""
    app = create_app(settings, engine=engine)
    assert "PROP_THREADER_BOLT_APP" in app.config


def test_start_socket_mode_connects_handler() -> None:
    """start_socket_mode constructs SocketModeHandler and connects it."""
    bolt_app = MagicMock()
    handler = MagicMock()
    handler_factory = MagicMock(return_value=handler)

    result = start_socket_mode(bolt_app, "xapp-test", handler_factory=handler_factory)

    handler_factory.assert_called_once_with(bolt_app, "xapp-test")
    handler.connect.assert_called_once_with()
    assert result is handler


def test_socket_mode_handler_acks_non_200(settings: Settings, engine: Engine) -> None:
    """Non-200 Bolt results still send a Socket Mode acknowledgement."""
    from red_team_prop_threader.web import PropThreaderSocketModeHandler

    app = create_app(settings, engine=engine)
    bolt_app = app.config["PROP_THREADER_BOLT_APP"]
    handler = PropThreaderSocketModeHandler(bolt_app, "xapp-test")
    client = MagicMock()
    req = MagicMock()
    req.type = "slash_commands"
    req.envelope_id = "E1"
    req.payload = {"command": "/create-prop-threads"}

    with patch("red_team_prop_threader.web.run_bolt_app", return_value=MagicMock(status=500, body="nope")):
        handler.handle(client, req)

    client.send_socket_mode_response.assert_called_once()
    assert client.send_socket_mode_response.call_args.args[0].envelope_id == "E1"


def test_main_starts_socket_mode_then_serves(settings: Settings) -> None:
    """Main serves Waitress in a thread then blocks on Socket Mode start."""
    with (
        patch("red_team_prop_threader.web.Settings.from_env", return_value=settings),
        patch("red_team_prop_threader.web.create_app") as create_app_mock,
        patch("red_team_prop_threader.web.PropThreaderSocketModeHandler") as handler_cls,
        patch("red_team_prop_threader.web.threading.Thread") as thread_cls,
    ):
        app = MagicMock()
        app.config = {"PROP_THREADER_BOLT_APP": MagicMock()}
        create_app_mock.return_value = app
        handler = MagicMock()
        handler_cls.return_value = handler
        main()

    thread_cls.assert_called_once()
    assert thread_cls.call_args.kwargs["daemon"] is True
    thread_cls.return_value.start.assert_called_once_with()
    handler_cls.assert_called_once_with(app.config["PROP_THREADER_BOLT_APP"], settings.slack_app_token)
    handler.start.assert_called_once_with()
