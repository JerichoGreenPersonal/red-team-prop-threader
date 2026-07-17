"""tests for persistence repositories: drafts, batches, operations, and message history."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import text, event, inspect, create_engine
from sqlalchemy.orm import Session

from red_team_prop_threader.tables import Base
from red_team_prop_threader.repositories import BatchStatus, DraftRecord, MessageKind, Repositories, BatchRepository, NewMessageInput, OperationStatus


if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Engine

    from red_team_prop_threader.repositories import BatchRecord, GroupRecord


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class FakeClock:
    """deterministic clock for tests."""

    def __init__(self, start: datetime | None = None) -> None:
        """Initialize the clock at start, defaulting to 2025-01-01T12:00:00Z."""
        self._now: datetime = start or datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        """Return current fake time."""
        return self._now

    def advance(self, *, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> None:
        """Advance the clock by the specified duration."""
        self._now += timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


def sample_draft(*, created_at: datetime, workspace_id: str = "W1", channel_id: str = "C1", user_id: str = "U1") -> DraftRecord:
    """Construct a draft record with default 24-hour expiry."""
    return DraftRecord(
        workspace_id=workspace_id,
        channel_id=channel_id,
        user_id=user_id,
        snapshot={"items": []},
        imported_at=created_at,
        created_at=created_at,
        updated_at=created_at,
        expires_at=created_at + timedelta(hours=24),
    )


def _make_group(session: Session, clock: FakeClock, *, workspace_id: str = "W1", channel_id: str = "C1") -> GroupRecord:
    """Insert a group, flush it, and return its record."""
    from red_team_prop_threader.repositories import GroupRepository

    repo = GroupRepository(session)
    record = repo.create(workspace_id=workspace_id, channel_id=channel_id, display_title="Test Group", normalized_title="test group", now=clock.now())
    session.flush()
    return record


def _make_batch(session: Session, clock: FakeClock, group_id: str) -> BatchRecord:
    """Insert a batch, flush it, and return its record."""
    record = BatchRepository(session).create(
        group_id=group_id, workspace_id="W1", channel_id="C1", submitter_user_id="U1", payload={"assets": []}, now=clock.now()
    )
    session.flush()
    return record


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    """in-memory sqlite engine with foreign keys and WAL mode."""
    e = create_engine("sqlite:///:memory:")

    @event.listens_for(e, "connect")
    def _set_pragmas(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    """Bare session; caller controls commit/rollback."""
    s = Session(engine)
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def repositories(session: Session) -> Repositories:
    """Repositories bundle bound to the test session."""
    return Repositories.from_session(session)


@pytest.fixture
def clock() -> FakeClock:
    """Deterministic fake clock starting at a fixed UTC time."""
    return FakeClock()


# ---------------------------------------------------------------------------
# migration tests
# ---------------------------------------------------------------------------


def test_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    """Alembic upgrade head creates all tables; downgrade base drops them."""
    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "mig_test.db"
    db_url = f"sqlite:///{db_path}"

    root = Path(__file__).parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")

    eng = create_engine(db_url)
    insp = inspect(eng)
    tables_after_upgrade = set(insp.get_table_names())
    eng.dispose()

    for expected in ("drafts", "groups", "batches", "batch_assets", "messages", "operations", "channel_leases"):
        assert expected in tables_after_upgrade, f"table {expected!r} missing after upgrade"

    command.downgrade(cfg, "base")

    eng = create_engine(db_url)
    insp = inspect(eng)
    app_tables = [t for t in insp.get_table_names() if t != "alembic_version"]
    eng.dispose()
    assert app_tables == [], f"expected no app tables after downgrade, got {app_tables}"


# ---------------------------------------------------------------------------
# sqlite pragmas
# ---------------------------------------------------------------------------


def test_sqlite_foreign_keys_enabled(engine: Engine) -> None:
    """foreign_keys pragma is on for all sqlite connections."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert result == 1


def test_sqlite_wal_mode(tmp_path: Path) -> None:
    """journal_mode=WAL is applied when build_engine uses a file-based sqlite url.

    in-memory sqlite does not support WAL (it returns 'memory'); this test uses
    a temporary file database to verify the PRAGMA is applied correctly.
    """
    from red_team_prop_threader.db import build_engine

    db_url = f"sqlite:///{tmp_path / 'wal_test.db'}"
    e = build_engine(db_url)
    try:
        with e.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert result == "wal"
    finally:
        e.dispose()


