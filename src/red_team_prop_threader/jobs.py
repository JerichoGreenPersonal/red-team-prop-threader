"""durable batch operation planning, leased execution, progress, and failed-only retry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from red_team_prop_threader.canvas import IndexedAsset, CanvasService, GroupIndexRequest, DuplicateThreadRequest
from red_team_prop_threader.domain import OperationKind, SupportingLink
from red_team_prop_threader._errors import ExternalServiceError, PermissionDeniedError, RetryableExternalServiceError
from red_team_prop_threader.messages import AssetRootContext, GroupSummaryContext, render_asset_root, render_group_summary
from red_team_prop_threader.repositories import BatchStatus, MessageKind, NewMessageInput, OperationStatus


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from red_team_prop_threader.leases import ChannelLeaseRepository
    from red_team_prop_threader.repositories import BatchRecord, Repositories, OperationRecord


__all__ = ("BatchExecutor", "BatchPlanner", "ExecutionResult")

_LEASE_TTL = timedelta(minutes=10)
_KIND_ORDER = {
    OperationKind.POST_SUMMARY: 0,
    OperationKind.POST_ASSET: 1,
    OperationKind.INDEX_ASSET: 2,
    OperationKind.RETIRE_PRIOR_LATEST: 3,
    OperationKind.FINALIZE_SUMMARY: 4,
}


class Clock(Protocol):
    """minimal clock protocol for job execution."""

    def now(self) -> datetime:
        """Return the current UTC-aware instant."""


class SlackJobsGateway(Protocol):
    """slack methods required by the batch executor."""

    def open_dm(self, user_id: str) -> str:
        """Open a DM channel with the user."""

    def post_message(self, channel_id: str, *, text: str, blocks: list[dict[str, Any]] | None = None, thread_ts: str | None = None) -> dict[str, Any]:
        """Post a channel or DM message."""

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Update an existing message."""

    def get_permalink(self, channel_id: str, message_ts: str) -> str:
        """Resolve a permalink for a posted message."""

    def get_user_info(self, user_id: str) -> dict[str, object]:
        """Fetch user profile information."""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """outcome of executing or retrying one batch."""

    batch_id: str
    status: BatchStatus
    failed_operation: OperationRecord | None


class BatchPlanner:
    """persist deterministic operation plans before side effects begin."""

    def __init__(self, repositories: Repositories) -> None:
        """Bind planner to a repository bundle.

        Args:
            repositories: transaction-scoped repository bundle.
        """
        self._repos = repositories

    def plan(self, batch_id: str, *, now: datetime) -> list[OperationRecord]:
        """Plan summary, per-asset, and finalize operations for a batch.

        Args:
            batch_id: target batch id.
            now: UTC-aware planning timestamp.

        Returns:
            list[OperationRecord]: planned operations in execution order.

        Raises:
            LookupError: if the batch does not exist.
            ValueError: if the batch payload is missing or invalid.
        """
        batch = self._repos.batches.get(batch_id)
        if batch is None:
            raise LookupError(f"batch {batch_id!r} not found")
        payload = batch.payload or {}
        assets = payload.get("assets")
        if not isinstance(assets, list) or not assets:
            raise ValueError("batch payload must include a non-empty assets list")

        planned: list[OperationRecord] = []
        tick = now
        planned.append(
            self._repos.operations.add_planned(
                batch_id=batch_id, kind=OperationKind.POST_SUMMARY, asset_entity_id=0, idempotency_key=f"{batch_id}:post_summary:0", now=tick
            )
        )
        for asset in assets:
            entity_id = int(asset["entity_id"])
            tick = tick + timedelta(microseconds=1)
            planned.append(
                self._repos.operations.add_planned(
                    batch_id=batch_id,
                    kind=OperationKind.POST_ASSET,
                    asset_entity_id=entity_id,
                    idempotency_key=f"{batch_id}:post_asset:{entity_id}",
                    payload={"entity_id": entity_id},
                    now=tick,
                )
            )
            tick = tick + timedelta(microseconds=1)
            planned.append(
                self._repos.operations.add_planned(
                    batch_id=batch_id,
                    kind=OperationKind.INDEX_ASSET,
                    asset_entity_id=entity_id,
                    idempotency_key=f"{batch_id}:index_asset:{entity_id}",
                    payload={"entity_id": entity_id},
                    now=tick,
                )
            )
            tick = tick + timedelta(microseconds=1)
            planned.append(
                self._repos.operations.add_planned(
                    batch_id=batch_id,
                    kind=OperationKind.RETIRE_PRIOR_LATEST,
                    asset_entity_id=entity_id,
                    idempotency_key=f"{batch_id}:retire_prior_latest:{entity_id}",
                    payload={"entity_id": entity_id},
                    now=tick,
                )
            )
        tick = tick + timedelta(microseconds=1)
        planned.append(
            self._repos.operations.add_planned(
                batch_id=batch_id, kind=OperationKind.FINALIZE_SUMMARY, asset_entity_id=0, idempotency_key=f"{batch_id}:finalize_summary:0", now=tick
            )
        )
        return planned


