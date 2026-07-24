"""flask entry point for slack events, health, and readiness probes."""

from __future__ import annotations

import sys
from time import time
from typing import TYPE_CHECKING, Any
import logging
from datetime import datetime, timezone
import threading

from flask import Flask, jsonify, request
from sqlalchemy import text
from sqlalchemy.orm import Session
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_bolt.adapter.socket_mode.internals import run_bolt_app, send_response

from red_team_prop_threader.db import build_engine
from red_team_prop_threader.edits import EditService
from red_team_prop_threader.canvas import CanvasService
from red_team_prop_threader.config import Settings
from red_team_prop_threader.leases import ChannelLeaseRepository
from red_team_prop_threader.shotgrid import ShotGridGateway
from red_team_prop_threader.workflow import Workflow, DraftBook
from red_team_prop_threader.slack_app import create_bolt_app, register_listeners
from red_team_prop_threader.repositories import Repositories
from red_team_prop_threader.slack_gateway import SlackGateway


if TYPE_CHECKING:
    from slack_bolt import App as BoltApp
    from sqlalchemy import Engine
    from slack_sdk.socket_mode.builtin import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest


__all__ = ("PropThreaderSocketModeHandler", "UtcClock", "create_app", "main", "start_socket_mode")

_DRAFTS = DraftBook()
_LOG = logging.getLogger(__name__)


class UtcClock:
    """system utc clock for web-process workflow/edit services."""

    def now(self) -> datetime:
        """Return the current UTC-aware datetime.

        Returns:
            datetime: timezone-aware UTC instant.
        """
        return datetime.now(timezone.utc)


class PropThreaderSocketModeHandler(SocketModeHandler):
    """Socket Mode handler that logs envelopes and always acknowledges Slack."""

    def handle(self, client: SocketModeClient, req: SocketModeRequest) -> None:  # type: ignore[override]
        """Dispatch one Socket Mode envelope through Bolt and acknowledge it.

        Args:
            client: active Socket Mode client.
            req: inbound Socket Mode request envelope.
        """
        started = time()
        payload = req.payload if isinstance(req.payload, dict) else {}
        command = payload.get("command")
        interactive_type = payload.get("type") if req.type == "interactive" else None
        callback_id = None
        action_id = None
        if isinstance(payload.get("view"), dict):
            callback_id = payload["view"].get("callback_id")
        actions = payload.get("actions")
        if isinstance(actions, list) and actions and isinstance(actions[0], dict):
            action_id = actions[0].get("action_id")
        _LOG.info(
            "socket mode envelope type=%s command=%s interactive_type=%s callback_id=%s action_id=%s",
            req.type,
            command,
            interactive_type,
            callback_id,
            action_id,
        )
        try:
            bolt_resp = run_bolt_app(self.app, req)
        except Exception:
            _LOG.exception("socket mode bolt dispatch failed type=%s", req.type)
            client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            return

        if bolt_resp is None:
            _LOG.error("socket mode bolt returned no response type=%s", req.type)
            client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            return

        if bolt_resp.status != 200:
            _LOG.error("socket mode bolt status=%s body=%s", bolt_resp.status, bolt_resp.body)
            # still ack so slack does not show 'app did not respond'
            client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            return

        send_response(client, req, bolt_resp, started)
        spent_ms = int((time() - started) * 1000)
        body = bolt_resp.body or ""
        _LOG.info("socket mode envelope acked type=%s spent_ms=%s body_len=%s", req.type, spent_ms, len(body))
        if req.type == "interactive" and body and len(body) < 500:
            _LOG.info("socket mode interactive ack body=%s", body)


