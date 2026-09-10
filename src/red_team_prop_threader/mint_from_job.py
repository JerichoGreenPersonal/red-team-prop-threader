"""process jobs from the inbox."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
import logging

from red_team_prop_threader.spokes import occupied_asset_ids
from red_team_prop_threader._errors import ExternalServiceError, RetryableExternalServiceError
from red_team_prop_threader.cl_jobs import sent_has, parse_job, list_inbox, stamp_sent, move_to_done, write_failed


if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.engine import Engine

    from red_team_prop_threader.cl_jobs import SlackClJob
    from red_team_prop_threader.slack_gateway import SlackGateway


__all__ = ("process_cl_jobs", "process_job", "reply_already_posted")

_LOG = logging.getLogger(__name__)


def reply_already_posted(gateway: SlackGateway, channel_id: str, thread_ts: str, body: str) -> bool:
    """Check if a reply with exactly the given body already exists."""
    if not body:
        return False
    try:
        resp = gateway._call("conversations_replies", channel=channel_id, ts=thread_ts)
        messages = resp.get("messages")
        if isinstance(messages, list):
            for msg in messages:
                if isinstance(msg, dict) and msg.get("text") == body:
                    return True
    except (ExternalServiceError, RetryableExternalServiceError):
        pass
    return False


def _find_spoke_in_season(season_root: Path, season_id: str, asset_id: str) -> dict[str, str] | None:
    path = season_root / "slack_threads" / f"{season_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        assets = data.get("assets", {})
        if isinstance(assets, dict):
            spoke = assets.get(str(int(asset_id)))
            if isinstance(spoke, dict):
                return spoke
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    return None


def process_job(job_path: Path, job: SlackClJob, *, slack: SlackGateway, season_root: Path, engine: Engine | None = None) -> None:
    """Process a single SlackClJob."""
    # 1. If all cls already sent -> move to done, return
    if job.cls and all(sent_has(season_root, job.asset_id, cl) for cl in job.cls):
        move_to_done(season_root, job_path)
        return

    channel_id = job.spoke_channel_id
    thread_ts = job.spoke_thread_ts

    try:
        asset_int = int(job.asset_id)
    except ValueError:
        write_failed(season_root, job.job_id, job.asset_id, "invalid asset_id")
        return

    # 2. Skip mint when job spoke set, or in season JSON
    needs_mint = True
    occupied = occupied_asset_ids(season_root)

    if channel_id and thread_ts:
        needs_mint = False
    elif asset_int in occupied and job.season_id:
        spoke = _find_spoke_in_season(season_root, job.season_id, job.asset_id)
        if spoke and spoke.get("channel_id") and spoke.get("thread_ts"):
            channel_id = spoke["channel_id"]
            thread_ts = spoke["thread_ts"]
            needs_mint = False

    if needs_mint:
        # TODO(@jgreen2): Postgres Minting (as per brief: implement skip-mint path first)
        # We need a fallback if mint-into-existing-group requires too much logic, but
        # test_mint_from_job will probably expect something. We will handle later if needed.
        write_failed(season_root, job.job_id, job.asset_id, "Minting not yet implemented")
        return

    if not channel_id or not thread_ts:
        write_failed(season_root, job.job_id, job.asset_id, "missing channel or thread")
        return

    try:
        body = job.body or ""
        
        # 3. reply_already_posted
        if body and not reply_already_posted(slack, channel_id, thread_ts, body):
            slack.post_message(channel_id, text=body, thread_ts=thread_ts)

        # 5. upload_file
        if job.image_filename:
            image_path = job_path.parent / job.image_filename
            if image_path.is_file():
                slack.upload_file(channel_id, file_path=image_path, thread_ts=thread_ts)

        # 6. stamp_sent
        if job.cls:
            stamp_sent(season_root, job.asset_id, job.cls)
        move_to_done(season_root, job_path)

    except (ExternalServiceError, RetryableExternalServiceError) as e:
        # 4 & 7. Write failed, do not stamp sent, leave inbox file
        write_failed(season_root, job.job_id, job.asset_id, str(e))


def process_cl_jobs(share_root: Path | str, slack: SlackGateway, *, engine: Engine | None = None) -> None:
    """Process all valid jobs in the inbox."""
    from pathlib import Path
    root = Path(share_root)
    for job_path in list_inbox(root):
        job = parse_job(job_path)
        if job is None:
            continue
        process_job(job_path, job, slack=slack, season_root=root, engine=engine)
