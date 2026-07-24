"""tests for durable batch planning, execution, progress, and failed-only retry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from datetime import datetime, timezone, timedelta
from dataclasses import field, dataclass

import pytest
from sqlalchemy import event, create_engine
from sqlalchemy.orm import Session

from red_team_prop_threader.jobs import BatchPlanner, BatchExecutor
from red_team_prop_threader.domain import OperationKind
from red_team_prop_threader.leases import ChannelLeaseRepository
from red_team_prop_threader.tables import Base
from red_team_prop_threader._errors import PermissionDeniedError, RetryableExternalServiceError
from red_team_prop_threader.repositories import BatchStatus, Repositories, OperationStatus


if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Engine

    from red_team_prop_threader.jobs import ExecutionResult


# ---------------------------------------------------------------------------
# fake clock / slack
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    """deterministic utc clock."""

    _now: datetime = field(default_factory=lambda: datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc))

    def now(self) -> datetime:
        """Return the current fake instant."""
        return self._now

    def advance(self, *, minutes: int = 0, seconds: int = 0) -> None:
        """Advance the fake clock."""
        self._now += timedelta(minutes=minutes, seconds=seconds)


@dataclass
class FakeSlackGateway:
    """in-memory slack double for job execution tests."""

    posts: list[dict[str, Any]] = field(default_factory=list)
    asset_posts: list[str] = field(default_factory=list)
    canvas_edits: list[dict[str, Any]] = field(default_factory=list)
    updated_messages: list[dict[str, Any]] = field(default_factory=list)
    progress_updates: list[str] = field(default_factory=list)
    _fail_queue: list[tuple[str, bool]] = field(default_factory=list)
    _ts_counter: int = 0
    section_lookup_result: list[dict[str, str]] = field(default_factory=list)
    channel_canvas_ids: dict[str, str] = field(default_factory=dict)
    fail_edit_canvas_id: str | None = None

    def fail_next(self, method: str, *, retryable: bool = False) -> None:
        """Queue a failure for the next matching method call."""
        self._fail_queue.append((method, retryable))

    def _raise_if_queued(self, method: str) -> None:
        """Raise a queued failure when the method matches."""
        if not self._fail_queue:
            return
        queued_method, retryable = self._fail_queue[0]
        if queued_method != method:
            return
        self._fail_queue.pop(0)
        if retryable:
            raise RetryableExternalServiceError(f"{method} temporarily unavailable", retry_after=1.0)
        raise PermissionDeniedError(f"{method} permanently denied")

    def _next_ts(self) -> str:
        """Allocate a unique message timestamp."""
        self._ts_counter += 1
        return f"1700000000.{self._ts_counter:06d}"

    def open_dm(self, user_id: str) -> str:
        """Return a fake dm channel id."""
        del user_id
        return "Dprogress"

    def post_message(self, channel_id: str, *, text: str, blocks: list[dict[str, Any]] | None = None, thread_ts: str | None = None) -> dict[str, Any]:
        """Post a message, tracking summary vs asset roots."""
        # progress dms must not consume channel-side failure queues
        if channel_id.startswith("C"):
            self._raise_if_queued("post_message")
        ts = self._next_ts()
        record = {"channel_id": channel_id, "text": text, "blocks": blocks or [], "thread_ts": thread_ts, "ts": ts}
        self.posts.append(record)
        if channel_id.startswith("C") and "Asset:" in text:
            self.asset_posts.append(ts)
        if channel_id == "Dprogress":
            self.progress_updates.append(text)
        return {"ok": True, "channel": channel_id, "ts": ts}

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Record a message update."""
        self._raise_if_queued("update_message")
        record = {"channel_id": channel_id, "ts": ts, "text": text, "blocks": blocks or []}
        self.updated_messages.append(record)
        if channel_id == "Dprogress":
            self.progress_updates.append(text)
        return {"ok": True}

    def get_permalink(self, channel_id: str, message_ts: str) -> str:
        """Return a deterministic permalink."""
        return f"https://slack.example/{channel_id}/{message_ts}"

    def get_user_info(self, user_id: str) -> dict[str, object]:
        """Return a fake user profile."""
        return {"id": user_id, "profile": {"display_name": f"User {user_id}", "real_name": f"User {user_id}"}}

    def get_conversation_info(self, channel_id: str) -> dict[str, object]:
        """Return channel info with a canvas id."""
        canvas_id = self.channel_canvas_ids.get(channel_id, "Fcanvas")
        return {"id": channel_id, "properties": {"canvas": {"file_id": canvas_id, "is_empty": False}}}

    def get_file_info(self, file_id: str) -> dict[str, object]:
        """Return canvas file metadata."""
        return {"id": file_id, "title": "INDEX OF PROP REQUESTS", "name": "INDEX OF PROP REQUESTS"}

    def lookup_sections(self, canvas_id: str, *, contains_text: str | None = None, section_types: tuple[str, ...] = ("any_header",)) -> list[dict[str, str]]:
        """Return configured canvas sections."""
        del canvas_id, contains_text, section_types
        return list(self.section_lookup_result)

    def edit_canvas(self, canvas_id: str, *, operation: str, markdown: str | None = None, section_id: str | None = None, title: str | None = None) -> None:
        """Record a canvas edit, optionally failing when queued."""
        if self.fail_edit_canvas_id and canvas_id == self.fail_edit_canvas_id:
            raise PermissionDeniedError(f"edit_canvas denied for {canvas_id}")
        self._raise_if_queued("edit_canvas")
        self.canvas_edits.append({"canvas_id": canvas_id, "operation": operation, "markdown": markdown, "section_id": section_id, "title": title})

    def create_channel_canvas(self, channel_id: str, *, title: str) -> str:
        """Unused in job tests."""
        del channel_id, title
        return "Fcanvas"

    def rename_canvas(self, canvas_id: str, *, title: str) -> None:
        """Unused in job tests."""
        del canvas_id, title