def test_sqlite_busy_timeout(engine: Engine) -> None:
    """busy_timeout is set to a positive value."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA busy_timeout")).scalar()
    assert result > 0


# ---------------------------------------------------------------------------
# utc awareness
# ---------------------------------------------------------------------------


def test_utc_awareness_reject_naive_datetime(repositories: Repositories, clock: FakeClock) -> None:
    """Repository methods reject naive (non-timezone-aware) datetimes."""
    naive = datetime(2025, 1, 1, 12, 0, 0)  # no tzinfo
    with pytest.raises((ValueError, TypeError)):
        repositories.drafts.save(
            DraftRecord(
                workspace_id="W1",
                channel_id="C1",
                user_id="U1",
                snapshot={},
                imported_at=naive,
                created_at=naive,
                updated_at=naive,
                expires_at=naive + timedelta(hours=24),
            )
        )


def test_utc_awareness_reads_are_utc_aware(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """All datetime values read from the db are UTC-aware."""
    repositories.drafts.save(sample_draft(created_at=clock.now()))
    session.flush()

    record = repositories.drafts.get_for_user_channel("U1", "C1", clock.now())
    assert record is not None
    assert record.created_at.tzinfo is not None
    assert record.expires_at.tzinfo is not None
    assert record.imported_at.tzinfo is not None


# ---------------------------------------------------------------------------
# draft repository
# ---------------------------------------------------------------------------


def test_draft_save_and_get(repositories: Repositories, clock: FakeClock) -> None:
    """Saving a draft and retrieving it returns the same snapshot."""
    d = sample_draft(created_at=clock.now())
    repositories.drafts.save(d)

    result = repositories.drafts.get_for_user_channel("U1", "C1", clock.now())
    assert result is not None
    assert result.snapshot == d.snapshot
    assert result.workspace_id == "W1"


def test_draft_expires_after_twenty_four_hours(repositories: Repositories, clock: FakeClock) -> None:
    """Draft is not retrievable once now strictly exceeds its expiry time."""
    repositories.drafts.save(sample_draft(created_at=clock.now()))
    clock.advance(hours=24, seconds=1)
    assert repositories.drafts.get_for_user_channel("U1", "C1", clock.now()) is None


def test_draft_not_expired_at_exact_boundary(repositories: Repositories, clock: FakeClock) -> None:
    """Draft is still retrievable at the exact expiry instant."""
    repositories.drafts.save(sample_draft(created_at=clock.now()))
    clock.advance(hours=24)  # exactly at expiry
    result = repositories.drafts.get_for_user_channel("U1", "C1", clock.now())
    assert result is not None


def test_draft_upsert_replaces_prior(repositories: Repositories, clock: FakeClock) -> None:
    """Saving a new draft for the same user/channel replaces the prior one."""
    repositories.drafts.save(sample_draft(created_at=clock.now()))
    clock.advance(hours=1)
    updated = DraftRecord(
        workspace_id="W1",
        channel_id="C1",
        user_id="U1",
        snapshot={"items": [{"id": 1}]},
        imported_at=clock.now(),
        created_at=clock.now(),
        updated_at=clock.now(),
        expires_at=clock.now() + timedelta(hours=24),
    )
    repositories.drafts.save(updated)

    result = repositories.drafts.get_for_user_channel("U1", "C1", clock.now())
    assert result is not None
    assert result.snapshot == {"items": [{"id": 1}]}


def test_draft_isolation_across_users(repositories: Repositories, clock: FakeClock) -> None:
    """Drafts for different users in the same channel are independent."""
    repositories.drafts.save(sample_draft(created_at=clock.now(), user_id="U1"))
    repositories.drafts.save(sample_draft(created_at=clock.now(), user_id="U2"))

    r1 = repositories.drafts.get_for_user_channel("U1", "C1", clock.now())
    r2 = repositories.drafts.get_for_user_channel("U2", "C1", clock.now())
    assert r1 is not None
    assert r2 is not None


def test_draft_delete_expired(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """delete_expired removes only drafts whose expiry is strictly past."""
    repositories.drafts.save(sample_draft(created_at=clock.now()))
    session.flush()

    # not yet expired
    count = repositories.drafts.delete_expired(clock.now())
    assert count == 0

    # expire it
    clock.advance(hours=24, seconds=1)
    count = repositories.drafts.delete_expired(clock.now())
    assert count == 1

    # confirm it's gone
    assert repositories.drafts.get_for_user_channel("U1", "C1", clock.now()) is None


def test_draft_delete_expired_does_not_remove_active(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """delete_expired does not delete drafts that have not yet expired."""
    repositories.drafts.save(sample_draft(created_at=clock.now()))
    session.flush()
    clock.advance(hours=12)
    count = repositories.drafts.delete_expired(clock.now())
    assert count == 0


# ---------------------------------------------------------------------------
# batch repository
# ---------------------------------------------------------------------------


def test_batch_create_and_get(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Creating and retrieving a batch round-trips its fields."""
    group = _make_group(session, clock)
    batch = repositories.batches.create(
        group_id=group.id, workspace_id="W1", channel_id="C1", submitter_user_id="U1", payload={"key": "value"}, now=clock.now()
    )
    result = repositories.batches.get(batch.id)
    assert result is not None
    assert result.id == batch.id
    assert result.status == BatchStatus.PENDING
    assert result.payload == {"key": "value"}


