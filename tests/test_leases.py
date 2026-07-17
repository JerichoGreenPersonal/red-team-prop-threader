"""tests for the channel lease repository: acquire, renew, release, and contention."""

from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import datetime, timezone, timedelta
import threading

import pytest
from sqlalchemy import event, create_engine
from sqlalchemy.orm import Session

from red_team_prop_threader.leases import ChannelLeaseRepository
from red_team_prop_threader.tables import Base


if TYPE_CHECKING:
    from collections.abc import Generator

    from conftest import FakeClock
    from sqlalchemy import Engine

    from red_team_prop_threader.leases import LeaseResult


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    """in-memory sqlite engine with pragmas."""
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
    """Bare session for single-session lease tests."""
    s = Session(engine)
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def leases(session: Session, engine: Engine) -> ChannelLeaseRepository:
    """Channel lease repository bound to the test session."""
    return ChannelLeaseRepository(session, engine)


# ---------------------------------------------------------------------------
# lease acquire
# ---------------------------------------------------------------------------


def test_channel_lease_acquire_new(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Acquiring a lease on a channel with no existing lease succeeds."""
    result = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert result.acquired is True
    assert result.owner_user_id == "U1"
    assert result.token is not None
    assert result.expires_at > clock.now()


def test_channel_lease_rejects_second_user_and_recovers_after_ten_minutes(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Second user is rejected while lease is active; succeeds after expiry."""
    assert leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10)).acquired
    busy = leases.acquire("C1", "U2", clock.now(), timedelta(minutes=10))
    assert busy.owner_user_id == "U1"
    clock.advance(minutes=10, seconds=1)
    assert leases.acquire("C1", "U2", clock.now(), timedelta(minutes=10)).acquired


