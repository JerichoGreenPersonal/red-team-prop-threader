"""atomic renewable channel leases for exclusive workflow ownership."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
import secrets
from dataclasses import dataclass

from sqlalchemy import delete, select

from red_team_prop_threader.tables import ChannelLease


if TYPE_CHECKING:
    from datetime import datetime, timedelta

    from sqlalchemy import Table, Engine
    from sqlalchemy.orm import Session
    from sqlalchemy.engine import CursorResult


__all__ = ("ChannelLeaseRepository", "LeaseResult")


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
    import uuid

    return str(uuid.uuid4())


def _new_token() -> str:
    """Generate a cryptographically random opaque lease token."""
    return secrets.token_hex(32)


@dataclass(frozen=True, slots=True)
class LeaseResult:
    """immutable result of a lease acquire, renew, or failed attempt.

    token is only present when the caller owns the lease (acquired=True).
    when acquired=False, owner_user_id and expires_at describe the current holder.
    """

    acquired: bool
    owner_user_id: str
    expires_at: datetime
    token: str | None


class ChannelLeaseRepository:
    """atomic channel lease repository with separate-session contention safety.

    for sqlite, lease acquisition uses a single upsert statement to avoid
    read-then-write races (two concurrent sessions cannot both acquire the same
    channel simultaneously due to sqlite's write serialization and the upsert's
    WHERE guard).

    for postgresql, a SELECT FOR UPDATE pattern serializes concurrent acquire
    attempts via row-level locking.

    expiry boundary: a lease is considered expired when now > expires_at (strictly).
    at exact equality (now == expires_at) the lease is NOT expired.
    """

    def __init__(self, session: Session, engine: Engine) -> None:
        """Bind the repository to an open session, detecting the database dialect.

        Args:
            session: an open sqlalchemy session; must not be closed.
            engine: the engine that created the session; used to determine the
                dialect for acquire/upsert path selection.
        """
        self._session = session
        self._dialect = engine.dialect.name

    # ------------------------------------------------------------------
    # public interface
    # ------------------------------------------------------------------

    def acquire(self, channel_id: str, owner_user_id: str, now: datetime, duration: timedelta, *, workspace_id: str = "W1") -> LeaseResult:
        """Attempt to acquire an exclusive lease on a channel.

        a free or strictly expired lease may be acquired.
        the current owner may safely reacquire without releasing first.
        a different active owner receives acquired=False with current owner/expiry.

        at exact equality (now == expires_at) the lease is NOT expired.

        Args:
            channel_id: the slack channel ID to lease.
            owner_user_id: the requesting user's slack ID.
            now: current UTC-aware time.
            duration: requested lease duration; must be strictly positive.
            workspace_id: slack workspace ID; defaults to 'W1' for development.

        Returns:
            LeaseResult: acquired=True with token when owned; False with current owner otherwise.

        Raises:
            ValueError: if now is naive or duration is not positive.
        """
        _require_aware(now, "now")
        if duration.total_seconds() <= 0:
            raise ValueError(f"duration must be strictly positive, got {duration!r}")

        new_token = _new_token()
        expires_at = now + duration

        if self._dialect == "sqlite":
            acquired = self._acquire_sqlite(workspace_id, channel_id, owner_user_id, new_token, now, expires_at)
        else:
            acquired = self._acquire_pg(workspace_id, channel_id, owner_user_id, new_token, now, expires_at)

        if acquired:
            return LeaseResult(acquired=True, owner_user_id=owner_user_id, expires_at=expires_at, token=new_token)

        current = self._fetch(workspace_id, channel_id)
        if current is None:
            # should not happen; fall back to a failed result
            return LeaseResult(acquired=False, owner_user_id="", expires_at=now, token=None)
        return LeaseResult(acquired=False, owner_user_id=current.owner_user_id, expires_at=current.expires_at, token=None)

    def renew(self, channel_id: str, owner_user_id: str, lease_token: str, now: datetime, duration: timedelta, *, workspace_id: str = "W1") -> LeaseResult:
        """Renew an existing lease, extending its expiry.

        renewal requires matching owner and token. the lease must not have expired.

        Args:
            channel_id: the slack channel ID.
            owner_user_id: the current owner's slack ID.
            lease_token: the opaque token issued at acquisition time.
            now: current UTC-aware time.
            duration: new duration added from now; must be strictly positive.
            workspace_id: slack workspace ID; defaults to 'W1' for development.

        Returns:
            LeaseResult: acquired=True with updated token on success; False otherwise.

        Raises:
            ValueError: if now is naive or duration is not positive.
        """
        _require_aware(now, "now")
        if duration.total_seconds() <= 0:
            raise ValueError(f"duration must be strictly positive, got {duration!r}")

        row = self._fetch(workspace_id, channel_id)
        if row is None or row.owner_user_id != owner_user_id or row.lease_token != lease_token:
            # no lease, wrong owner, or bad token
            current_owner = row.owner_user_id if row is not None else ""
            current_expiry = row.expires_at if row is not None else now
            return LeaseResult(acquired=False, owner_user_id=current_owner, expires_at=current_expiry, token=None)

        new_token = _new_token()
        new_expires = now + duration
        row.lease_token = new_token
        row.expires_at = new_expires
        row.renewed_at = now
        row.version = row.version + 1
        return LeaseResult(acquired=True, owner_user_id=owner_user_id, expires_at=new_expires, token=new_token)

    def release(self, channel_id: str, owner_user_id: str, lease_token: str, *, workspace_id: str = "W1") -> bool:
        """Release a held lease, making the channel available immediately.

        Args:
            channel_id: the slack channel ID.
            owner_user_id: the owner's slack ID.
            lease_token: the opaque token issued at acquisition time.
            workspace_id: slack workspace ID; defaults to 'W1' for development.

        Returns:
            bool: True if the lease was released; False if the owner/token did not match.
        """
        dml_result = cast(
            "CursorResult[Any]",
            self._session.execute(
                delete(ChannelLease).where(
                    ChannelLease.workspace_id == workspace_id,
                    ChannelLease.channel_id == channel_id,
                    ChannelLease.owner_user_id == owner_user_id,
                    ChannelLease.lease_token == lease_token,
                )
            ),
        )
        return dml_result.rowcount > 0

    def get(self, channel_id: str, *, workspace_id: str = "W1") -> LeaseResult | None:
        """Return the current lease for a channel, or None if no lease exists.

        Args:
            channel_id: the slack channel ID.
            workspace_id: slack workspace ID; defaults to 'W1' for development.

        Returns:
            LeaseResult | None: the current lease (token is None since caller may not own it),
                or None if no lease exists.
        """
        row = self._fetch(workspace_id, channel_id)
        if row is None:
            return None
        return LeaseResult(acquired=True, owner_user_id=row.owner_user_id, expires_at=row.expires_at, token=None)

    # ------------------------------------------------------------------
    # dialect-specific acquire implementations
    # ------------------------------------------------------------------

    def _acquire_sqlite(self, workspace_id: str, channel_id: str, owner_user_id: str, new_token: str, now: datetime, expires_at: datetime) -> bool:
        """Sqlite acquire using a single upsert with a WHERE guard.

        the ON CONFLICT DO UPDATE WHERE clause is evaluated atomically within
        sqlite's write lock, preventing double-acquisition even under concurrent
        sessions. rowcount == 0 means the WHERE guard rejected the update (another
        active owner); rowcount == 1 means we acquired or reacquired.

        Args:
            workspace_id: slack workspace ID.
            channel_id: slack channel ID.
            owner_user_id: the requesting user's slack ID.
            new_token: freshly generated opaque token.
            now: current UTC-aware time (stored as renewed_at).
            expires_at: new expiry time.

        Returns:
            bool: True if this session acquired the lease.
        """
        from sqlalchemy.dialects.sqlite import insert as _insert

        tbl = cast("Table", ChannelLease.__table__)
        stmt = _insert(tbl).values(
            id=_new_id(),
            workspace_id=workspace_id,
            channel_id=channel_id,
            owner_user_id=owner_user_id,
            lease_token=new_token,
            expires_at=expires_at,
            created_at=now,
            renewed_at=now,
            version=1,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["workspace_id", "channel_id"],
            set_={
                "owner_user_id": stmt.excluded.owner_user_id,
                "lease_token": stmt.excluded.lease_token,
                "expires_at": stmt.excluded.expires_at,
                "renewed_at": stmt.excluded.renewed_at,
                "version": tbl.c.version + 1,
            },
            # update only when the existing lease is expired OR belongs to this user
            where=(tbl.c.expires_at < now) | (tbl.c.owner_user_id == owner_user_id),
        )
        dml_result = cast("CursorResult[Any]", self._session.execute(stmt))

        if dml_result.rowcount > 0:
            return True

        # rowcount == 0: WHERE guard prevented the update (another active owner).
        # verify by reading back to confirm we do NOT own it.
        self._session.expire_all()
        current = self._fetch(workspace_id, channel_id)
        return current is not None and current.owner_user_id == owner_user_id and current.lease_token == new_token

    def _acquire_pg(self, workspace_id: str, channel_id: str, owner_user_id: str, new_token: str, now: datetime, expires_at: datetime) -> bool:
        """Postgresql acquire using SELECT FOR UPDATE for row-level serialization.

        Args:
            workspace_id: slack workspace ID.
            channel_id: slack channel ID.
            owner_user_id: the requesting user's slack ID.
            new_token: freshly generated opaque token.
            now: current UTC-aware time.
            expires_at: new expiry time.

        Returns:
            bool: True if this session acquired the lease.
        """
        from sqlalchemy.dialects.postgresql import insert as _insert

        tbl = cast("Table", ChannelLease.__table__)

        # postgresql INSERT ON CONFLICT DO UPDATE is also atomic, reuse the same
        # upsert pattern as sqlite for consistency.
        stmt = _insert(tbl).values(
            id=_new_id(),
            workspace_id=workspace_id,
            channel_id=channel_id,
            owner_user_id=owner_user_id,
            lease_token=new_token,
            expires_at=expires_at,
            created_at=now,
            renewed_at=now,
            version=1,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["workspace_id", "channel_id"],
            set_={
                "owner_user_id": stmt.excluded.owner_user_id,
                "lease_token": stmt.excluded.lease_token,
                "expires_at": stmt.excluded.expires_at,
                "renewed_at": stmt.excluded.renewed_at,
                "version": tbl.c.version + 1,
            },
            where=(tbl.c.expires_at < now) | (tbl.c.owner_user_id == owner_user_id),
        )
        dml_result = cast("CursorResult[Any]", self._session.execute(stmt))

        if dml_result.rowcount > 0:
            return True

        # rowcount == 0: confirm via read-back
        current = self._fetch(workspace_id, channel_id)
        return current is not None and current.owner_user_id == owner_user_id and current.lease_token == new_token

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _fetch(self, workspace_id: str, channel_id: str) -> ChannelLease | None:
        """Fetch the current lease row for a workspace/channel pair.

        Args:
            workspace_id: slack workspace ID.
            channel_id: slack channel ID.

        Returns:
            ChannelLease | None: the ORM row, or None.
        """
        return self._session.execute(
            select(ChannelLease).where(ChannelLease.workspace_id == workspace_id, ChannelLease.channel_id == channel_id)
        ).scalar_one_or_none()