def test_batch_status_transition(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Batch status transitions PENDING -> RUNNING -> SUCCEEDED."""
    group = _make_group(session, clock)
    batch = repositories.batches.create(group_id=group.id, workspace_id="W1", channel_id="C1", submitter_user_id="U1", payload=None, now=clock.now())
    assert repositories.batches.transition(batch.id, BatchStatus.PENDING, BatchStatus.RUNNING, now=clock.now())
    assert repositories.batches.transition(batch.id, BatchStatus.RUNNING, BatchStatus.SUCCEEDED, now=clock.now())

    result = repositories.batches.get(batch.id)
    assert result is not None
    assert result.status == BatchStatus.SUCCEEDED
    assert result.completed_at is not None


def test_batch_illegal_transition_raises(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Transitioning to an illegal status raises ValueError."""
    group = _make_group(session, clock)
    batch = repositories.batches.create(group_id=group.id, workspace_id="W1", channel_id="C1", submitter_user_id="U1", payload=None, now=clock.now())
    with pytest.raises(ValueError):
        repositories.batches.transition(batch.id, BatchStatus.PENDING, BatchStatus.SUCCEEDED, now=clock.now())


def test_batch_stale_cas_returns_false(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Transition returns False when expected_status does not match current status."""
    group = _make_group(session, clock)
    batch = repositories.batches.create(group_id=group.id, workspace_id="W1", channel_id="C1", submitter_user_id="U1", payload=None, now=clock.now())
    result = repositories.batches.transition(batch.id, BatchStatus.RUNNING, BatchStatus.SUCCEEDED, now=clock.now())
    assert result is False


def test_batch_update_payload(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """update_payload replaces the batch's payload json."""
    group = _make_group(session, clock)
    batch = repositories.batches.create(group_id=group.id, workspace_id="W1", channel_id="C1", submitter_user_id="U1", payload={"a": 1}, now=clock.now())
    repositories.batches.update_payload(batch.id, {"b": 2})
    result = repositories.batches.get(batch.id)
    assert result is not None
    assert result.payload == {"b": 2}


def test_batch_clear_payload(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """clear_payload sets payload to None without deleting the batch."""
    group = _make_group(session, clock)
    batch = repositories.batches.create(group_id=group.id, workspace_id="W1", channel_id="C1", submitter_user_id="U1", payload={"x": 1}, now=clock.now())
    repositories.batches.clear_payload(batch.id)
    result = repositories.batches.get(batch.id)
    assert result is not None
    assert result.payload is None
    assert result.id == batch.id


def test_batch_purge_expired_payloads(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """purge_expired_payloads clears only batches whose retention deadline is past."""
    group = _make_group(session, clock)
    deadline = clock.now() + timedelta(days=30)

    batch = repositories.batches.create(group_id=group.id, workspace_id="W1", channel_id="C1", submitter_user_id="U1", payload={"a": 1}, now=clock.now())
    repositories.batches.set_payload_expires_at(batch.id, deadline)
    session.flush()

    # cutoff before deadline: nothing cleared
    count = repositories.batches.purge_expired_payloads(clock.now())
    assert count == 0

    # cutoff after deadline: payload cleared
    clock.advance(days=31)
    count = repositories.batches.purge_expired_payloads(clock.now())
    assert count == 1

    result = repositories.batches.get(batch.id)
    assert result is not None
    assert result.payload is None


# ---------------------------------------------------------------------------
# operation repository
# ---------------------------------------------------------------------------


def test_operation_add_planned_idempotent(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Adding the same planned operation twice returns the existing record."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)

    op1 = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=42, idempotency_key="key-1", now=clock.now())
    op2 = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=42, idempotency_key="key-1", now=clock.now())
    assert op1.id == op2.id


def test_operation_add_planned_different_assets(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Different asset_entity_ids create separate operation records."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)

    op1 = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="k1", now=clock.now())
    op2 = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=2, idempotency_key="k2", now=clock.now())
    assert op1.id != op2.id


def test_operation_transition_pending_to_running(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """PENDING operation can transition to RUNNING."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)
    op = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="k", now=clock.now())
    ok = repositories.operations.transition(op.id, OperationStatus.PENDING, OperationStatus.RUNNING, now=clock.now())
    assert ok is True
    result = repositories.operations.get(op.id)
    assert result is not None
    assert result.status == OperationStatus.RUNNING


def test_operation_transition_running_to_succeeded(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """RUNNING operation can transition to SUCCEEDED with a result payload."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)
    op = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="k", now=clock.now())
    repositories.operations.transition(op.id, OperationStatus.PENDING, OperationStatus.RUNNING, now=clock.now())
    repositories.operations.transition(op.id, OperationStatus.RUNNING, OperationStatus.SUCCEEDED, result={"ts": "12345"}, now=clock.now())
    result = repositories.operations.get(op.id)
    assert result is not None
    assert result.status == OperationStatus.SUCCEEDED
    assert result.completed_at is not None
    assert result.result == {"ts": "12345"}


def test_operation_transition_running_to_failed(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """RUNNING operation can transition to FAILED with a safe error message."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)
    op = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="k", now=clock.now())
    repositories.operations.transition(op.id, OperationStatus.PENDING, OperationStatus.RUNNING, now=clock.now())
    repositories.operations.transition(op.id, OperationStatus.RUNNING, OperationStatus.FAILED, safe_error="Slack API timeout", attempts=1, now=clock.now())
    result = repositories.operations.get(op.id)
    assert result is not None
    assert result.status == OperationStatus.FAILED
    assert result.last_safe_error == "Slack API timeout"


def test_operation_illegal_transition_raises(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Transitioning PENDING directly to SUCCEEDED raises ValueError."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)
    op = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="k", now=clock.now())
    with pytest.raises(ValueError):
        repositories.operations.transition(op.id, OperationStatus.PENDING, OperationStatus.SUCCEEDED, now=clock.now())


def test_operation_stale_cas_returns_false(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Transition returns False when expected_status does not match current status."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)
    op = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="k", now=clock.now())
    # currently PENDING; supply wrong expected_status
    ok = repositories.operations.transition(op.id, OperationStatus.RUNNING, OperationStatus.SUCCEEDED, now=clock.now())
    assert ok is False


def test_operation_retry_selection(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """get_for_retry returns PENDING and FAILED operations."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)

    op_p = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="k1", now=clock.now())
    op_f = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=2, idempotency_key="k2", now=clock.now())
    op_s = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=3, idempotency_key="k3", now=clock.now())
    # mark op_f as failed
    repositories.operations.transition(op_f.id, OperationStatus.PENDING, OperationStatus.RUNNING, now=clock.now())
    repositories.operations.transition(op_f.id, OperationStatus.RUNNING, OperationStatus.FAILED, now=clock.now())
    # mark op_s as succeeded
    repositories.operations.transition(op_s.id, OperationStatus.PENDING, OperationStatus.RUNNING, now=clock.now())
    repositories.operations.transition(op_s.id, OperationStatus.RUNNING, OperationStatus.SUCCEEDED, now=clock.now())

    retry = repositories.operations.get_for_retry(batch.id)
    retry_ids = {r.id for r in retry}
    assert op_p.id in retry_ids
    assert op_f.id in retry_ids
    assert op_s.id not in retry_ids


