"""flask entry point for slack events, health, and readiness probes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from sqlalchemy import text
from sqlalchemy.orm import Session
from slack_bolt.adapter.flask import SlackRequestHandler

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
    from sqlalchemy import Engine


__all__ = ("UtcClock", "create_app", "main")

_DRAFTS = DraftBook()


class UtcClock:
    """system utc clock for web-process workflow/edit services."""

    def now(self) -> datetime:
        """Return the current UTC-aware datetime.

        Returns:
            datetime: timezone-aware UTC instant.
        """
        return datetime.now(timezone.utc)


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
    bolt_app = create_bolt_app(bot_token=cfg.slack_bot_token, signing_secret=cfg.slack_signing_secret, process_before_response=False)
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
            session=session,
            drafts=_DRAFTS,
        )

    def edit_factory() -> EditService:
        session = Session(db_engine)
        return EditService(repositories=Repositories.from_session(session), slack=slack, canvas_slack=slack, clock=clock)

    register_listeners(bolt_app, workflow_factory, edit_factory)
    handler = SlackRequestHandler(bolt_app)

    app = Flask(__name__)
    app.config["PROP_THREADER_ENGINE"] = db_engine
    app.config["PROP_THREADER_SETTINGS"] = cfg

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
        """Forward Slack HTTPS requests to the Bolt request handler."""
        return handler.handle(request)

    return app


def main() -> None:
    """Serve the Flask app with Waitress using configured host/port."""
    settings = Settings.from_env()
    app = create_app(settings)
    from waitress import serve

    serve(app, host=settings.web_host, port=settings.web_port)
