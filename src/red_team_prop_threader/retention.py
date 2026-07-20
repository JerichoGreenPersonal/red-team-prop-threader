"""expiry cleanup for drafts and detailed batch payloads."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from red_team_prop_threader.db import build_engine, session_scope
from red_team_prop_threader.config import Settings
from red_team_prop_threader.repositories import Repositories


__all__ = ("RetentionResult", "main", "run_retention")

_LOG = logging.getLogger(__name__)
_PAYLOAD_RETENTION_DAYS = 30


@dataclass(frozen=True, slots=True)
class RetentionResult:
    """counts of retention side effects applied in one run."""

    drafts_deleted: int
    payloads_cleared: int


def run_retention(repositories: Repositories, *, now: datetime, payload_retention_days: int = _PAYLOAD_RETENTION_DAYS) -> RetentionResult:
    """Delete expired drafts and clear detailed payloads older than the retention window.

    Message/group/asset identity history is preserved. Cleanup is idempotent.

    Args:
        repositories: transaction-scoped repository bundle.
        now: UTC-aware cleanup timestamp.
        payload_retention_days: age threshold for completed-batch payload redaction.

    Returns:
        RetentionResult: drafts deleted and payloads cleared.

    Raises:
        ValueError: if now is naive.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError(f"now must be a timezone-aware UTC datetime, got {now!r}")

    drafts_deleted = repositories.drafts.delete_expired(now)
    cutoff = now - timedelta(days=payload_retention_days)
    # completed-age purge first; deadline purge covers explicit retention timestamps
    cleared = repositories.batches.purge_completed_payloads(cutoff)
    cleared += repositories.batches.purge_expired_payloads(cutoff)
    return RetentionResult(drafts_deleted=drafts_deleted, payloads_cleared=cleared)


def main() -> None:
    """CLI entry point for one retention pass."""
    settings = Settings.from_env()
    engine = build_engine(settings.database_url)
    now = datetime.now(timezone.utc)
    with session_scope(engine) as session:
        result = run_retention(Repositories.from_session(session), now=now)
    _LOG.info("retention complete: drafts_deleted=%s payloads_cleared=%s", result.drafts_deleted, result.payloads_cleared)
