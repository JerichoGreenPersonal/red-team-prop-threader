"""tests for the leased batch worker entry point."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from red_team_prop_threader.jobs import ExecutionResult
from red_team_prop_threader.config import Settings
from red_team_prop_threader.worker import UtcClock, main, run_forever
from red_team_prop_threader.repositories import BatchStatus


def _settings() -> Settings:
    return Settings(
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
        worker_poll_seconds=0,
        tunnel_command=None,
        tunnel_health_url=None,
    )


def test_utc_clock_returns_aware_datetime() -> None:
    """UtcClock returns timezone-aware UTC values."""
    now = UtcClock().now()
    assert now.tzinfo is not None


def test_run_forever_once_with_work() -> None:
    """once=True executes one claim cycle and returns after work."""
    settings = _settings()
    executor = MagicMock()
    executor.run_once.return_value = ExecutionResult(batch_id="b1", status=BatchStatus.SUCCEEDED, failed_operation=None)

    with (
        patch("red_team_prop_threader.worker.build_engine") as build_engine,
        patch("red_team_prop_threader.worker.session_scope") as session_scope,
        patch("red_team_prop_threader.worker.SlackGateway.from_settings"),
        patch("red_team_prop_threader.worker.BatchExecutor", return_value=executor),
        patch("red_team_prop_threader.worker.Repositories.from_session"),
        patch("red_team_prop_threader.worker.ChannelLeaseRepository"),
    ):
        session_scope.return_value.__enter__.return_value = MagicMock()
        session_scope.return_value.__exit__.return_value = None
        build_engine.return_value = MagicMock()
        run_forever(settings=settings, once=True)

    executor.run_once.assert_called_once()


def test_run_forever_once_without_work_does_not_sleep_when_once() -> None:
    """once=True returns immediately even when no batch was claimed."""
    settings = _settings()
    executor = MagicMock()
    executor.run_once.return_value = None

    with (
        patch("red_team_prop_threader.worker.build_engine", return_value=MagicMock()),
        patch("red_team_prop_threader.worker.session_scope") as session_scope,
        patch("red_team_prop_threader.worker.SlackGateway.from_settings"),
        patch("red_team_prop_threader.worker.BatchExecutor", return_value=executor),
        patch("red_team_prop_threader.worker.Repositories.from_session"),
        patch("red_team_prop_threader.worker.ChannelLeaseRepository"),
        patch("red_team_prop_threader.worker.time.sleep") as sleep,
    ):
        session_scope.return_value.__enter__.return_value = MagicMock()
        session_scope.return_value.__exit__.return_value = None
        run_forever(settings=settings, once=True)

    sleep.assert_not_called()


def test_main_invokes_run_forever() -> None:
    """Main delegates to run_forever."""
    with patch("red_team_prop_threader.worker.run_forever") as run:
        main()
    run.assert_called_once_with()
