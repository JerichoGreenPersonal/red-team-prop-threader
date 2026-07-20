"""tests for draft and payload retention cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import event, create_engine
from sqlalchemy.orm import Session

from red_team_prop_threader.tables import Base
from red_team_prop_threader.retention import run_retention
from red_team_prop_threader.repositories import BatchStatus, DraftRecord, MessageKind, Repositories, NewMessageInput


if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Engine


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    """in-memory sqlite engine."""
    e = create_engine("sqlite:///:memory:")

    @event.listens_for(e, "connect")
    def _pragmas(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    """Open session."""
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def repositories(session: Session) -> Repositories:
    """Repository bundle."""
    return Repositories.from_session(session)


@pytest.fixture
def clock_now() -> datetime:
    """Fixed utc instant."""
    return datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone.utc)


def _seed_old_completed_batch(repositories: Repositories, session: Session, completed_at: datetime) -> str:
    """Create a completed batch with payload and a latest message; return batch id."""
    group = repositories.groups.create(
        workspace_id="W1", channel_id="C1", display_title="SEASON 31 PROP REQUEST THREADS", normalized_title="season 31 prop request threads", now=completed_at
    )
    session.flush()
    batch = repositories.batches.create(
        group_id=group.id, workspace_id="W1", channel_id="C1", submitter_user_id="U1", payload={"assets": [{"entity_id": 1}]}, now=completed_at
    )
    session.flush()
    assert repositories.batches.transition(batch.id, BatchStatus.PENDING, BatchStatus.RUNNING, now=completed_at)
    assert repositories.batches.transition(batch.id, BatchStatus.RUNNING, BatchStatus.SUCCEEDED, now=completed_at)
    repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group.id,
            batch_id=batch.id,
            kind=MessageKind.GROUP_SUMMARY,
            asset_entity_id=None,
            slack_ts="1.1",
            permalink="https://slack.example/summary",
            canvas_metadata={"canvas_id": "F1"},
            now=completed_at,
        )
    )
    session.flush()
    return batch.id


def test_retention_removes_payloads_but_preserves_thread_history(repositories: Repositories, session: Session, clock_now: datetime) -> None:
    """Old completed payloads are cleared while message history remains."""
    old = clock_now - timedelta(days=31)
    batch_id = _seed_old_completed_batch(repositories, session, old)
    result = run_retention(repositories, now=clock_now)
    session.flush()
    assert result.payloads_cleared >= 1
    batch = repositories.batches.get(batch_id)
    assert batch is not None
    assert batch.payload is None
    assert repositories.history.latest_group_summary(batch.group_id) is not None


def test_retention_deletes_expired_drafts(repositories: Repositories, session: Session, clock_now: datetime) -> None:
    """Drafts past their expiry are removed."""
    created = clock_now - timedelta(hours=25)
    repositories.drafts.save(
        DraftRecord(
            workspace_id="W1",
            channel_id="C1",
            user_id="U1",
            snapshot={"x": 1},
            imported_at=created,
            created_at=created,
            updated_at=created,
            expires_at=created + timedelta(hours=24),
        )
    )
    session.flush()
    result = run_retention(repositories, now=clock_now)
    assert result.drafts_deleted == 1
    assert repositories.drafts.get_for_user_channel("U1", "C1", clock_now) is None


def test_retention_is_idempotent(repositories: Repositories, session: Session, clock_now: datetime) -> None:
    """A second retention pass clears nothing more."""
    _seed_old_completed_batch(repositories, session, clock_now - timedelta(days=40))
    first = run_retention(repositories, now=clock_now)
    second = run_retention(repositories, now=clock_now)
    assert first.payloads_cleared >= 1
    assert second.payloads_cleared == 0
