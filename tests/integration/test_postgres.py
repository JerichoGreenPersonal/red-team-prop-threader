"""postgresql integration tests.

these tests skip unless TEST_POSTGRES_URL is set to a non-empty value. the database
name must start with ``test_``/``ci_`` or end with ``_test``.
credentials are never printed or included in error messages.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import pytest


if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Engine


# ---------------------------------------------------------------------------
# helpers and guards
# ---------------------------------------------------------------------------

_POSTGRES_URL: str | None = os.environ.get("TEST_POSTGRES_URL") or None

_DISPOSABLE_DB_NAME = re.compile(r"(?:(?:test|ci)_[a-z0-9_]+|[a-z0-9_]+_test)\Z")


def _assert_disposable_db(url: str) -> None:
    """Raise if the database name does not look obviously disposable."""
    parsed = urlparse(url)
    db_name = (parsed.path or "").lstrip("/").lower()
    if _DISPOSABLE_DB_NAME.fullmatch(db_name) is None:
        raise RuntimeError(
            "TEST_POSTGRES_URL must target an obviously disposable database named test_<name>, ci_<name>, or <name>_test; refusing destructive migration"
        )


pytestmark = pytest.mark.postgres_integration


def _skip_if_no_url() -> None:
    if not _POSTGRES_URL:
        pytest.skip("TEST_POSTGRES_URL not set")


def _assert_final_migration_url(cfg: object, expected_url: str) -> None:
    """Validate the secret-safe resolved migration target immediately before a command."""
    from alembic.config import Config

    from red_team_prop_threader.db import resolve_migration_url

    assert isinstance(cfg, Config)
    resolved = resolve_migration_url(explicit_override=cfg.attributes.get("database_url_override"), configured_url=cfg.get_main_option("sqlalchemy.url"))
    if resolved != expected_url:
        raise RuntimeError("resolved migration target does not match the disposable test database")


def _assert_empty_target(engine: Engine) -> None:
    """Refuse migration when application or Alembic tables already exist."""
    from sqlalchemy import inspect

    protected = {"alembic_version", "drafts", "groups", "batches", "batch_assets", "messages", "operations", "channel_leases"}
    if protected.intersection(inspect(engine).get_table_names()):
        raise RuntimeError("disposable PostgreSQL target is not empty")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Generator[Engine, None, None]:
    """Postgresql engine with alembic migration applied; dropped after the module."""
    _skip_if_no_url()
    assert _POSTGRES_URL is not None
    _assert_disposable_db(_POSTGRES_URL)

    from pathlib import Path

    from alembic import command
    from sqlalchemy import create_engine
    from alembic.config import Config

    root = Path(__file__).parent.parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.attributes["database_url_override"] = _POSTGRES_URL

    preflight_engine = create_engine(_POSTGRES_URL)
    try:
        _assert_empty_target(preflight_engine)
    finally:
        preflight_engine.dispose()

    engine = None
    upgraded = False
    try:
        _assert_final_migration_url(cfg, _POSTGRES_URL)
        command.upgrade(cfg, "head")
        upgraded = True
        engine = create_engine(_POSTGRES_URL)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if upgraded:
            _assert_final_migration_url(cfg, _POSTGRES_URL)
            command.downgrade(cfg, "base")


@pytest.fixture
def pg_session(pg_engine: Engine) -> Generator[object, None, None]:
    """Fresh session for each postgres test; always rolled back."""
    from sqlalchemy.orm import Session

    s = Session(pg_engine)
    yield s
    s.rollback()
    s.close()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_explicit_test_url_outranks_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """A disposable explicit target wins over a populated production DATABASE_URL."""
    from red_team_prop_threader.db import resolve_migration_url

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/production")
    monkeypatch.setenv("TEST_POSTGRES_URL", "postgresql://example.invalid/disposable_test")
    explicit = os.environ["TEST_POSTGRES_URL"]
    assert resolve_migration_url(explicit_override=explicit, configured_url="sqlite:///default.db") == explicit


@pytest.mark.parametrize("database_name", ["test_props", "ci_props", "props_test"])
def test_disposable_database_guard_accepts_anchored_names(database_name: str) -> None:
    """The guard accepts only explicit anchored disposable naming conventions."""
    _assert_disposable_db(f"postgresql://example.invalid/{database_name}")


@pytest.mark.parametrize("database_name", ["contest", "latest", "production_test_backup", "dev_props", "props_ci"])
def test_disposable_database_guard_rejects_substring_accidents(database_name: str) -> None:
    """Incidental safety substrings do not authorize destructive migrations."""
    with pytest.raises(RuntimeError, match="disposable"):
        _assert_disposable_db(f"postgresql://example.invalid/{database_name}")


def test_preflight_rejects_existing_application_or_alembic_tables() -> None:
    """Migration setup refuses a target that is not empty."""
    from sqlalchemy import text, create_engine

    engine = create_engine("sqlite:///:memory:")
    _assert_empty_target(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
    with pytest.raises(RuntimeError, match="not empty"):
        _assert_empty_target(engine)
    engine.dispose()


def test_postgres_alembic_upgrade_creates_tables(pg_engine: Engine) -> None:
    """Alembic upgrade head creates the expected tables in postgresql."""
    from sqlalchemy import inspect

    insp = inspect(pg_engine)
    tables = set(insp.get_table_names())
    for expected in ("drafts", "groups", "batches", "batch_assets", "messages", "operations", "channel_leases"):
        assert expected in tables, f"table {expected!r} missing after pg upgrade"


def test_postgres_utc_timestamps(pg_session: object, pg_engine: Engine) -> None:
    """A non-UTC offset round-trips as the exact UTC instant."""
    from sqlalchemy.orm import Session

    from red_team_prop_threader.repositories import DraftRecord, Repositories

    session = pg_session  # type: ignore[assignment]
    assert isinstance(session, Session)
    repos = Repositories.from_session(session)
    now = datetime(2025, 6, 1, 5, 30, 0, tzinfo=timezone(timedelta(hours=-4)))
    expected_utc = datetime(2025, 6, 1, 9, 30, 0, tzinfo=timezone.utc)
    repos.drafts.save(
        DraftRecord(
            workspace_id="WPG1",
            channel_id="CPG1",
            user_id="UPG1",
            snapshot={"test": True},
            imported_at=now,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=24),
        )
    )
    session.flush()  # type: ignore[union-attr]
    result = repos.drafts.get_for_user_channel("UPG1", "CPG1", now, workspace_id="WPG1")
    assert result is not None
    assert result.created_at == expected_utc
    assert result.expires_at.tzinfo is not None


def test_postgres_operation_uniqueness(pg_session: object) -> None:
    """The unique operation constraint is enforced in postgresql."""
    from sqlalchemy.orm import Session

    from red_team_prop_threader.domain import OperationKind
    from red_team_prop_threader.repositories import Repositories, GroupRepository

    session = pg_session  # type: ignore[assignment]
    assert isinstance(session, Session)

    repos = Repositories.from_session(session)
    now = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

    group = GroupRepository(session).create(workspace_id="WPG2", channel_id="CPG2", display_title="PG Test Group", normalized_title="pg test group", now=now)
    batch = repos.batches.create(group_id=group.id, workspace_id="WPG2", channel_id="CPG2", submitter_user_id="UPG2", payload=None, now=now)
    repos.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="pg-k", now=now)
    session.flush()  # type: ignore[union-attr]

    # second add_planned should be idempotent
    op2 = repos.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="pg-k", now=now)
    assert op2 is not None  # no error; returned existing record


def test_postgres_lease_contention(pg_engine: Engine) -> None:
    """Concurrent acquire from two postgres sessions yields one owner."""
    import threading

    from sqlalchemy.orm import Session

    from red_team_prop_threader.leases import ChannelLeaseRepository

    results: list = []
    errors: list[Exception] = []
    now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    barrier = threading.Barrier(2)

    def _worker(user_id: str) -> None:
        s = Session(pg_engine)
        try:
            repo = ChannelLeaseRepository(s, pg_engine)
            barrier.wait()
            result = repo.acquire("CPG-CONTENTION", user_id, now, timedelta(minutes=10))
            s.commit()
            results.append(result)
        except Exception as exc:
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=_worker, args=(f"UPG{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"pg contention errors: {errors}"
    acquired_count = sum(1 for r in results if r.acquired)
    assert acquired_count == 1


def test_postgres_retention_preserves_history(pg_session: object) -> None:
    """Clearing batch payload does not remove message history in postgresql."""
    from sqlalchemy.orm import Session

    from red_team_prop_threader.repositories import MessageKind, Repositories, GroupRepository, NewMessageInput

    session = pg_session  # type: ignore[assignment]
    assert isinstance(session, Session)
    repos = Repositories.from_session(session)
    now = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

    group = GroupRepository(session).create(
        workspace_id="WPG3", channel_id="CPG3", display_title="PG History Group", normalized_title="pg history group", now=now
    )
    batch = repos.batches.create(group_id=group.id, workspace_id="WPG3", channel_id="CPG3", submitter_user_id="UPG3", payload={"data": "present"}, now=now)
    repos.history.record(
        NewMessageInput(
            workspace_id="WPG3",
            channel_id="CPG3",
            group_id=group.id,
            batch_id=batch.id,
            kind=MessageKind.GROUP_SUMMARY,
            asset_entity_id=None,
            slack_ts="pg.1",
            permalink="https://example.slack.com/pg/1",
            canvas_metadata=None,
            now=now,
        )
    )
    session.flush()  # type: ignore[union-attr]

    repos.batches.clear_payload(batch.id)

    result = repos.history.latest_group_summary(group.id)
    assert result is not None
    assert result.slack_ts == "pg.1"
