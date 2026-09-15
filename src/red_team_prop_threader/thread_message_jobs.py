"""drain ReviewPrep thread_message inbox jobs without minting."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
import logging

from red_team_prop_threader.cl_jobs import parse_job, list_inbox, stamp_sent, move_to_done, write_failed


if TYPE_CHECKING:
    from pathlib import Path

    from red_team_prop_threader.cl_jobs import ThreadMessageJob
    from red_team_prop_threader.slack_gateway import SlackGateway


__all__ = ("drain_thread_message_inbox", "process_thread_message_job")

_LOG = logging.getLogger(__name__)

_UNSUPPORTED_JOB = "Unsupported job; send Thread Message"
_MISSING_THREAD = "Missing Slack thread"


def process_thread_message_job(job: ThreadMessageJob, *, inbox: Path, slack: SlackGateway, jobs_root: Path, job_json_path: Path | None = None) -> None:
    """Reply in the existing spoke thread, then upload images in order.

    Never mints. Blank spoke ids fail without posting. A missing image file
    fails without stamping sent.

    Args:
        job: parsed thread_message job.
        inbox: slack_jobs/inbox directory containing JSON and image copies.
        slack: slack gateway used for post_message and upload_file.
        jobs_root: ReviewPrep external links root (parent of slack_jobs/).
        job_json_path: optional inbox JSON path; defaults to ``{job_id}.json``.

    Returns:
        None: this function writes failed/sent stamps and moves files as side effects.
    """
    json_path = job_json_path if job_json_path is not None else inbox / f"{job.job_id}.json"
    asset_key = str(job.asset_id)

    if not job.spoke_channel_id.strip() or not job.spoke_thread_ts.strip():
        write_failed(jobs_root, job.job_id, asset_key, _MISSING_THREAD)
        move_to_done(jobs_root, json_path)
        return

    image_paths: list[Path] = []
    for name in job.image_filenames:
        path = inbox / name
        if not path.is_file():
            write_failed(jobs_root, job.job_id, asset_key, f"Missing image file: {name}")
            move_to_done(jobs_root, json_path)
            return
        image_paths.append(path)

    try:
        if job.body.strip():
            slack.post_message(job.spoke_channel_id, text=job.body, thread_ts=job.spoke_thread_ts)
        for path in image_paths:
            slack.upload_file(job.spoke_channel_id, file_path=path, thread_ts=job.spoke_thread_ts)
    except Exception as exc:
        _LOG.warning("thread_message job %s failed: %s", job.job_id, exc)
        write_failed(jobs_root, job.job_id, asset_key, str(exc))
        move_to_done(jobs_root, json_path)
        return

    stamp_sent(jobs_root, job.asset_id, job.job_id)
    move_to_done(jobs_root, json_path)


def drain_thread_message_inbox(jobs_root: Path, slack: SlackGateway) -> None:
    """Process each inbox JSON as thread_message, or fail unsupported jobs.

    Args:
        jobs_root: ReviewPrep external links root (parent of slack_jobs/).
        slack: slack gateway used for replies and uploads.

    Returns:
        None: each inbox JSON is posted, failed, or moved as a side effect.
    """
    inbox = jobs_root / "slack_jobs" / "inbox"
    for job_path in list_inbox(jobs_root):
        job = parse_job(job_path)
        if job is None:
            job_id, asset_id = _ids_from_job_file(job_path)
            write_failed(jobs_root, job_id, asset_id, _UNSUPPORTED_JOB)
            move_to_done(jobs_root, job_path)
            continue
        process_thread_message_job(job, inbox=inbox, slack=slack, jobs_root=jobs_root, job_json_path=job_path)


def _ids_from_job_file(path: Path) -> tuple[str, str]:
    """Read job_id and asset_id from a job file for failed.json.

    Args:
        path: inbox JSON path.

    Returns:
        tuple[str, str]: job_id and asset_id strings; stem and empty on failure.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return path.stem, ""
    if not isinstance(raw, dict):
        return path.stem, ""
    job_id = raw.get("job_id")
    asset_id = raw.get("asset_id")
    job_id_str = job_id.strip() if isinstance(job_id, str) and job_id.strip() else path.stem
    asset_id_str = str(asset_id) if asset_id is not None else ""
    return job_id_str, asset_id_str
