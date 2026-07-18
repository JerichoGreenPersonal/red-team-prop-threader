"""transaction-scoped repositories for drafts, batches, operations, and message history."""

from __future__ import annotations

from enum import StrEnum
import json
import uuid
from typing import TYPE_CHECKING, Any, cast
import hashlib
from dataclasses import dataclass

from sqlalchemy import func, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from red_team_prop_threader.domain import OperationKind
from red_team_prop_threader.tables import Batch, Draft, Group, Message, Operation


if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy import Table
    from sqlalchemy.orm import Session
    from sqlalchemy.engine import CursorResult


__all__ = (
    "BatchRecord",
    "BatchRepository",
    "BatchStatus",
    "DraftRecord",
    "DraftRepository",
    "GroupRecord",
    "GroupRepository",
    "HistoryRepository",
    "MessageKind",
    "MessageRecord",
    "NewMessageInput",
    "OperationRecord",
    "OperationRepository",
    "OperationStatus",
    "Repositories",
)


# ---------------------------------------------------------------------------
# status and kind enums
# ---------------------------------------------------------------------------


class BatchStatus(StrEnum):
    """lifecycle states for a submission batch."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationStatus(StrEnum):
    """lifecycle states for a durable workflow operation."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MessageKind(StrEnum):
    """categories of tracked slack messages."""

    GROUP_SUMMARY = "group_summary"
    ASSET_ROOT = "asset_root"


# ---------------------------------------------------------------------------
# allowed status transitions
# ---------------------------------------------------------------------------

_BATCH_TRANSITIONS: dict[BatchStatus, frozenset[BatchStatus]] = {
    BatchStatus.PENDING: frozenset({BatchStatus.RUNNING}),
    BatchStatus.RUNNING: frozenset({BatchStatus.SUCCEEDED, BatchStatus.FAILED, BatchStatus.CANCELLED}),
    BatchStatus.SUCCEEDED: frozenset(),
    BatchStatus.FAILED: frozenset({BatchStatus.RUNNING}),
    BatchStatus.CANCELLED: frozenset(),
}

_OPERATION_TRANSITIONS: dict[OperationStatus, frozenset[OperationStatus]] = {
    OperationStatus.PENDING: frozenset({OperationStatus.RUNNING}),
    OperationStatus.RUNNING: frozenset({OperationStatus.SUCCEEDED, OperationStatus.FAILED}),
    OperationStatus.SUCCEEDED: frozenset(),
    OperationStatus.FAILED: frozenset({OperationStatus.RUNNING}),
}


# ---------------------------------------------------------------------------
# immutable record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DraftRecord:
    """immutable snapshot of a user's in-progress prop request."""

    workspace_id: str
    channel_id: str
    user_id: str
    snapshot: dict[str, Any]
    imported_at: datetime
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class GroupRecord:
    """immutable record for a named prop-request group."""

    id: str
    workspace_id: str
    channel_id: str
    display_title: str
    normalized_title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BatchRecord:
    """immutable record for a submission batch."""

    id: str
    group_id: str
    workspace_id: str
    channel_id: str
    submitter_user_id: str
    status: BatchStatus
    payload: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    payload_expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class OperationRecord:
    """immutable record for a durable workflow operation."""

    id: str
    batch_id: str
    kind: OperationKind
    asset_entity_id: int
    status: OperationStatus
    idempotency_key: str
    attempts: int
    last_safe_error: str | None
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class MessageRecord:
    """immutable record for a tracked slack message."""

    id: str
    workspace_id: str
    channel_id: str
    group_id: str
    batch_id: str | None
    kind: MessageKind
    asset_entity_id: int | None
    slack_ts: str
    permalink: str
    is_latest: bool
    canvas_metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    last_editor_id: str | None
    last_edited_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewMessageInput:
    """input for recording a new tracked slack message."""

    workspace_id: str
    channel_id: str
    group_id: str
    batch_id: str | None
    kind: MessageKind
    asset_entity_id: int | None
    slack_ts: str
    permalink: str
    canvas_metadata: dict[str, Any] | None
    now: datetime


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _require_aware(dt: datetime, name: str) -> None:
    """Raise ValueError for naive datetimes.

    Args:
        dt: the datetime to validate.
        name: field name used in the error message.

    Raises:
        ValueError: if dt has no tzinfo or its utcoffset is None.
    """
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError(f"{name} must be a timezone-aware UTC datetime, got {dt!r}")


