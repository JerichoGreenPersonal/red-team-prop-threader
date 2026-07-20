"""tests for retention CLI entrypoint and web main wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from red_team_prop_threader.web import main as web_main, create_app
from red_team_prop_threader.retention import RetentionResult, main as retention_main


def test_retention_main_logs_result() -> None:
    """Retention main runs one pass and logs counts."""
    settings = MagicMock()
    settings.database_url = "sqlite:///:memory:"
    result = RetentionResult(drafts_deleted=1, payloads_cleared=2)
    with (
        patch("red_team_prop_threader.retention.Settings.from_env", return_value=settings),
        patch("red_team_prop_threader.retention.build_engine", return_value=MagicMock()),
        patch("red_team_prop_threader.retention.session_scope") as scope,
        patch("red_team_prop_threader.retention.Repositories.from_session"),
        patch("red_team_prop_threader.retention.run_retention", return_value=result) as run,
        patch("red_team_prop_threader.retention._LOG") as log,
    ):
        scope.return_value.__enter__.return_value = MagicMock()
        scope.return_value.__exit__.return_value = None
        retention_main()
    run.assert_called_once()
    assert run.call_args.kwargs["now"].tzinfo is not None
    log.info.assert_called_once()


def test_web_main_serves_waitress() -> None:
    """Web main builds the app and serves via Waitress."""
    settings = MagicMock()
    settings.web_host = "127.0.0.1"
    settings.web_port = 3000
    app = MagicMock()
    with (
        patch("red_team_prop_threader.web.Settings.from_env", return_value=settings),
        patch("red_team_prop_threader.web.create_app", return_value=app) as create,
        patch("waitress.serve") as serve,
    ):
        web_main()
    create.assert_called_once_with(settings)
    serve.assert_called_once_with(app, host="127.0.0.1", port=3000)


def test_create_app_slack_events_route_exists() -> None:
    """create_app registers the slack events route."""
    from sqlalchemy import create_engine

    from red_team_prop_threader.config import Settings
    from red_team_prop_threader.tables import Base

    settings = Settings(
        slack_bot_token="xoxb-test",
        slack_signing_secret="secret",
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
    )
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    app = create_app(settings, engine=engine)
    assert "slack_events" in app.view_functions