def create_app(settings: Settings | None = None, *, engine: Engine | None = None) -> Flask:
    """Create the Flask application wired to Bolt and health probes.

    Args:
        settings: optional settings override; loads from the environment when omitted.
        engine: optional sqlalchemy engine override for tests.

    Returns:
        Flask: configured application.
    """
    cfg = settings or Settings.from_env()
    db_engine = engine or build_engine(cfg.database_url)
    # Socket Mode: finish listeners (including views.open) before acknowledging.
    bolt_app = create_bolt_app(bot_token=cfg.slack_bot_token, signing_secret=cfg.slack_signing_secret, process_before_response=True)
    clock = UtcClock()
    slack = SlackGateway.from_settings(cfg)
    shotgrid = ShotGridGateway.from_settings(cfg)

    def workflow_factory() -> Workflow:
        session = Session(db_engine)
        return Workflow(
            slack=slack,
            shotgrid=shotgrid,
            canvas=CanvasService(slack),
            leases=ChannelLeaseRepository(session, db_engine),
            clock=clock,
            shotgrid_base_url=cfg.shotgrid_url,
            primary_asset_index_channel_id=cfg.primary_asset_index_channel_id,
            session=session,
            drafts=_DRAFTS,
        )

    def edit_factory() -> EditService:
        session = Session(db_engine)
        return EditService(
            repositories=Repositories.from_session(session),
            slack=slack,
            canvas_slack=slack,
            clock=clock,
            primary_asset_index_channel_id=cfg.primary_asset_index_channel_id,
        )

    register_listeners(bolt_app, workflow_factory, edit_factory)
    handler = SlackRequestHandler(bolt_app)

    app = Flask(__name__)
    app.config["PROP_THREADER_ENGINE"] = db_engine
    app.config["PROP_THREADER_SETTINGS"] = cfg
    app.config["PROP_THREADER_BOLT_APP"] = bolt_app

    @app.get("/healthz")
    def healthz() -> Any:
        """Liveness probe that does not touch dependencies."""
        return jsonify({"status": "ok"}), 200

    @app.get("/readyz")
    def readyz() -> Any:
        """Readiness probe for configuration and database connectivity."""
        try:
            _ = cfg.slack_bot_token
            with db_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            return jsonify({"status": "not_ready"}), 503
        return jsonify({"status": "ready"}), 200

    @app.post("/slack/events")
    def slack_events() -> Any:
        """Forward Slack HTTPS requests to the Bolt request handler.

        retained for dual-mode and local debugging; socket mode is the primary
        inbound path when the web process starts via :func:`main`.
        """
        return handler.handle(request)

    return app


def start_socket_mode(
    bolt_app: BoltApp, app_token: str, *, handler_factory: type[SocketModeHandler] | Any = PropThreaderSocketModeHandler
) -> SocketModeHandler:
    """Connect Bolt Socket Mode without blocking the caller.

    Args:
        bolt_app: configured Bolt application with listeners registered.
        app_token: Slack app-level token (``xapp-...``) with ``connections:write``.
        handler_factory: Socket Mode handler type or test double.

    Returns:
        SocketModeHandler: the connected handler instance.
    """
    handler = handler_factory(bolt_app, app_token)
    handler.connect()
    _LOG.info("slack socket mode listener connected")
    return handler


def _configure_logging() -> None:
    """Send process logs to stderr so run-local capture includes Socket Mode activity."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stderr)
    root.setLevel(logging.INFO)


def main() -> None:
    """Serve health probes in a background thread and block on Socket Mode."""
    _configure_logging()
    settings = Settings.from_env()
    app = create_app(settings)
    bolt_app = app.config["PROP_THREADER_BOLT_APP"]

    def serve_health() -> None:
        from waitress import serve

        serve(app, host=settings.web_host, port=settings.web_port)

    threading.Thread(target=serve_health, name="waitress-health", daemon=True).start()
    _LOG.info("health probes listening on http://%s:%s", settings.web_host, settings.web_port)

    handler = PropThreaderSocketModeHandler(bolt_app, settings.slack_app_token)
    _LOG.info("starting slack socket mode on main thread")
    handler.start()
