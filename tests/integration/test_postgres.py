"""postgresql integration tests.

these tests skip unless TEST_POSTGRES_URL is set to a non-empty value. the database
name must contain 'test' or 'dev' to prevent accidental destruction of production data.
credentials are never printed or included in error messages.
"""

from __future__ import annotations

import os
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

_SAFE_DB_NAME_SUBSTRINGS = ("test", "dev", "local", "ci", "sandbox")


def _assert_disposable_db(url: str) -> None:
    """Raise if the database name does not look obviously disposable."""
    parsed = urlparse(url)
    db_name = (parsed.path or "").lstrip("/").lower()
    if not any(sub in db_name for sub in _SAFE_DB_NAME_SUBSTRINGS):
        raise RuntimeError(
            "TEST_POSTGRES_URL points to a database whose name does not contain "
            f"any of {_SAFE_DB_NAME_SUBSTRINGS!r}. refusing to run destructive migration. "
            "rename the database or set TEST_POSTGRES_URL to a clearly disposable database."
        )


pytestmark = pytest.mark.postgres_integration


def _skip_if_no_url() -> None:
    if not _POSTGRES_URL:
        pytest.skip("TEST_POSTGRES_URL not set")


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
    cfg.set_main_option("sqlalchemy.url", _POSTGRES_URL)

    command.upgrade(cfg, "head")

    engine = create_engine(_POSTGRES_URL)
    yield engine
    engine.dispose()

    # downgrade to clean state
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


def test_postgres_alembic_upgrade_creates_tables(pg_engine: Engine) -> None:
    """Alembic upgrade head creates the expected tables in postgresql."""
    from sqlalchemy import inspect

    insp = inspect(pg_engine)
    tables = set(insp.get_table_names())
    for expected in ("drafts", "groups", "batches", "batch_assets", "messages", "operations", "channel_leases"):
        assert expected in tables, f"table {expected!r} missing after pg upgrade"


def test_postgres_utc_timestamps(pg_session: object, pg_engine: Engine) -> None:
    """Datetime values stored and read from postgresql are UTC-aware."""
    from sqlalchemy.orm import Session

    from red_team_prop_threader.repositories import DraftRecord, Repositories

    session = pg_session  # type: ignore[assignment]
    assert isinstance(session, Session)
    repos = Repositories.from_session(session)
    now = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
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
    assert result.created_at.tzinfo is not None
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
