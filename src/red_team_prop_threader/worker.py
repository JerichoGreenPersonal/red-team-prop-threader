"""database-backed worker entry point for leased batch execution."""

from __future__ import annotations

import time
import logging
from pathlib import Path
from datetime import datetime, timezone

from red_team_prop_threader.db import build_engine, session_scope
from red_team_prop_threader.jobs import BatchExecutor
from red_team_prop_threader.config import Settings
from red_team_prop_threader.leases import ChannelLeaseRepository
from red_team_prop_threader.repositories import Repositories
from red_team_prop_threader.slack_gateway import SlackGateway
from red_team_prop_threader.thread_message_jobs import drain_thread_message_inbox


__all__ = ("UtcClock", "main", "run_forever")

_LOG = logging.getLogger(__name__)


class UtcClock:
    """system utc clock for worker execution."""

    def now(self) -> datetime:
        """Return the current UTC-aware datetime.

        Returns:
            datetime: timezone-aware UTC instant.
        """
        return datetime.now(timezone.utc)


def run_forever(*, settings: Settings | None = None, once: bool = False) -> None:
    """Poll for PENDING batches and drain thread_message inbox jobs.

    Inbox drain replies in existing spokes and never mints. Laptop stacks
    must stay off while EAV1089717 is live.

    Args:
        settings: optional settings override; loads from the environment when omitted.
        once: when True, claim at most one batch, drain inbox once, and return.
    """
    cfg = settings or Settings.from_env()
    engine = build_engine(cfg.database_url)
    slack = SlackGateway.from_settings(cfg)
    clock = UtcClock()

    while True:
        worked = False
        with session_scope(engine) as session:
            repositories = Repositories.from_session(session)
            leases = ChannelLeaseRepository(session, engine)
            executor = BatchExecutor(repositories=repositories, leases=leases, slack=slack, canvas_slack=slack, clock=clock, session=session)
            result = executor.run_once()
            if result is not None:
                worked = True
                _LOG.info("batch %s finished with status %s", result.batch_id, result.status.value)

        try:
            drain_thread_message_inbox(Path(cfg.reviewprep_external_links_root), slack)
        except Exception:
            _LOG.exception("drain_thread_message_inbox failed")

        if once:
            return
        if not worked:
            time.sleep(cfg.worker_poll_seconds)


def main() -> None:
    """CLI entry point for the prop-threader worker process."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    _LOG.info("prop-threader worker starting")
    run_forever()