def test_operation_succeeded_not_returned_for_retry(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Successful operations are never returned as retry candidates."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)
    op = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=1, idempotency_key="k", now=clock.now())
    repositories.operations.transition(op.id, OperationStatus.PENDING, OperationStatus.RUNNING, now=clock.now())
    repositories.operations.transition(op.id, OperationStatus.RUNNING, OperationStatus.SUCCEEDED, now=clock.now())

    retry = repositories.operations.get_for_retry(batch.id)
    assert all(r.id != op.id for r in retry)


def test_operations_for_batch_ordered(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """operations_for_batch returns operations in creation order."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)

    ids = []
    for i in range(3):
        op = repositories.operations.add_planned(
            batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=i + 1, idempotency_key=f"k{i}", now=clock.now()
        )
        ids.append(op.id)
        clock.advance(seconds=1)

    result = repositories.operations.get_for_batch(batch.id)
    assert [r.id for r in result] == ids


# ---------------------------------------------------------------------------
# history repository
# ---------------------------------------------------------------------------


def test_history_record_group_summary(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Recording a group summary message stores and retrieves it."""
    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)
    msg = repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group.id,
            batch_id=batch.id,
            kind=MessageKind.GROUP_SUMMARY,
            asset_entity_id=None,
            slack_ts="111.222",
            permalink="https://example.slack.com/archives/C1/p111222",
            canvas_metadata=None,
            now=clock.now(),
        )
    )
    assert msg.id is not None
    assert msg.is_latest is True