def test_lease_busy_does_not_expose_token(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """The token is not exposed when the caller does not own the lease."""
    leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    busy = leases.acquire("C1", "U2", clock.now(), timedelta(minutes=10))
    assert busy.acquired is False
    assert busy.token is None
    assert busy.owner_user_id == "U1"


def test_lease_same_owner_reacquire(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """The same owner can reacquire the lease and extend expiry."""
    r1 = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert r1.acquired is True
    clock.advance(minutes=5)
    r2 = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert r2.acquired is True
    assert r2.expires_at > r1.expires_at


def test_lease_expired_can_be_acquired_by_new_user(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """A lease that has strictly expired can be taken by a new user."""
    leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    clock.advance(minutes=10, seconds=1)
    result = leases.acquire("C1", "U2", clock.now(), timedelta(minutes=10))
    assert result.acquired is True
    assert result.owner_user_id == "U2"


def test_lease_exact_boundary_not_expired(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """At exactly the expiry instant, the lease is NOT expired (now > expires_at is required)."""
    leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    clock.advance(minutes=10)  # now == expires_at exactly
    result = leases.acquire("C1", "U2", clock.now(), timedelta(minutes=10))
    assert result.acquired is False
    assert result.owner_user_id == "U1"


def test_lease_acquire_busy_returns_expiry(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Busy result includes the current owner's expiry time."""
    t0 = clock.now()
    leases.acquire("C1", "U1", t0, timedelta(minutes=10))
    busy = leases.acquire("C1", "U2", clock.now(), timedelta(minutes=10))
    expected_expiry = t0 + timedelta(minutes=10)
    assert busy.expires_at == expected_expiry


def test_lease_duration_must_be_positive(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Acquire raises ValueError for zero or negative duration."""
    with pytest.raises(ValueError):
        leases.acquire("C1", "U1", clock.now(), timedelta(0))
    with pytest.raises(ValueError):
        leases.acquire("C1", "U1", clock.now(), timedelta(seconds=-1))


def test_lease_naive_datetime_rejected(leases: ChannelLeaseRepository) -> None:
    """Naive datetime is rejected at the acquire boundary."""
    naive = datetime(2025, 1, 1, 12, 0, 0)
    with pytest.raises((ValueError, TypeError)):
        leases.acquire("C1", "U1", naive, timedelta(minutes=10))


# ---------------------------------------------------------------------------
# lease renew
# ---------------------------------------------------------------------------


def test_lease_renew(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Owner can renew the lease using the correct token."""
    r = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert r.token is not None
    clock.advance(minutes=5)
    renewed = leases.renew("C1", "U1", r.token, clock.now(), timedelta(minutes=10))
    assert renewed.acquired is True
    assert renewed.expires_at > r.expires_at


def test_lease_renew_bad_token(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Renewing with the wrong token returns acquired=False."""
    leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    result = leases.renew("C1", "U1", "wrong-token", clock.now(), timedelta(minutes=10))
    assert result.acquired is False


def test_lease_renew_wrong_owner(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Renewing as a different user than the owner returns acquired=False."""
    r = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert r.token is not None
    result = leases.renew("C1", "U2", r.token, clock.now(), timedelta(minutes=10))
    assert result.acquired is False


def test_lease_renew_expired_fails_without_resurrection(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """A strictly expired lease cannot be renewed by its former owner."""
    acquired = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert acquired.token is not None
    clock.advance(minutes=10, seconds=1)

    renewed = leases.renew("C1", "U1", acquired.token, clock.now(), timedelta(minutes=10))

    assert renewed.acquired is False
    current = leases.get("C1")
    assert current is not None
    assert current.expires_at < clock.now()


def test_lease_renew_at_exact_expiry_succeeds(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Exact equality is active, so the current owner may renew."""
    acquired = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert acquired.token is not None
    clock.advance(minutes=10)

    renewed = leases.renew("C1", "U1", acquired.token, clock.now(), timedelta(minutes=10))

    assert renewed.acquired is True


def test_lease_stale_token_cannot_renew_after_reacquire(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Reacquisition rotates the token and makes the old token stale."""
    first = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert first.token is not None
    second = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert second.token is not None

    stale = leases.renew("C1", "U1", first.token, clock.now(), timedelta(minutes=10))

    assert stale.acquired is False
    assert leases.renew("C1", "U1", second.token, clock.now(), timedelta(minutes=10)).acquired


def test_expired_renew_loses_to_acquire_from_separate_session(tmp_path: object) -> None:
    """A concurrent expired renewal cannot overwrite a replacement owner."""
    from red_team_prop_threader.db import build_engine

    db_url = f"sqlite:///{tmp_path / 'renew-acquire.db'}"  # type: ignore[operator]
    engine = build_engine(db_url)
    Base.metadata.create_all(engine)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    with Session(engine) as setup:
        initial = ChannelLeaseRepository(setup, engine).acquire("C1", "U1", now, timedelta(minutes=10))
        setup.commit()
    assert initial.token is not None
    expired_now = now + timedelta(minutes=10, seconds=1)
    barrier = threading.Barrier(2)
    results: dict[str, LeaseResult] = {}
    errors: list[Exception] = []

    def _acquire() -> None:
        with Session(engine) as acquiring:
            try:
                barrier.wait()
                results["acquire"] = ChannelLeaseRepository(acquiring, engine).acquire("C1", "U2", expired_now, timedelta(minutes=10))
                acquiring.commit()
            except Exception as exc:
                errors.append(exc)

    def _renew() -> None:
        with Session(engine) as stale:
            try:
                barrier.wait()
                results["renew"] = ChannelLeaseRepository(stale, engine).renew("C1", "U1", initial.token, expired_now, timedelta(minutes=10))
                stale.commit()
            except Exception as exc:
                errors.append(exc)

    threads = [threading.Thread(target=_acquire), threading.Thread(target=_renew)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert results["acquire"].acquired is True
    assert results["renew"].acquired is False
    with Session(engine) as verify:
        current = ChannelLeaseRepository(verify, engine).get("C1")
        assert current is not None
        assert current.owner_user_id == "U2"
    engine.dispose()


# ---------------------------------------------------------------------------
# lease release
# ---------------------------------------------------------------------------


def test_lease_release(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Owner can release the lease using the correct token."""
    r = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert r.token is not None
    released = leases.release("C1", "U1", r.token)
    assert released is True
    # another user can now acquire
    result = leases.acquire("C1", "U2", clock.now(), timedelta(minutes=10))
    assert result.acquired is True


def test_lease_release_bad_token(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Release with wrong token returns False and does not release the lease."""
    leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    released = leases.release("C1", "U1", "bad-token")
    assert released is False
    # original owner still holds it
    busy = leases.acquire("C1", "U2", clock.now(), timedelta(minutes=10))
    assert busy.acquired is False


def test_lease_release_wrong_owner(leases: ChannelLeaseRepository, clock: FakeClock) -> None:
    """Release as a different user returns False."""
    r = leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    assert r.token is not None
    released = leases.release("C1", "U2", r.token)
    assert released is False


# ---------------------------------------------------------------------------
# lease get
# ---------------------------------------------------------------------------


def test_lease_get_returns_current(leases: ChannelLeaseRepository, clock: FakeClock, session: Session) -> None:
    """Get returns the current lease record."""
    leases.acquire("C1", "U1", clock.now(), timedelta(minutes=10))
    session.flush()
    result = leases.get("C1")
    assert result is not None
    assert result.owner_user_id == "U1"


def test_lease_get_missing(leases: ChannelLeaseRepository) -> None:
    """Get returns None when no lease exists for the channel."""
    result = leases.get("NONEXISTENT")
    assert result is None


# ---------------------------------------------------------------------------
# concurrent sqlite contention
# ---------------------------------------------------------------------------


def test_lease_concurrent_sqlite_contention(tmp_path: object) -> None:
    """Concurrent acquire from separate sessions yields exactly one owner."""
    db_path = str(tmp_path / "contention.db")  # type: ignore[operator]
    db_url = f"sqlite:///{db_path}"

    results: list[LeaseResult] = []
    errors: list[Exception] = []

    def _make_engine() -> Engine:
        e = create_engine(db_url, connect_args={"check_same_thread": False})

        @event.listens_for(e, "connect")
        def _pragmas(dbapi_conn: object, _record: object) -> None:
            c = dbapi_conn.cursor()  # type: ignore[union-attr]
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            c.close()

        return e

    eng = _make_engine()
    Base.metadata.create_all(eng)
    eng.dispose()

    barrier = threading.Barrier(2)
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def _worker(user_id: str) -> None:
        e = _make_engine()
        s = Session(e)
        try:
            repo = ChannelLeaseRepository(s, e)
            barrier.wait()
            result = repo.acquire("C-CONTENTION", user_id, now, timedelta(minutes=10))
            s.commit()
            results.append(result)
        except Exception as exc:
            errors.append(exc)
        finally:
            s.close()
            e.dispose()

    threads = [threading.Thread(target=_worker, args=(f"U{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"contention errors: {errors}"
    acquired_count = sum(1 for r in results if r.acquired)
    assert acquired_count == 1, f"expected exactly one acquisition, got {acquired_count}: {results}"
