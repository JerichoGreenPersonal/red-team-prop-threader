"""sqlalchemy 2.x declarative table definitions for the prop-threader database."""

# note: `from __future__ import annotations` is intentionally omitted here.
# sqlalchemy 2.0's DeclarativeBase resolves `Mapped[...]` annotations via
# typing.get_type_hints() at class definition time; moving `Mapped` into a
# TYPE_CHECKING block would cause a NameError during mapper configuration.

from typing import Any
from datetime import datetime, timezone

from sqlalchemy import JSON, Index, String, Boolean, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, DeclarativeBase, mapped_column  # noqa: TC002
from sqlalchemy.types import TypeDecorator


__all__ = ("Base", "Batch", "BatchAsset", "ChannelLease", "Draft", "Group", "Message", "Operation", "UtcDateTime")


class UtcDateTime(TypeDecorator[datetime]):
    """timezone-aware UTC datetime type that rehydrates SQLite reads as UTC.

    write path: accepts only timezone-aware datetimes; converts to UTC before
    storing as a naive value (SQLite stores as ISO-8601 string without offset).

    read path: always returns a UTC-aware datetime. SQLite returns a naive
    datetime that is stamped with UTC; PostgreSQL returns a tz-aware value
    that is converted to UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        """Convert aware datetime to UTC before storage.

        Args:
            value: the datetime to store, must be timezone-aware.
            dialect: the sqlalchemy dialect (unused directly).

        Returns:
            datetime | None: UTC-normalised naive datetime, or None.

        Raises:
            ValueError: if value is a naive datetime with no tzinfo.
        """
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(f"naive datetime rejected; supply a UTC-aware datetime (e.g. datetime(..., tzinfo=timezone.utc)), got {value!r}")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        """Rehydrate stored datetime as UTC-aware.

        Args:
            value: the datetime read from the database.
            dialect: the sqlalchemy dialect (unused directly).

        Returns:
            datetime | None: UTC-aware datetime, or None.
        """
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        # sqlite returns naive; stamp as UTC
        return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    """shared declarative base for all prop-threader ORM tables."""


class Draft(Base):
    """durable snapshot of a user's in-progress prop request."""

    __tablename__ = "drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    snapshot_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (UniqueConstraint("workspace_id", "channel_id", "user_id", name="uq_draft_identity"),)


class Group(Base):
    """a named prop-request group within a workspace channel."""

    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_title: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (UniqueConstraint("workspace_id", "channel_id", "normalized_title", name="uq_group_identity"),)


class Batch(Base):
    """a single submission batch within a prop-request group."""

    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    submitter_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    payload_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (Index("ix_batch_workspace_channel", "workspace_id", "channel_id"),)


class BatchAsset(Base):
    """immutable asset record associated with a submission batch."""

    __tablename__ = "batch_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("batches.id"), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_index: Mapped[int] = mapped_column(Integer, nullable=False)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    asset_details_json: Mapped[Any] = mapped_column(JSON, nullable=True)

    __table_args__ = (UniqueConstraint("batch_id", "entity_id", name="uq_batch_asset_entity"), Index("ix_batch_asset_batch", "batch_id"))


class Message(Base):
    """slack message record tracking group summaries and asset-root posts."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("groups.id"), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("batches.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slack_ts: Mapped[str] = mapped_column(String(64), nullable=False)
    permalink: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    canvas_metadata_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_editor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_edited_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (
        Index("ix_message_latest_group_summary", "group_id", "kind", "is_latest"),
        Index("ix_message_latest_asset_root", "workspace_id", "channel_id", "asset_entity_id", "kind", "is_latest"),
    )


class Operation(Base):
    """a single durable operation within a batch workflow."""

    __tablename__ = "operations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("batches.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_entity_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_safe_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    payload_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    __table_args__ = (UniqueConstraint("batch_id", "kind", "asset_entity_id", name="uq_operation_idempotency"),)


class ChannelLease(Base):
    """atomic renewable lock on a workspace channel for exclusive workflow ownership."""

    __tablename__ = "channel_leases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    lease_token: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    renewed_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (UniqueConstraint("workspace_id", "channel_id", name="uq_channel_lease"),)