def test_history_latest_group_summary(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """latest_group_summary returns the most recently recorded summary."""
    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)

    repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group.id,
            batch_id=batch.id,
            kind=MessageKind.GROUP_SUMMARY,
            asset_entity_id=None,
            slack_ts="1.0",
            permalink="https://example.slack.com/1",
            canvas_metadata=None,
            now=clock.now(),
        )
    )
    result = repositories.history.latest_group_summary(group.id)
    assert result is not None
    assert result.slack_ts == "1.0"


def test_history_record_asset_root(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Recording an asset-root message stores and retrieves it."""
    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)
    msg = repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group.id,
            batch_id=batch.id,
            kind=MessageKind.ASSET_ROOT,
            asset_entity_id=99,
            slack_ts="999.1",
            permalink="https://example.slack.com/a/1",
            canvas_metadata=None,
            now=clock.now(),
        )
    )
    assert msg.asset_entity_id == 99


def test_history_latest_asset_root(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """latest_asset_root returns the current latest for a specific entity."""
    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)

    repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group.id,
            batch_id=batch.id,
            kind=MessageKind.ASSET_ROOT,
            asset_entity_id=55,
            slack_ts="55.1",
            permalink="https://example.slack.com/55",
            canvas_metadata=None,
            now=clock.now(),
        )
    )
    result = repositories.history.latest_asset_root("W1", "C1", 55)
    assert result is not None
    assert result.slack_ts == "55.1"


def test_history_retire_prior_latest(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Recording a new summary retires the prior latest marker."""
    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)

    first = repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group.id,
            batch_id=batch.id,
            kind=MessageKind.GROUP_SUMMARY,
            asset_entity_id=None,
            slack_ts="1.0",
            permalink="https://example.slack.com/1",
            canvas_metadata=None,
            now=clock.now(),
        )
    )
    assert first.is_latest is True

    second = repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group.id,
            batch_id=batch.id,
            kind=MessageKind.GROUP_SUMMARY,
            asset_entity_id=None,
            slack_ts="2.0",
            permalink="https://example.slack.com/2",
            canvas_metadata=None,
            now=clock.now(),
        )
    )
    assert second.is_latest is True

    # re-fetch first to verify it was retired
    session.expire_all()
    latest = repositories.history.latest_group_summary(group.id)
    assert latest is not None
    assert latest.slack_ts == "2.0"