# ---------------------------------------------------------------------------
# fixtures / builders
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    """in-memory sqlite engine with foreign keys enabled."""
    e = create_engine("sqlite:///:memory:")

    @event.listens_for(e, "connect")
    def _set_pragmas(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    """Open session bound to the in-memory engine."""
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def clock() -> FakeClock:
    """Deterministic clock fixture."""
    return FakeClock()


@pytest.fixture
def fake_slack() -> FakeSlackGateway:
    """Slack double fixture."""
    return FakeSlackGateway()


@pytest.fixture
def repositories(session: Session) -> Repositories:
    """Repository bundle for the test session."""
    return Repositories.from_session(session)


@pytest.fixture
def leases(session: Session, engine: Engine) -> ChannelLeaseRepository:
    """Channel lease repository for the test session."""
    return ChannelLeaseRepository(session, engine)


def _sample_payload(*, assets: list[dict[str, Any]] | None = None, lease_token: str = "lease-token") -> dict[str, Any]:
    """Build a confirmed-batch payload used by planner/executor tests."""
    return {
        "canvas_id": "Fcanvas",
        "group_title": "SEASON 31 PROP REQUEST THREADS",
        "group_animator_id": "Uanim",
        "group_additional_ids": [],
        "group_links": [{"label": "Brief", "url": "https://example.com/brief"}],
        "lease_token": lease_token,
        "assets": assets
        or [
            {
                "entity_id": 1001,
                "name": "Prop A",
                "url": "https://respawn.shotgunstudio.com/detail/Asset/1001",
                "animator_id": "Uasset",
                "additional_ids": [],
                "links": [],
            },
            {
                "entity_id": 1002,
                "name": "Prop B",
                "url": "https://respawn.shotgunstudio.com/detail/Asset/1002",
                "animator_id": "Uasset",
                "additional_ids": [],
                "links": [],
            },
        ],
    }


_PRIMARY_CHANNEL = "C04H4QZEYUE"
_PRIMARY_CANVAS = "F0BKLFG5S0M"


def sample_confirmed_batch(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock, *, payload: dict[str, Any] | None = None
) -> str:
    """Create a leased pending batch with planned operations and return its id."""
    now = clock.now()
    group = repositories.groups.create(
        workspace_id="W1", channel_id="C1", display_title="SEASON 31 PROP REQUEST THREADS", normalized_title="season 31 prop request threads", now=now
    )
    session.flush()
    body = payload if payload is not None else _sample_payload()
    batch = repositories.batches.create(group_id=group.id, workspace_id="W1", channel_id="C1", submitter_user_id="Usubmit", payload=body, now=now)
    session.flush()
    lease = leases.acquire("C1", "Usubmit", now, timedelta(minutes=10), workspace_id="W1")
    assert lease.acquired and lease.token is not None
    body = {**body, "lease_token": lease.token}
    repositories.batches.update_payload(batch.id, body)
    BatchPlanner(repositories).plan(batch.id, now=now)
    session.flush()
    return batch.id


def sample_satellite_batch_with_primary(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock, *, payload: dict[str, Any] | None = None
) -> str:
    """Create a leased satellite batch that mirrors onto the primary channel canvas."""
    now = clock.now()
    body = (
        payload
        if payload is not None
        else {
            **_sample_payload(assets=[_sample_payload()["assets"][0]]),
            "primary_asset_index_channel_id": _PRIMARY_CHANNEL,
            "primary_asset_index_canvas_id": _PRIMARY_CANVAS,
            "source_channel_display": "red-props",
        }
    )
    group = repositories.groups.create(
        workspace_id="W1", channel_id="C_satellite", display_title="SEASON 31 PROP REQUEST THREADS", normalized_title="season 31 prop request threads", now=now
    )
    session.flush()
    batch = repositories.batches.create(group_id=group.id, workspace_id="W1", channel_id="C_satellite", submitter_user_id="Usubmit", payload=body, now=now)
    session.flush()
    lease = leases.acquire("C_satellite", "Usubmit", now, timedelta(minutes=10), workspace_id="W1")
    assert lease.acquired and lease.token is not None
    body = {**body, "lease_token": lease.token}
    repositories.batches.update_payload(batch.id, body)
    BatchPlanner(repositories).plan(batch.id, now=now)
    session.flush()
    return batch.id


def sample_batch_with_canvas_failure(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock, fake_slack: FakeSlackGateway, executor: BatchExecutor
) -> ExecutionResult:
    """Run a batch that posts roots successfully but fails the first canvas index."""
    batch_id = sample_confirmed_batch(repositories, leases, session, clock)
    fake_slack.fail_next("edit_canvas", retryable=False)
    return executor.execute(batch_id)


@pytest.fixture
def executor(repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock, fake_slack: FakeSlackGateway) -> BatchExecutor:
    """Batch executor wired to test doubles."""
    return BatchExecutor(repositories=repositories, leases=leases, slack=fake_slack, canvas_slack=fake_slack, clock=clock, session=session)


# ---------------------------------------------------------------------------
# planner
# ---------------------------------------------------------------------------


def test_planner_creates_ordered_operations(repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock) -> None:
    """Planning emits summary, per-asset post/index/retire, then finalize."""
    batch_id = sample_confirmed_batch(repositories, leases, session, clock)
    ops = repositories.operations.get_for_batch(batch_id)
    kinds = [op.kind for op in ops]
    assert kinds[0] is OperationKind.POST_SUMMARY
    assert kinds[-1] is OperationKind.FINALIZE_SUMMARY
    assert kinds.count(OperationKind.POST_ASSET) == 2
    assert kinds.count(OperationKind.INDEX_ASSET) == 2
    assert kinds.count(OperationKind.RETIRE_PRIOR_LATEST) == 2
    assert all(op.status is OperationStatus.PENDING for op in ops)


def test_plan_includes_index_primary_asset_after_each_index(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock
) -> None:
    """Satellite batches plan INDEX_PRIMARY_ASSET immediately after each INDEX_ASSET."""
    now = clock.now()
    payload = {**_sample_payload(assets=[_sample_payload()["assets"][0]]), "primary_asset_index_channel_id": _PRIMARY_CHANNEL}
    group = repositories.groups.create(
        workspace_id="W1", channel_id="C_satellite", display_title="SEASON 31 PROP REQUEST THREADS", normalized_title="season 31 prop request threads", now=now
    )
    session.flush()
    batch = repositories.batches.create(group_id=group.id, workspace_id="W1", channel_id="C_satellite", submitter_user_id="Usubmit", payload=payload, now=now)
    session.flush()
    ops = BatchPlanner(repositories).plan(batch.id, now=now)
    kinds = [op.kind for op in ops]
    assert OperationKind.INDEX_PRIMARY_ASSET in kinds
    idx = kinds.index(OperationKind.INDEX_ASSET)
    assert kinds[idx + 1] is OperationKind.INDEX_PRIMARY_ASSET
    primary_ops = [op for op in ops if op.kind is OperationKind.INDEX_PRIMARY_ASSET]
    assert len(primary_ops) == 1
    assert primary_ops[0].asset_entity_id == 1001


def test_plan_skips_index_primary_when_channel_is_primary(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock
) -> None:
    """Primary-channel batches skip INDEX_PRIMARY_ASSET entirely."""
    now = clock.now()
    payload = {**_sample_payload(assets=[_sample_payload()["assets"][0]]), "primary_asset_index_channel_id": _PRIMARY_CHANNEL}
    group = repositories.groups.create(
        workspace_id="W1",
        channel_id=_PRIMARY_CHANNEL,
        display_title="SEASON 31 PROP REQUEST THREADS",
        normalized_title="season 31 prop request threads",
        now=now,
    )
    session.flush()
    batch = repositories.batches.create(
        group_id=group.id, workspace_id="W1", channel_id=_PRIMARY_CHANNEL, submitter_user_id="Usubmit", payload=payload, now=now
    )
    session.flush()
    ops = BatchPlanner(repositories).plan(batch.id, now=now)
    assert all(op.kind is not OperationKind.INDEX_PRIMARY_ASSET for op in ops)


def test_index_primary_asset_writes_primary_canvas(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock, fake_slack: FakeSlackGateway, executor: BatchExecutor
) -> None:
    """Satellite execution indexes the group onto the configured primary canvas file."""
    fake_slack.channel_canvas_ids = {"C_satellite": "Fcanvas", _PRIMARY_CHANNEL: "Fprimary"}
    batch_id = sample_satellite_batch_with_primary(repositories, leases, session, clock)
    result = executor.execute(batch_id)
    assert result.status is BatchStatus.SUCCEEDED
    primary_edits = [edit for edit in fake_slack.canvas_edits if edit["canvas_id"] == _PRIMARY_CANVAS]
    assert primary_edits
    assert any(edit["operation"] == "insert_at_start" for edit in primary_edits)
    primary_op = next(op for op in repositories.operations.get_for_batch(batch_id) if op.kind is OperationKind.INDEX_PRIMARY_ASSET)
    assert primary_op.status is OperationStatus.SUCCEEDED
    assert primary_op.result is not None
    assert primary_op.result["indexed"] is True
    assert primary_op.result["canvas_id"] == _PRIMARY_CANVAS


def test_index_primary_failure_does_not_fail_batch(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock, fake_slack: FakeSlackGateway, executor: BatchExecutor
) -> None:
    """Primary canvas failures succeed the op with indexed false and leave the batch succeeded."""
    fake_slack.channel_canvas_ids = {"C_satellite": "Fcanvas", _PRIMARY_CHANNEL: "Fprimary"}
    fake_slack.fail_edit_canvas_id = _PRIMARY_CANVAS
    batch_id = sample_satellite_batch_with_primary(repositories, leases, session, clock)
    result = executor.execute(batch_id)
    assert result.status is BatchStatus.SUCCEEDED
    primary_op = next(op for op in repositories.operations.get_for_batch(batch_id) if op.kind is OperationKind.INDEX_PRIMARY_ASSET)
    assert primary_op.status is OperationStatus.SUCCEEDED
    assert primary_op.result is not None
    assert primary_op.result["indexed"] is False
    assert "error" in primary_op.result


# ---------------------------------------------------------------------------
# execution / retry
# ---------------------------------------------------------------------------


def test_summary_failure_stops_before_asset_messages(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock, fake_slack: FakeSlackGateway, executor: BatchExecutor
) -> None:
    """Permanent summary failure stops before any asset roots are posted."""
    batch_id = sample_confirmed_batch(repositories, leases, session, clock)
    fake_slack.fail_next("post_message", retryable=False)
    result = executor.execute(batch_id)
    assert result.failed_operation is not None
    assert result.failed_operation.kind is OperationKind.POST_SUMMARY
    assert fake_slack.asset_posts == []
    batch = repositories.batches.get(batch_id)
    assert batch is not None
    assert batch.status is BatchStatus.FAILED


def test_retry_does_not_recreate_successful_roots(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock, fake_slack: FakeSlackGateway, executor: BatchExecutor
) -> None:
    """Retry requeues only failed/pending ops and keeps successful root timestamps."""
    first = sample_batch_with_canvas_failure(repositories, leases, session, clock, fake_slack, executor)
    root_timestamps = tuple(fake_slack.asset_posts)
    assert root_timestamps
    # clear queued failure so retry can complete canvas work
    fake_slack._fail_queue.clear()
    fake_slack.section_lookup_result = [{"id": "Slatest", "type": "any_header"}]
    # reacquire lease for retry (released on terminal failure)
    lease = leases.acquire("C1", "Usubmit", clock.now(), timedelta(minutes=10), workspace_id="W1")
    assert lease.acquired and lease.token is not None
    batch = repositories.batches.get(first.batch_id)
    assert batch is not None and batch.payload is not None
    repositories.batches.update_payload(first.batch_id, {**batch.payload, "lease_token": lease.token})
    session.flush()

    second = executor.retry_failed(first.batch_id)
    assert tuple(fake_slack.asset_posts) == root_timestamps
    assert fake_slack.canvas_edits
    assert second.status in (BatchStatus.SUCCEEDED, BatchStatus.FAILED)


def test_individual_asset_failure_continues(
    repositories: Repositories, leases: ChannelLeaseRepository, session: Session, clock: FakeClock, fake_slack: FakeSlackGateway, executor: BatchExecutor
) -> None:
    """One asset post failure does not prevent later asset posts."""
    batch_id = sample_confirmed_batch(repositories, leases, session, clock)
    original_post = fake_slack.post_message
    state = {"channel_posts": 0}

    def _post(channel_id: str, *, text: str, blocks: list[dict[str, Any]] | None = None, thread_ts: str | None = None) -> dict[str, Any]:
        if channel_id.startswith("C"):
            state["channel_posts"] += 1
            # 1 = summary, 2 = first asset (fail), 3 = second asset
            if state["channel_posts"] == 2:
                raise PermissionDeniedError("asset post denied")
        return original_post(channel_id, text=text, blocks=blocks, thread_ts=thread_ts)

    fake_slack.post_message = _post  # type: ignore[method-assign]
    result = executor.execute(batch_id)
    assert len(fake_slack.asset_posts) == 1
    assert result.status is BatchStatus.FAILED
    statuses = sorted(op.status.value for op in repositories.operations.get_for_batch(batch_id) if op.kind is OperationKind.POST_ASSET)
    assert OperationStatus.FAILED.value in statuses
    assert OperationStatus.SUCCEEDED.value in statuses