def _new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def _build_draft_upsert(dialect_name: str, values: dict[str, Any]) -> Any:
    """Build a native draft upsert for a supported production dialect."""
    table = cast("Table", Draft.__table__)
    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    elif dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        raise ValueError(f"native draft upsert is unsupported for dialect {dialect_name!r}")
    statement = dialect_insert(table).values(**values)
    return statement.on_conflict_do_update(
        index_elements=["workspace_id", "channel_id", "user_id"],
        set_={
            "snapshot_json": statement.excluded.snapshot_json,
            "imported_at": statement.excluded.imported_at,
            "updated_at": statement.excluded.updated_at,
            "expires_at": statement.excluded.expires_at,
        },
    )


def _build_operation_insert(dialect_name: str, values: dict[str, Any]) -> Any:
    """Build a native idempotent operation insert for a supported dialect."""
    table = cast("Table", Operation.__table__)
    if dialect_name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    elif dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        raise ValueError(f"native operation insert is unsupported for dialect {dialect_name!r}")
    return dialect_insert(table).values(**values).on_conflict_do_nothing(index_elements=["batch_id", "kind", "asset_entity_id"])


def _history_advisory_lock_statement(inp: NewMessageInput) -> Any:
    """Build a transaction-scoped PostgreSQL advisory lock for the true history scope."""
    if inp.kind == MessageKind.ASSET_ROOT:
        components = [inp.kind.value, inp.workspace_id, inp.channel_id, str(inp.asset_entity_id)]
    else:
        components = [inp.kind.value, inp.group_id]
    canonical_scope = json.dumps(components, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.blake2b(canonical_scope, digest_size=8, person=b"rtpt-hist").digest()
    key = int.from_bytes(digest, byteorder="big", signed=True)
    return select(func.pg_advisory_xact_lock(key))


def _draft_to_record(row: Draft) -> DraftRecord:
    """Convert a Draft ORM row to a DraftRecord."""
    return DraftRecord(
        workspace_id=row.workspace_id,
        channel_id=row.channel_id,
        user_id=row.user_id,
        snapshot=row.snapshot_json,
        imported_at=row.imported_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        expires_at=row.expires_at,
    )


def _group_to_record(row: Group) -> GroupRecord:
    """Convert a Group ORM row to a GroupRecord."""
    return GroupRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        channel_id=row.channel_id,
        display_title=row.display_title,
        normalized_title=row.normalized_title,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _batch_to_record(row: Batch) -> BatchRecord:
    """Convert a Batch ORM row to a BatchRecord."""
    return BatchRecord(
        id=row.id,
        group_id=row.group_id,
        workspace_id=row.workspace_id,
        channel_id=row.channel_id,
        submitter_user_id=row.submitter_user_id,
        status=BatchStatus(row.status),
        payload=row.payload_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
        payload_expires_at=row.payload_expires_at,
    )


def _operation_to_record(row: Operation) -> OperationRecord:
    """Convert an Operation ORM row to an OperationRecord."""
    return OperationRecord(
        id=row.id,
        batch_id=row.batch_id,
        kind=OperationKind(row.kind),
        asset_entity_id=row.asset_entity_id,
        status=OperationStatus(row.status),
        idempotency_key=row.idempotency_key,
        attempts=row.attempts,
        last_safe_error=row.last_safe_error,
        payload=row.payload_json,
        result=row.result_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


def _message_to_record(row: Message) -> MessageRecord:
    """Convert a Message ORM row to a MessageRecord."""
    return MessageRecord(
        id=row.id,
        workspace_id=row.workspace_id,
        channel_id=row.channel_id,
        group_id=row.group_id,
        batch_id=row.batch_id,
        kind=MessageKind(row.kind),
        asset_entity_id=row.asset_entity_id,
        slack_ts=row.slack_ts,
        permalink=row.permalink,
        is_latest=row.is_latest,
        canvas_metadata=row.canvas_metadata_json,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_editor_id=row.last_editor_id,
        last_edited_at=row.last_edited_at,
    )


# ---------------------------------------------------------------------------
# repositories
# ---------------------------------------------------------------------------


class DraftRepository:
    """transaction-scoped repository for user draft snapshots."""

    def __init__(self, session: Session) -> None:
        """Bind the repository to an open session."""
        self._session = session

    def save(self, record: DraftRecord) -> None:
        """Upsert a draft snapshot for the given workspace/channel/user.

        exactly one active draft is kept per workspace/channel/user combination.
        calling save again with the same identity replaces the prior snapshot.

        Args:
            record: the draft record to persist; all datetime fields must be UTC-aware.

        Raises:
            ValueError: if any datetime field is naive.
        """
        _require_aware(record.created_at, "created_at")
        _require_aware(record.updated_at, "updated_at")
        _require_aware(record.imported_at, "imported_at")
        _require_aware(record.expires_at, "expires_at")

        values = {
            "id": _new_id(),
            "workspace_id": record.workspace_id,
            "channel_id": record.channel_id,
            "user_id": record.user_id,
            "snapshot_json": record.snapshot,
            "imported_at": record.imported_at,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "expires_at": record.expires_at,
        }
        dialect = self._session.get_bind().dialect.name
        if dialect not in ("sqlite", "postgresql"):
            self._save_generic(values)
            return
        self._session.execute(_build_draft_upsert(dialect, values))

    def _save_generic(self, values: dict[str, Any]) -> None:
        """Use a savepoint-backed conflict fallback for other SQL dialects."""
        try:
            with self._session.begin_nested():
                self._session.execute(insert(Draft).values(**values))
            return
        except IntegrityError:
            pass
        self._session.execute(
            update(Draft)
            .where(Draft.workspace_id == values["workspace_id"], Draft.channel_id == values["channel_id"], Draft.user_id == values["user_id"])
            .values(snapshot_json=values["snapshot_json"], imported_at=values["imported_at"], updated_at=values["updated_at"], expires_at=values["expires_at"])
        )

    def get_for_user_channel(self, user_id: str, channel_id: str, now: datetime, *, workspace_id: str = "W1") -> DraftRecord | None:
        """Return a non-expired draft for the given user and channel, or None.

        a draft is considered expired when now > expires_at (strictly). at exact
        equality (now == expires_at) the draft is still retrievable.

        Args:
            user_id: the user's slack ID.
            channel_id: the channel's slack ID.
            now: current UTC-aware time used for expiry comparison.
            workspace_id: the workspace's slack ID; defaults to 'W1' for development.

        Returns:
            DraftRecord | None: the active draft, or None if absent or expired.

        Raises:
            ValueError: if now is naive.
        """
        _require_aware(now, "now")
        row = self._session.execute(
            select(Draft).where(Draft.workspace_id == workspace_id, Draft.channel_id == channel_id, Draft.user_id == user_id, Draft.expires_at >= now)
        ).scalar_one_or_none()

        return None if row is None else _draft_to_record(row)

    def delete_expired(self, now: datetime) -> int:
        """Delete all drafts whose expiry is strictly in the past.

        drafts with expires_at == now are not deleted (boundary is exclusive).

        Args:
            now: current UTC-aware time.

        Returns:
            int: the number of drafts deleted.

        Raises:
            ValueError: if now is naive.
        """
        _require_aware(now, "now")
        dml = cast("CursorResult[Any]", self._session.execute(delete(Draft).where(Draft.expires_at < now)))
        return dml.rowcount


class GroupRepository:
    """transaction-scoped repository for prop-request groups."""

    def __init__(self, session: Session) -> None:
        """Bind the repository to an open session."""
        self._session = session

    def create(self, *, workspace_id: str, channel_id: str, display_title: str, normalized_title: str, now: datetime) -> GroupRecord:
        """Create a new group record.

        Args:
            workspace_id: slack workspace ID.
            channel_id: slack channel ID.
            display_title: human-readable group title.
            normalized_title: normalized form used for deduplication.
            now: UTC-aware creation timestamp.

        Returns:
            GroupRecord: the created group record.

        Raises:
            ValueError: if now is naive.
        """
        _require_aware(now, "now")
        row = Group(
            id=_new_id(),
            workspace_id=workspace_id,
            channel_id=channel_id,
            display_title=display_title,
            normalized_title=normalized_title,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        return _group_to_record(row)

    def get(self, group_id: str) -> GroupRecord | None:
        """Return a group by ID, or None if not found.

        Args:
            group_id: the group's UUID string.

        Returns:
            GroupRecord | None: the group record, or None.
        """
        row = self._session.get(Group, group_id)
        return None if row is None else _group_to_record(row)


class BatchRepository:
    """transaction-scoped repository for submission batches."""

    def __init__(self, session: Session) -> None:
        """Bind the repository to an open session."""
        self._session = session

    def create(
        self, *, group_id: str, workspace_id: str, channel_id: str, submitter_user_id: str, payload: dict[str, Any] | None, now: datetime
    ) -> BatchRecord:
        """Create a new PENDING batch.

        Args:
            group_id: the parent group's UUID.
            workspace_id: slack workspace ID.
            channel_id: slack channel ID.
            submitter_user_id: the submitting user's slack ID.
            payload: optional detailed payload JSON.
            now: UTC-aware creation timestamp.

        Returns:
            BatchRecord: the created batch record.

        Raises:
            ValueError: if now is naive.
        """
        _require_aware(now, "now")
        row = Batch(
            id=_new_id(),
            group_id=group_id,
            workspace_id=workspace_id,
            channel_id=channel_id,
            submitter_user_id=submitter_user_id,
            status=BatchStatus.PENDING,
            payload_json=payload,
            created_at=now,
            updated_at=now,
            completed_at=None,
            payload_expires_at=None,
        )
        self._session.add(row)
        return _batch_to_record(row)

    def get(self, batch_id: str) -> BatchRecord | None:
        """Return a batch by ID, or None if not found.

        Args:
            batch_id: the batch's UUID string.

        Returns:
            BatchRecord | None: the batch record, or None.
        """
        row = self._session.get(Batch, batch_id)
        return None if row is None else _batch_to_record(row)

    def transition(self, batch_id: str, expected_status: BatchStatus, new_status: BatchStatus, *, now: datetime) -> bool:
        """Transition a batch status with compare-and-swap semantics.

        Args:
            batch_id: the batch's UUID string.
            expected_status: the status the caller believes the batch is in.
            new_status: the target status.
            now: UTC-aware timestamp for updated_at and completed_at.

        Returns:
            bool: True if the transition succeeded; False if expected_status did not match.

        Raises:
            ValueError: if the transition from expected_status to new_status is illegal,
                or if now is naive.
            LookupError: if batch_id does not exist.
        """
        _require_aware(now, "now")
        allowed = _BATCH_TRANSITIONS.get(expected_status, frozenset())
        if new_status not in allowed:
            raise ValueError(f"illegal batch transition {expected_status!r} -> {new_status!r}")

        values: dict[str, Any] = {"status": new_status, "updated_at": now}
        if new_status in (BatchStatus.SUCCEEDED, BatchStatus.FAILED, BatchStatus.CANCELLED):
            values["completed_at"] = now
        elif new_status is BatchStatus.RUNNING:
            values["completed_at"] = None
        result = cast(
            "CursorResult[Any]",
            self._session.execute(
                update(Batch).where(Batch.id == batch_id, Batch.status == expected_status).values(**values).execution_options(synchronize_session=False)
            ),
        )
        if result.rowcount:
            return True
        if self._session.execute(select(Batch.id).where(Batch.id == batch_id)).scalar_one_or_none() is None:
            raise LookupError(f"batch {batch_id!r} not found")
        return False

    def claim_next_pending(self, *, now: datetime) -> BatchRecord | None:
        """Claim the oldest PENDING batch by transitioning it to RUNNING.

        Args:
            now: UTC-aware claim timestamp.

        Returns:
            BatchRecord | None: the claimed batch, or None when no PENDING batch exists.

        Raises:
            ValueError: if now is naive.
        """
        _require_aware(now, "now")
        row = self._session.execute(select(Batch).where(Batch.status == BatchStatus.PENDING).order_by(Batch.created_at).limit(1)).scalar_one_or_none()
        if row is None:
            return None
        if not self.transition(row.id, BatchStatus.PENDING, BatchStatus.RUNNING, now=now):
            return None
        return self.get(row.id)

    def update_payload(self, batch_id: str, payload: dict[str, Any] | None) -> None:
        """Replace the batch's detailed payload independently of status.

        Args:
            batch_id: the batch's UUID string.
            payload: the new payload JSON, or None to clear.

        Raises:
            LookupError: if batch_id does not exist.
        """
        row = self._session.get(Batch, batch_id)
        if row is None:
            raise LookupError(f"batch {batch_id!r} not found")
        row.payload_json = payload

    def clear_payload(self, batch_id: str) -> None:
        """Set the batch's detailed payload to None for retention compliance.

        message history and identity fields are preserved. this does not delete the batch.

        Args:
            batch_id: the batch's UUID string.
        """
        self._session.execute(update(Batch).where(Batch.id == batch_id).values(payload_json=None))

    def set_payload_expires_at(self, batch_id: str, expires_at: datetime) -> None:
        """Set the retention deadline after which the payload may be cleared.

        Args:
            batch_id: the batch's UUID string.
            expires_at: UTC-aware retention deadline.

        Raises:
            ValueError: if expires_at is naive.
        """
        _require_aware(expires_at, "expires_at")
        row = self._session.get(Batch, batch_id)
        if row is None:
            raise LookupError(f"batch {batch_id!r} not found")
        row.payload_expires_at = expires_at

    def purge_expired_payloads(self, cutoff: datetime) -> int:
        """Clear detailed payloads for batches whose retention deadline is strictly past.

        message history is preserved. only payload_json is set to None.

        Args:
            cutoff: UTC-aware cutoff time; batches with payload_expires_at < cutoff are cleared.

        Returns:
            int: number of batches whose payload was cleared.

        Raises:
            ValueError: if cutoff is naive.
        """
        _require_aware(cutoff, "cutoff")
        dml = cast(
            "CursorResult[Any]",
            self._session.execute(
                update(Batch)
                .where(Batch.payload_json.isnot(None), Batch.payload_expires_at.isnot(None), Batch.payload_expires_at < cutoff)
                .values(payload_json=None)
            ),
        )
        return dml.rowcount


class OperationRepository:
    """transaction-scoped repository for durable workflow operations."""

    def __init__(self, session: Session) -> None:
        """Bind the repository to an open session."""
        self._session = session

    def add_planned(
        self, *, batch_id: str, kind: OperationKind, asset_entity_id: int, idempotency_key: str, payload: dict[str, Any] | None = None, now: datetime
    ) -> OperationRecord:
        """Add a PENDING operation idempotently.

        if an operation with the same (batch_id, kind, asset_entity_id) already
        exists, the existing record is returned unchanged.

        Args:
            batch_id: parent batch UUID.
            kind: the operation kind.
            asset_entity_id: ShotGrid entity ID, or 0 for batch-level operations.
            idempotency_key: stable caller-supplied key; ignored if the operation exists.
            payload: optional operation payload JSON.
            now: UTC-aware creation timestamp.

        Returns:
            OperationRecord: the existing or newly created operation record.

        Raises:
            ValueError: if now is naive.
        """
        _require_aware(now, "now")
        self._session.flush()

        values = {
            "id": _new_id(),
            "batch_id": batch_id,
            "kind": kind,
            "asset_entity_id": asset_entity_id,
            "status": OperationStatus.PENDING,
            "idempotency_key": idempotency_key,
            "attempts": 0,
            "last_safe_error": None,
            "payload_json": payload,
            "result_json": None,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        dialect = self._session.get_bind().dialect.name
        if dialect not in ("sqlite", "postgresql"):
            self._add_planned_generic(values)
            return self._get_by_unique_key(batch_id, kind, asset_entity_id)

        self._session.execute(_build_operation_insert(dialect, values))
        return self._get_by_unique_key(batch_id, kind, asset_entity_id)

    def _add_planned_generic(self, values: dict[str, Any]) -> None:
        """Use a savepoint-backed insert fallback for other SQL dialects."""
        try:
            with self._session.begin_nested():
                self._session.execute(insert(Operation).values(**values))
        except IntegrityError:
            pass

    def _get_by_unique_key(self, batch_id: str, kind: OperationKind, asset_entity_id: int) -> OperationRecord:
        """Fetch an operation by its enforced idempotency key."""
        row = self._session.execute(
            select(Operation).where(Operation.batch_id == batch_id, Operation.kind == kind, Operation.asset_entity_id == asset_entity_id)
        ).scalar_one()
        return _operation_to_record(row)

    def get(self, operation_id: str) -> OperationRecord | None:
        """Return an operation by ID, or None if not found.

        Args:
            operation_id: the operation's UUID string.

        Returns:
            OperationRecord | None: the operation record, or None.
        """
        row = self._session.get(Operation, operation_id)
        return None if row is None else _operation_to_record(row)

    def transition(
        self,
        operation_id: str,
        expected_status: OperationStatus,
        new_status: OperationStatus,
        *,
        attempts: int | None = None,
        safe_error: str | None = None,
        result: dict[str, Any] | None = None,
        now: datetime,
    ) -> bool:
        """Transition an operation status with compare-and-swap semantics.

        stale workers that supply the wrong expected_status receive False and
        must not overwrite terminal state.

        Args:
            operation_id: the operation's UUID string.
            expected_status: status the caller believes the operation is in.
            new_status: target status.
            attempts: if provided, overwrite the attempts counter.
            safe_error: user-safe error message for FAILED transitions.
            result: operation result payload for SUCCEEDED transitions.
            now: UTC-aware transition timestamp.

        Returns:
            bool: True if the CAS succeeded; False if expected_status did not match.

        Raises:
            ValueError: if the transition is illegal, or if now is naive.
            LookupError: if operation_id does not exist.
        """
        _require_aware(now, "now")
        allowed = _OPERATION_TRANSITIONS.get(expected_status, frozenset())
        if new_status not in allowed:
            raise ValueError(f"illegal operation transition {expected_status!r} -> {new_status!r}")

        values: dict[str, Any] = {"status": new_status, "updated_at": now}
        if attempts is not None:
            values["attempts"] = attempts
        if safe_error is not None:
            values["last_safe_error"] = safe_error
        if result is not None:
            values["result_json"] = result
        if new_status in (OperationStatus.SUCCEEDED, OperationStatus.FAILED):
            values["completed_at"] = now
        dml = cast(
            "CursorResult[Any]",
            self._session.execute(
                update(Operation)
                .where(Operation.id == operation_id, Operation.status == expected_status)
                .values(**values)
                .execution_options(synchronize_session=False)
            ),
        )
        if dml.rowcount:
            return True
        if self._session.execute(select(Operation.id).where(Operation.id == operation_id)).scalar_one_or_none() is None:
            raise LookupError(f"operation {operation_id!r} not found")
        return False

    def get_for_batch(self, batch_id: str) -> list[OperationRecord]:
        """Return all operations for a batch ordered by creation time.

        Args:
            batch_id: the parent batch UUID.

        Returns:
            list[OperationRecord]: operations in creation order.
        """
        rows = self._session.execute(select(Operation).where(Operation.batch_id == batch_id).order_by(Operation.created_at)).scalars().all()
        return [_operation_to_record(r) for r in rows]

    def get_for_retry(self, batch_id: str) -> list[OperationRecord]:
        """Return PENDING and FAILED operations eligible for retry.

        successful operations are never included. the list is ordered by creation time.

        Args:
            batch_id: the parent batch UUID.

        Returns:
            list[OperationRecord]: retry-eligible operations in creation order.
        """
        rows = (
            self._session
            .execute(
                select(Operation)
                .where(Operation.batch_id == batch_id, Operation.status.in_([OperationStatus.PENDING, OperationStatus.FAILED]))
                .order_by(Operation.created_at)
            )
            .scalars()
            .all()
        )
        return [_operation_to_record(r) for r in rows]


class HistoryRepository:
    """transaction-scoped repository for tracked slack message history."""

    def __init__(self, session: Session) -> None:
        """Bind the repository to an open session."""
        self._session = session

    def record(self, inp: NewMessageInput) -> MessageRecord:
        """Record a new message and retire the prior latest marker for the same scope.

        for GROUP_SUMMARY messages: retires prior latest within the same group.
        for ASSET_ROOT messages: retires prior latest within the same workspace/channel/entity.

        Args:
            inp: the new message input; now must be UTC-aware.

        Returns:
            MessageRecord: the newly created message record with is_latest=True.

        Raises:
            ValueError: if inp.now is naive.
        """
        self._validate_input(inp)
        dialect = self._session.get_bind().dialect.name
        if dialect == "postgresql":
            self._session.execute(_history_advisory_lock_statement(inp))
        if dialect == "sqlite":
            return self._record_sqlite(inp)
        return self._record_once(inp)

    @staticmethod
    def _validate_input(inp: NewMessageInput) -> None:
        """Validate message-kind/entity invariants before issuing SQL."""
        _require_aware(inp.now, "now")
        if inp.kind == MessageKind.ASSET_ROOT and (inp.asset_entity_id is None or inp.asset_entity_id <= 0):
            raise ValueError("ASSET_ROOT messages require a positive asset_entity_id")
        if inp.kind == MessageKind.GROUP_SUMMARY and inp.asset_entity_id is not None:
            raise ValueError("GROUP_SUMMARY messages require asset_entity_id=None")

    def _record_sqlite(self, inp: NewMessageInput) -> MessageRecord:
        """Serialize SQLite replacement and isolate a rare uniqueness retry."""
        attempts = 3
        for attempt in range(attempts):
            try:
                with self._session.begin_nested():
                    row = self._record_once(inp)
                    self._session.flush()
                return row
            except IntegrityError:
                if attempt == attempts - 1:
                    raise
        raise RuntimeError("unreachable history retry state")

    def _record_once(self, inp: NewMessageInput) -> MessageRecord:
        """Retire the current row and insert its replacement in this transaction."""
        if inp.kind == MessageKind.GROUP_SUMMARY:
            self._session.execute(
                update(Message)
                .where(Message.group_id == inp.group_id, Message.kind == inp.kind, Message.is_latest.is_(True))
                .values(is_latest=False, updated_at=inp.now)
            )
        else:
            self._session.execute(
                update(Message)
                .where(
                    Message.workspace_id == inp.workspace_id,
                    Message.channel_id == inp.channel_id,
                    Message.asset_entity_id == inp.asset_entity_id,
                    Message.kind == inp.kind,
                    Message.is_latest.is_(True),
                )
                .values(is_latest=False, updated_at=inp.now)
            )

        row = Message(
            id=_new_id(),
            workspace_id=inp.workspace_id,
            channel_id=inp.channel_id,
            group_id=inp.group_id,
            batch_id=inp.batch_id,
            kind=inp.kind,
            asset_entity_id=inp.asset_entity_id,
            slack_ts=inp.slack_ts,
            permalink=inp.permalink,
            is_latest=True,
            canvas_metadata_json=inp.canvas_metadata,
            created_at=inp.now,
            updated_at=inp.now,
            last_editor_id=None,
            last_edited_at=None,
        )
        self._session.add(row)
        return _message_to_record(row)

    def latest_group_summary(self, group_id: str) -> MessageRecord | None:
        """Return the current latest group-summary message for a group.

        Args:
            group_id: the group's UUID string.

        Returns:
            MessageRecord | None: the latest summary, or None if none exists.
        """
        row = self._session.execute(
            select(Message).where(Message.group_id == group_id, Message.kind == MessageKind.GROUP_SUMMARY, Message.is_latest.is_(True))
        ).scalar_one_or_none()
        return None if row is None else _message_to_record(row)

    def latest_asset_root(self, workspace_id: str, channel_id: str, asset_entity_id: int) -> MessageRecord | None:
        """Return the current latest asset-root message for a specific entity.

        Args:
            workspace_id: the workspace's slack ID.
            channel_id: the channel's slack ID.
            asset_entity_id: the ShotGrid entity ID.

        Returns:
            MessageRecord | None: the latest asset-root message, or None.
        """
        row = self._session.execute(
            select(Message).where(
                Message.workspace_id == workspace_id,
                Message.channel_id == channel_id,
                Message.asset_entity_id == asset_entity_id,
                Message.kind == MessageKind.ASSET_ROOT,
                Message.is_latest.is_(True),
            )
        ).scalar_one_or_none()
        return None if row is None else _message_to_record(row)

    def get_by_channel_ts(self, *, workspace_id: str, channel_id: str, slack_ts: str) -> MessageRecord | None:
        """Return a tracked message by channel and Slack timestamp.

        Args:
            workspace_id: slack workspace id.
            channel_id: slack channel id.
            slack_ts: slack message timestamp.

        Returns:
            MessageRecord | None: the matching message, or None.
        """
        row = self._session.execute(
            select(Message).where(Message.workspace_id == workspace_id, Message.channel_id == channel_id, Message.slack_ts == slack_ts)
        ).scalar_one_or_none()
        return None if row is None else _message_to_record(row)

    def list_latest_asset_roots_for_group(self, group_id: str) -> list[MessageRecord]:
        """Return all current latest asset-root messages for a group.

        Args:
            group_id: parent group uuid.

        Returns:
            list[MessageRecord]: latest asset roots ordered by entity id.
        """
        rows = (
            self._session.execute(
                select(Message)
                .where(Message.group_id == group_id, Message.kind == MessageKind.ASSET_ROOT, Message.is_latest.is_(True))
                .order_by(Message.asset_entity_id)
            )
            .scalars()
            .all()
        )
        return [_message_to_record(row) for row in rows]

    def touch_editor(self, message_id: str, *, editor_id: str, now: datetime, canvas_metadata: dict[str, Any] | None = None) -> MessageRecord:
        """Record the last editor and optional updated edit snapshot metadata.

        Args:
            message_id: tracked message uuid.
            editor_id: slack user id of the editor.
            now: UTC-aware edit timestamp.
            canvas_metadata: optional replacement metadata payload.

        Returns:
            MessageRecord: updated message record.

        Raises:
            ValueError: if now is naive.
            LookupError: if message_id does not exist.
        """
        _require_aware(now, "now")
        row = self._session.get(Message, message_id)
        if row is None:
            raise LookupError(f"message {message_id!r} not found")
        row.last_editor_id = editor_id
        row.last_edited_at = now
        row.updated_at = now
        if canvas_metadata is not None:
            row.canvas_metadata_json = canvas_metadata
        return _message_to_record(row)


# ---------------------------------------------------------------------------
# repository bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Repositories:
    """bundle of transaction-scoped repositories sharing one caller-owned session.

    use Repositories.from_session(session) to construct; do not instantiate directly.
    the caller is responsible for committing or rolling back the session.
    """

    drafts: DraftRepository
    batches: BatchRepository
    operations: OperationRepository
    history: HistoryRepository
    groups: GroupRepository

    @classmethod
    def from_session(cls, session: Session) -> Repositories:
        """Create a Repositories bundle bound to the given session.

        Args:
            session: an open sqlalchemy session; must not be closed.

        Returns:
            Repositories: bundle with all four repositories sharing the session.
        """
        return cls(
            drafts=DraftRepository(session),
            batches=BatchRepository(session),
            operations=OperationRepository(session),
            history=HistoryRepository(session),
            groups=GroupRepository(session),
        )