def test_history_preserved_after_payload_clear(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Clearing batch payload does not delete associated message history."""
    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)

    repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group.id,
            batch_id=batch.id,
            kind=MessageKind.GROUP_SUMMARY,
            asset_entity_id=None,
            slack_ts="1.0",
            permalink="https://example.slack.com/1",
            canvas_metadata=None,
            now=clock.now(),
        )
    )

    repositories.batches.clear_payload(batch.id)

    result = repositories.history.latest_group_summary(group.id)
    assert result is not None
    assert result.slack_ts == "1.0"


# ---------------------------------------------------------------------------
# constraint tests
# ---------------------------------------------------------------------------


def test_unique_group_constraint(session: Session, clock: FakeClock) -> None:
    """Inserting two groups with the same workspace/channel/normalized_title raises an error."""
    from sqlalchemy.exc import IntegrityError

    from red_team_prop_threader.repositories import GroupRepository

    repo = GroupRepository(session)
    repo.create(workspace_id="W1", channel_id="C1", display_title="Foo", normalized_title="foo", now=clock.now())
    session.flush()

    with pytest.raises(IntegrityError):
        repo.create(workspace_id="W1", channel_id="C1", display_title="Foo", normalized_title="foo", now=clock.now())
        session.flush()


def test_unique_operation_constraint(repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Adding the same operation twice does not cause a duplicate; idempotency is honored."""
    from red_team_prop_threader.domain import OperationKind

    group = _make_group(session, clock)
    batch = _make_batch(session, clock, group.id)
    op1 = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=10, idempotency_key="ik", now=clock.now())
    op2 = repositories.operations.add_planned(batch_id=batch.id, kind=OperationKind.POST_ASSET, asset_entity_id=10, idempotency_key="ik", now=clock.now())
    assert op1.id == op2.id


def test_foreign_key_constraint_batch_requires_group(session: Session, clock: FakeClock) -> None:
    """Inserting a batch with a nonexistent group_id raises an IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    repo = BatchRepository(session)
    repo.create(
        group_id=str(uuid.uuid4()),  # nonexistent
        workspace_id="W1",
        channel_id="C1",
        submitter_user_id="U1",
        payload=None,
        now=clock.now(),
    )
    with pytest.raises(IntegrityError):
        session.flush()


# ---------------------------------------------------------------------------
# transaction behavior
# ---------------------------------------------------------------------------


def test_transaction_rollback_discards_changes(engine: Engine, clock: FakeClock) -> None:
    """Changes rolled back are not visible in a new session."""
    s1 = Session(engine)
    try:
        repos = Repositories.from_session(s1)
        repos.drafts.save(sample_draft(created_at=clock.now()))
        s1.flush()
        s1.rollback()
    finally:
        s1.close()

    s2 = Session(engine)
    try:
        repos2 = Repositories.from_session(s2)
        result = repos2.drafts.get_for_user_channel("U1", "C1", clock.now())
        assert result is None
    finally:
        s2.close()


def test_session_scope_commits_on_success(engine: Engine, clock: FakeClock) -> None:
    """session_scope commits changes when the block exits without error."""
    from red_team_prop_threader.db import session_scope

    with session_scope(engine) as s:
        Repositories.from_session(s).drafts.save(sample_draft(created_at=clock.now()))

    s2 = Session(engine)
    try:
        result = Repositories.from_session(s2).drafts.get_for_user_channel("U1", "C1", clock.now())
        assert result is not None
    finally:
        s2.close()


def test_session_scope_rolls_back_on_exception(engine: Engine, clock: FakeClock) -> None:
    """session_scope rolls back when the block raises an exception."""
    from red_team_prop_threader.db import session_scope

    with pytest.raises(RuntimeError), session_scope(engine) as s:
        Repositories.from_session(s).drafts.save(sample_draft(created_at=clock.now()))
        raise RuntimeError("simulated failure")

    s2 = Session(engine)
    try:
        result = Repositories.from_session(s2).drafts.get_for_user_channel("U1", "C1", clock.now())
        assert result is None
    finally:
        s2.close()
