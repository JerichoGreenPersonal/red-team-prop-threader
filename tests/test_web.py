"""tests for flask health, readiness, and app factory wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from red_team_prop_threader.web import create_app
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
