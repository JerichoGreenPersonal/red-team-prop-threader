"""No-connection SQL compilation tests for PostgreSQL and SQLite persistence paths."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy.schema import CreateIndex
from sqlalchemy.dialects import sqlite, postgresql

from red_team_prop_threader.domain import OperationKind
from red_team_prop_threader.tables import Message
from red_team_prop_threader.repositories import MessageKind, NewMessageInput


def _advisory_key(inp: NewMessageInput) -> int:
    """Extract the deterministic advisory key from a compiled lock statement."""
    from red_team_prop_threader.repositories import _history_advisory_lock_statement

    compiled = _history_advisory_lock_statement(inp).compile(dialect=postgresql.dialect())
    [key] = compiled.params.values()
    assert isinstance(key, int)
    return key


def _values() -> dict[str, object]:
    """Return representative bind values for dialect statement builders."""
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return {
        "id": "id",
        "workspace_id": "W1",
        "channel_id": "C1",
        "user_id": "U1",
        "snapshot_json": {},
        "imported_at": now,
        "created_at": now,
        "updated_at": now,
        "expires_at": now + timedelta(hours=1),
    }


def test_postgres_draft_upsert_compiles_without_connection() -> None:
    """The PostgreSQL draft path compiles to conflict-safe update SQL."""
    from red_team_prop_threader.repositories import _build_draft_upsert

    sql = str(_build_draft_upsert("postgresql", _values()).compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in sql
    assert "DO UPDATE" in sql
    assert "created_at" not in sql.split("DO UPDATE SET", maxsplit=1)[1]


def test_postgres_operation_insert_compiles_without_connection() -> None:
    """The PostgreSQL operation path compiles to conflict-do-nothing SQL."""
    from red_team_prop_threader.repositories import _build_operation_insert

    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    values = {
        "id": "id",
        "batch_id": "batch",
        "kind": OperationKind.POST_SUMMARY,
        "asset_entity_id": 0,
        "status": "pending",
        "idempotency_key": "key",
        "attempts": 0,
        "last_safe_error": None,
        "payload_json": None,
        "result_json": None,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }
    sql = str(_build_operation_insert("postgresql", values).compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in sql
    assert "DO NOTHING" in sql


def test_postgres_lease_acquire_and_renew_compile_without_connection() -> None:
    """PostgreSQL lease acquisition locks rows and missing inserts remain race-safe."""
    from red_team_prop_threader.leases import _lease_renew_statement, _lease_for_update_statement, _postgres_lease_insert_statement

    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    locked_sql = str(_lease_for_update_statement("W1", "C1").compile(dialect=postgresql.dialect()))
    insert_sql = str(
        _postgres_lease_insert_statement(
            workspace_id="W1", channel_id="C1", owner_user_id="U1", new_token="token", now=now, expires_at=now + timedelta(minutes=10)
        ).compile(dialect=postgresql.dialect())
    )
    renew_sql = str(
        _lease_renew_statement(
            workspace_id="W1", channel_id="C1", owner_user_id="U1", lease_token="token", new_token="next", now=now, expires_at=now + timedelta(minutes=10)
        ).compile(dialect=postgresql.dialect())
    )
    assert "FOR UPDATE" in locked_sql
    assert "ON CONFLICT" in insert_sql and "DO NOTHING" in insert_sql
    assert "owner_user_id" in renew_sql and "lease_token" in renew_sql and "expires_at >=" in renew_sql


def test_postgres_advisory_lock_uses_stable_asset_scope() -> None:
    """Same workspace/channel/kind/entity maps to one deterministic advisory key."""
    from red_team_prop_threader.repositories import _history_advisory_lock_statement

    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first = NewMessageInput("W1", "C1", "G1", None, MessageKind.ASSET_ROOT, 42, "1", "https://example/1", None, now)
    other_group = NewMessageInput("W1", "C1", "G2", None, MessageKind.ASSET_ROOT, 42, "2", "https://example/2", None, now)
    other_asset = NewMessageInput("W1", "C1", "G2", None, MessageKind.ASSET_ROOT, 43, "3", "https://example/3", None, now)

    first_compiled = _history_advisory_lock_statement(first).compile(dialect=postgresql.dialect())
    other_group_compiled = _history_advisory_lock_statement(other_group).compile(dialect=postgresql.dialect())
    other_asset_compiled = _history_advisory_lock_statement(other_asset).compile(dialect=postgresql.dialect())

    assert "pg_advisory_xact_lock" in str(first_compiled)
    assert tuple(first_compiled.params.values()) == tuple(other_group_compiled.params.values())
    assert tuple(first_compiled.params.values()) != tuple(other_asset_compiled.params.values())


def test_group_summary_advisory_scope_matches_unique_index() -> None:
    """Group-summary locks depend on kind and group ID, matching DB uniqueness."""
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first = NewMessageInput("W1", "C1", "G1", None, MessageKind.GROUP_SUMMARY, None, "1", "https://example/1", None, now)
    moved = NewMessageInput("W2", "C2", "G1", None, MessageKind.GROUP_SUMMARY, None, "2", "https://example/2", None, now)
    other_group = NewMessageInput("W1", "C1", "G2", None, MessageKind.GROUP_SUMMARY, None, "3", "https://example/3", None, now)

    assert _advisory_key(first) == _advisory_key(moved)
    assert _advisory_key(first) != _advisory_key(other_group)


def test_advisory_scope_encoding_is_unambiguous() -> None:
    """Components that collide under delimiter joining produce different keys."""
    now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    first = NewMessageInput("W\x1fC", "D", "G1", None, MessageKind.ASSET_ROOT, 42, "1", "https://example/1", None, now)
    ambiguous_under_join = NewMessageInput("W", "C\x1fD", "G2", None, MessageKind.ASSET_ROOT, 42, "2", "https://example/2", None, now)

    assert _advisory_key(first) != _advisory_key(ambiguous_under_join)


def test_partial_latest_indexes_compile_for_both_dialects() -> None:
    """Both latest-message partial unique indexes emit predicates on SQLite and PostgreSQL."""
    indexes = {index.name: index for index in Message.__table__.indexes}
    for name in ("uq_message_latest_group_summary", "uq_message_latest_asset_root"):
        sqlite_sql = str(CreateIndex(indexes[name]).compile(dialect=sqlite.dialect()))
        postgres_sql = str(CreateIndex(indexes[name]).compile(dialect=postgresql.dialect()))
        assert "CREATE UNIQUE INDEX" in sqlite_sql
        assert " WHERE " in sqlite_sql
        assert "CREATE UNIQUE INDEX" in postgres_sql
        assert " WHERE " in postgres_sql