class BatchExecutor:
    """leased executor for durable batch operations with failed-only retry."""

    def __init__(
        self, *, repositories: Repositories, leases: ChannelLeaseRepository, slack: SlackJobsGateway, canvas_slack: Any, clock: Clock, session: Session
    ) -> None:
        """Wire repositories, leases, slack gateways, and clock.

        Args:
            repositories: transaction-scoped repositories.
            leases: channel lease repository.
            slack: messaging gateway for posts/DMs.
            canvas_slack: gateway satisfying CanvasService needs.
            clock: utc clock.
            session: open sqlalchemy session owned by the caller.
        """
        self._repos = repositories
        self._leases = leases
        self._slack = slack
        self._canvas = CanvasService(canvas_slack)
        self._clock = clock
        self._session = session

    def run_once(self) -> ExecutionResult | None:
        """Claim one PENDING batch and execute it.

        Returns:
            ExecutionResult | None: result when work was claimed; otherwise None.
        """
        now = self._clock.now()
        batch = self._repos.batches.claim_next_pending(now=now)
        if batch is None:
            return None
        self._session.flush()
        return self._run_batch(batch, retry_only=False)

    def execute(self, batch_id: str) -> ExecutionResult:
        """Execute all pending operations for a known batch.

        Args:
            batch_id: batch to execute.

        Returns:
            ExecutionResult: terminal batch outcome.

        Raises:
            LookupError: if the batch does not exist.
        """
        batch = self._require_batch(batch_id)
        now = self._clock.now()
        if batch.status is BatchStatus.PENDING:
            self._repos.batches.transition(batch_id, BatchStatus.PENDING, BatchStatus.RUNNING, now=now)
            batch = self._require_batch(batch_id)
        return self._run_batch(batch, retry_only=False)

    def retry_failed(self, batch_id: str) -> ExecutionResult:
        """Requeue FAILED/PENDING operations and resume execution.

        Args:
            batch_id: batch to retry.

        Returns:
            ExecutionResult: terminal batch outcome after retry.

        Raises:
            LookupError: if the batch does not exist.
            ValueError: if the batch is not retryable.
        """
        batch = self._require_batch(batch_id)
        now = self._clock.now()
        if batch.status is BatchStatus.FAILED:
            if not self._repos.batches.transition(batch_id, BatchStatus.FAILED, BatchStatus.RUNNING, now=now):
                raise ValueError(f"batch {batch_id!r} could not be requeued")
            batch = self._require_batch(batch_id)
        elif batch.status is not BatchStatus.RUNNING:
            raise ValueError(f"batch {batch_id!r} is not retryable from status {batch.status!r}")
        self._session.flush()
        return self._run_batch(batch, retry_only=True)

    def _run_batch(self, batch: BatchRecord, *, retry_only: bool) -> ExecutionResult:
        """Execute runnable operations for a batch under the channel lease."""
        now = self._clock.now()
        payload = dict(batch.payload or {})
        lease_token = str(payload.get("lease_token") or "")
        self._renew_lease(batch, lease_token, now)
        self._update_progress(batch, payload, "Creating messages…")

        first_failure: OperationRecord | None = None
        stop_assets = False
        operations = sorted(self._repos.operations.get_for_batch(batch.id), key=lambda op: (op.created_at, _KIND_ORDER[op.kind], op.asset_entity_id))
        for operation in operations:
            if retry_only and operation.status is OperationStatus.SUCCEEDED:
                continue
            if operation.status is OperationStatus.SUCCEEDED:
                continue
            if stop_assets and operation.kind in (
                OperationKind.POST_ASSET,
                OperationKind.INDEX_ASSET,
                OperationKind.RETIRE_PRIOR_LATEST,
                OperationKind.FINALIZE_SUMMARY,
            ):
                continue
            if operation.status is OperationStatus.FAILED and not retry_only:
                # initial execute still skips already-failed ops when re-entered
                continue

            outcome = self._execute_operation(batch, operation, payload)
            self._session.flush()
            if outcome is None:
                continue
            if outcome.status is OperationStatus.FAILED:
                if first_failure is None:
                    first_failure = outcome
                if operation.kind is OperationKind.POST_SUMMARY:
                    stop_assets = True
                    break
                continue
            if operation.kind is OperationKind.INDEX_ASSET:
                self._update_progress(batch, payload, "Updating the canvas…")
            self._renew_lease(batch, str(payload.get("lease_token") or lease_token), self._clock.now())

        batch = self._require_batch(batch.id)
        ops = self._repos.operations.get_for_batch(batch.id)
        any_failed = any(op.status is OperationStatus.FAILED for op in ops)
        terminal = BatchStatus.FAILED if any_failed or stop_assets else BatchStatus.SUCCEEDED
        if batch.status is BatchStatus.RUNNING:
            self._repos.batches.transition(batch.id, BatchStatus.RUNNING, terminal, now=self._clock.now())
        self._release_lease(batch, str(payload.get("lease_token") or lease_token))
        completion = "Complete with failures." if terminal is BatchStatus.FAILED else "Complete."
        self._update_progress(batch, payload, completion, terminal=True)
        self._session.flush()
        failed = first_failure
        if failed is None:
            failed = next((op for op in ops if op.status is OperationStatus.FAILED), None)
        return ExecutionResult(batch_id=batch.id, status=terminal, failed_operation=failed)

    def _execute_operation(self, batch: BatchRecord, operation: OperationRecord, payload: dict[str, Any]) -> OperationRecord | None:
        """Run one operation, persisting success or user-safe failure."""
        now = self._clock.now()
        if operation.status is OperationStatus.FAILED:
            # move failed -> running for retry attempts
            if not self._repos.operations.transition(operation.id, OperationStatus.FAILED, OperationStatus.RUNNING, attempts=operation.attempts + 1, now=now):
                return None
        elif operation.status is OperationStatus.PENDING:
            if not self._repos.operations.transition(operation.id, OperationStatus.PENDING, OperationStatus.RUNNING, attempts=operation.attempts + 1, now=now):
                return None
        elif operation.status is OperationStatus.RUNNING:
            pass
        else:
            return None

        try:
            result = self._dispatch(batch, operation, payload)
        except RetryableExternalServiceError as exc:
            self._repos.operations.transition(
                operation.id, OperationStatus.RUNNING, OperationStatus.FAILED, attempts=operation.attempts + 1, safe_error=str(exc), now=self._clock.now()
            )
            return self._repos.operations.get(operation.id)
        except (PermissionDeniedError, ExternalServiceError, ValueError, LookupError) as exc:
            self._repos.operations.transition(
                operation.id, OperationStatus.RUNNING, OperationStatus.FAILED, attempts=operation.attempts + 1, safe_error=str(exc), now=self._clock.now()
            )
            return self._repos.operations.get(operation.id)

        self._repos.operations.transition(
            operation.id, OperationStatus.RUNNING, OperationStatus.SUCCEEDED, attempts=operation.attempts + 1, result=result, now=self._clock.now()
        )
        return self._repos.operations.get(operation.id)

    def _dispatch(self, batch: BatchRecord, operation: OperationRecord, payload: dict[str, Any]) -> dict[str, Any]:
        """Dispatch one operation kind to its side-effect implementation."""
        if operation.kind is OperationKind.POST_SUMMARY:
            return self._post_summary(batch, payload)
        if operation.kind is OperationKind.POST_ASSET:
            return self._post_asset(batch, operation, payload)
        if operation.kind is OperationKind.INDEX_ASSET:
            return self._index_asset(batch, operation, payload)
        if operation.kind is OperationKind.RETIRE_PRIOR_LATEST:
            return self._retire_prior_latest(batch, operation, payload)
        if operation.kind is OperationKind.FINALIZE_SUMMARY:
            return self._finalize_summary(batch, payload)
        raise ValueError(f"unsupported operation kind {operation.kind!r}")

    def _post_summary(self, batch: BatchRecord, payload: dict[str, Any]) -> dict[str, Any]:
        """Post the group summary message and record it as latest."""
        assets = list(payload.get("assets") or [])
        context = GroupSummaryContext(
            group_title=str(payload["group_title"]),
            animator_id=str(payload["group_animator_id"]),
            additional_ids=tuple(str(item) for item in payload.get("group_additional_ids") or ()),
            links=_links_from_payload(payload.get("group_links")),
            included_asset_count=len(assets),
            processing_status="Creating threads…",
            summary_identity=batch.id,
            canvas_url=None,
        )
        rendered = render_group_summary(context)
        response = self._slack.post_message(batch.channel_id, text=str(rendered["text"]), blocks=_blocks(rendered))
        ts = str(response["ts"])
        permalink = self._slack.get_permalink(batch.channel_id, ts)
        now = self._clock.now()
        self._repos.history.record(
            NewMessageInput(
                workspace_id=batch.workspace_id,
                channel_id=batch.channel_id,
                group_id=batch.group_id,
                batch_id=batch.id,
                kind=MessageKind.GROUP_SUMMARY,
                asset_entity_id=None,
                slack_ts=ts,
                permalink=permalink,
                canvas_metadata={"canvas_id": payload.get("canvas_id")},
                now=now,
            )
        )
        return {"ts": ts, "permalink": permalink}

    def _post_asset(self, batch: BatchRecord, operation: OperationRecord, payload: dict[str, Any]) -> dict[str, Any]:
        """Post one asset root, preserving any prior latest for retirement."""
        asset = _asset_from_payload(payload, operation.asset_entity_id)
        prior = self._repos.history.latest_asset_root(batch.workspace_id, batch.channel_id, operation.asset_entity_id)
        now = self._clock.now()
        created_ts = int(now.timestamp())
        context = AssetRootContext(
            asset_entity_id=operation.asset_entity_id,
            asset_name=str(asset["name"]),
            asset_url=str(asset["url"]),
            group_title=str(payload["group_title"]),
            created_ts=created_ts,
            asset_animator_id=str(asset["animator_id"]),
            asset_additional_ids=tuple(str(item) for item in asset.get("additional_ids") or ()),
            group_animator_display=self._display_name(str(payload["group_animator_id"])),
            group_additional_displays=tuple(self._display_name(str(item)) for item in payload.get("group_additional_ids") or ()),
            group_links=_links_from_payload(payload.get("group_links")),
            asset_links=_links_from_payload(asset.get("links")),
            message_identity=f"{batch.id}:{operation.asset_entity_id}",
            is_latest=True,
        )
        rendered = render_asset_root(context)
        response = self._slack.post_message(batch.channel_id, text=str(rendered["text"]), blocks=_blocks(rendered))
        ts = str(response["ts"])
        permalink = self._slack.get_permalink(batch.channel_id, ts)
        self._repos.history.record(
            NewMessageInput(
                workspace_id=batch.workspace_id,
                channel_id=batch.channel_id,
                group_id=batch.group_id,
                batch_id=batch.id,
                kind=MessageKind.ASSET_ROOT,
                asset_entity_id=operation.asset_entity_id,
                slack_ts=ts,
                permalink=permalink,
                canvas_metadata=None,
                now=now,
            )
        )
        return {
            "ts": ts,
            "permalink": permalink,
            "created_ts": created_ts,
            "prior_ts": prior.slack_ts if prior is not None else None,
            "prior_permalink": prior.permalink if prior is not None else None,
        }

    def _index_asset(self, batch: BatchRecord, operation: OperationRecord, payload: dict[str, Any]) -> dict[str, Any]:
        """Index one posted asset onto the channel canvas."""
        post_op = self._require_succeeded_asset_op(batch.id, OperationKind.POST_ASSET, operation.asset_entity_id)
        post_result = post_op.result or {}
        permalink = str(post_result["permalink"])
        created_ts = int(post_result.get("created_ts") or self._clock.now().timestamp())
        created_at = datetime.fromtimestamp(created_ts, tz=timezone.utc)
        asset = _asset_from_payload(payload, operation.asset_entity_id)
        canvas_id = str(payload["canvas_id"])
        prior_permalink = post_result.get("prior_permalink")
        if prior_permalink:
            result = self._canvas.add_duplicate_thread(
                DuplicateThreadRequest(
                    channel_id=batch.channel_id,
                    canvas_id=canvas_id,
                    group_title=str(payload["group_title"]),
                    entity_id=operation.asset_entity_id,
                    asset_name=str(asset["name"]),
                    asset_url=str(asset["url"]),
                    permalink=permalink,
                    created_at=created_at,
                )
            )
            return {"manual_cleanup_required": result.manual_cleanup_required, "detail": result.detail}

        indexed_assets = self._indexed_assets_for_group(batch, payload)
        request = GroupIndexRequest(
            channel_id=batch.channel_id,
            canvas_id=canvas_id,
            group_title=str(payload["group_title"]),
            animator_display=self._display_name(str(payload["group_animator_id"])),
            additional_displays=tuple(self._display_name(str(item)) for item in payload.get("group_additional_ids") or ()),
            links=_links_from_payload(payload.get("group_links")),
            assets=indexed_assets,
        )
        self._canvas.index_batch(request)
        return {"indexed": True, "entity_id": operation.asset_entity_id}

    def _retire_prior_latest(self, batch: BatchRecord, operation: OperationRecord, payload: dict[str, Any]) -> dict[str, Any]:
        """Remove the Latest marker from the prior bot-authored asset root."""
        post_op = self._require_succeeded_asset_op(batch.id, OperationKind.POST_ASSET, operation.asset_entity_id)
        prior_ts = (post_op.result or {}).get("prior_ts")
        if not prior_ts:
            return {"retired": False}
        asset = _asset_from_payload(payload, operation.asset_entity_id)
        created_ts = int((post_op.result or {}).get("created_ts") or self._clock.now().timestamp())
        # re-render prior root without Latest using stored identity conventions
        context = AssetRootContext(
            asset_entity_id=operation.asset_entity_id,
            asset_name=str(asset["name"]),
            asset_url=str(asset["url"]),
            group_title=str(payload["group_title"]),
            created_ts=created_ts,
            asset_animator_id=str(asset["animator_id"]),
            asset_additional_ids=tuple(str(item) for item in asset.get("additional_ids") or ()),
            group_animator_display=self._display_name(str(payload["group_animator_id"])),
            group_additional_displays=tuple(self._display_name(str(item)) for item in payload.get("group_additional_ids") or ()),
            group_links=_links_from_payload(payload.get("group_links")),
            asset_links=_links_from_payload(asset.get("links")),
            message_identity=f"{batch.id}:{operation.asset_entity_id}:prior",
            is_latest=False,
        )
        rendered = render_asset_root(context)
        self._slack.update_message(batch.channel_id, str(prior_ts), text=str(rendered["text"]), blocks=_blocks(rendered))
        return {"retired": True, "prior_ts": prior_ts}

    def _finalize_summary(self, batch: BatchRecord, payload: dict[str, Any]) -> dict[str, Any]:
        """Update the group summary with completion counts."""
        summary = self._repos.history.latest_group_summary(batch.group_id)
        if summary is None:
            raise LookupError("group summary message is missing")
        ops = self._repos.operations.get_for_batch(batch.id)
        asset_ops = [op for op in ops if op.kind is OperationKind.POST_ASSET]
        completed = sum(1 for op in asset_ops if op.status is OperationStatus.SUCCEEDED)
        failed = sum(1 for op in asset_ops if op.status is OperationStatus.FAILED)
        assets = list(payload.get("assets") or [])
        context = GroupSummaryContext(
            group_title=str(payload["group_title"]),
            animator_id=str(payload["group_animator_id"]),
            additional_ids=tuple(str(item) for item in payload.get("group_additional_ids") or ()),
            links=_links_from_payload(payload.get("group_links")),
            included_asset_count=len(assets),
            processing_status="Complete" if failed == 0 else "Complete with failures",
            summary_identity=batch.id,
            completion_count=completed,
            failure_count=failed,
            canvas_url=None,
        )
        rendered = render_group_summary(context)
        self._slack.update_message(batch.channel_id, summary.slack_ts, text=str(rendered["text"]), blocks=_blocks(rendered))
        return {"completed": completed, "failed": failed}

    def _indexed_assets_for_group(self, batch: BatchRecord, payload: dict[str, Any]) -> tuple[IndexedAsset, ...]:
        """Build canvas index entries for successfully posted assets."""
        entries: list[IndexedAsset] = []
        for asset in payload.get("assets") or []:
            entity_id = int(asset["entity_id"])
            post_op = next(
                (
                    op
                    for op in self._repos.operations.get_for_batch(batch.id)
                    if op.kind is OperationKind.POST_ASSET and op.asset_entity_id == entity_id and op.status is OperationStatus.SUCCEEDED
                ),
                None,
            )
            if post_op is None or not post_op.result:
                continue
            created_ts = int(post_op.result.get("created_ts") or self._clock.now().timestamp())
            entries.append(
                IndexedAsset(
                    entity_id=entity_id,
                    name=str(asset["name"]),
                    asset_url=str(asset["url"]),
                    permalink=str(post_op.result["permalink"]),
                    created_at=datetime.fromtimestamp(created_ts, tz=timezone.utc),
                    is_latest=True,
                )
            )
        return tuple(entries)

    def _require_succeeded_asset_op(self, batch_id: str, kind: OperationKind, entity_id: int) -> OperationRecord:
        """Return a succeeded operation for an asset or raise LookupError."""
        for operation in self._repos.operations.get_for_batch(batch_id):
            if operation.kind is kind and operation.asset_entity_id == entity_id and operation.status is OperationStatus.SUCCEEDED:
                return operation
        raise LookupError(f"missing succeeded {kind.value} operation for entity {entity_id}")

    def _require_batch(self, batch_id: str) -> BatchRecord:
        """Fetch a batch or raise LookupError."""
        batch = self._repos.batches.get(batch_id)
        if batch is None:
            raise LookupError(f"batch {batch_id!r} not found")
        return batch

    def _renew_lease(self, batch: BatchRecord, lease_token: str, now: datetime) -> None:
        """Renew the channel lease when a token is available."""
        if not lease_token:
            return
        result = self._leases.renew(batch.channel_id, batch.submitter_user_id, lease_token, now, _LEASE_TTL, workspace_id=batch.workspace_id)
        if result.acquired and result.token:
            payload = dict(batch.payload or {})
            payload["lease_token"] = result.token
            self._repos.batches.update_payload(batch.id, payload)

    def _release_lease(self, batch: BatchRecord, lease_token: str) -> None:
        """Release the channel lease on terminal success or failure."""
        if not lease_token:
            return
        self._leases.release(batch.channel_id, batch.submitter_user_id, lease_token, workspace_id=batch.workspace_id)

    def _update_progress(self, batch: BatchRecord, payload: dict[str, Any], text: str, *, terminal: bool = False) -> None:
        """Open or update the submitter's private progress DM."""
        del terminal
        progress = dict(payload.get("progress") or {})
        try:
            if "channel_id" not in progress or "ts" not in progress:
                channel_id = self._slack.open_dm(batch.submitter_user_id)
                response = self._slack.post_message(channel_id, text=text)
                progress = {"channel_id": channel_id, "ts": str(response["ts"])}
            else:
                self._slack.update_message(str(progress["channel_id"]), str(progress["ts"]), text=text)
        except ExternalServiceError:
            return
        payload["progress"] = progress
        self._repos.batches.update_payload(batch.id, payload)

    def _display_name(self, user_id: str) -> str:
        """Resolve a non-notifying display name for canvas/root copy."""
        try:
            info = self._slack.get_user_info(user_id)
        except ExternalServiceError:
            return user_id
        profile = info.get("profile") if isinstance(info.get("profile"), dict) else {}
        for key in ("display_name", "real_name"):
            value = profile.get(key) if isinstance(profile, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
        return user_id


def _blocks(rendered: dict[str, object]) -> list[dict[str, Any]]:
    """Extract typed block kit blocks from a renderer payload."""
    blocks = rendered.get("blocks")
    if not isinstance(blocks, list):
        return []
    typed: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict):
            typed.append({str(key): value for key, value in block.items()})
    return typed


def _links_from_payload(raw: Any) -> tuple[SupportingLink, ...]:
    """Convert payload link dicts into SupportingLink values."""
    if not raw:
        return ()
    links: list[SupportingLink] = []
    for item in raw:
        if isinstance(item, SupportingLink):
            links.append(item)
            continue
        if isinstance(item, dict):
            links.append(SupportingLink(label=str(item["label"]), url=str(item["url"])))
    return tuple(links)


def _asset_from_payload(payload: dict[str, Any], entity_id: int) -> dict[str, Any]:
    """Return one asset dict from the batch payload."""
    for asset in payload.get("assets") or []:
        if int(asset["entity_id"]) == entity_id:
            return dict(asset)
    raise LookupError(f"asset entity {entity_id} missing from batch payload")
