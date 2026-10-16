"""drain ReviewPrep inbox jobs: thread_message replies and mint_group routing."""

from __future__ import annotations

import re
import json
from typing import TYPE_CHECKING, Any
import hashlib
import logging
from datetime import datetime, timezone

from red_team_prop_threader._errors import ExternalServiceError
from red_team_prop_threader.cl_jobs import parse_job, list_inbox, stamp_sent, move_to_done, sent_has_job, write_failed, is_mint_group_file, parse_mint_group_job


if TYPE_CHECKING:
    from pathlib import Path
    from collections.abc import Callable

    from red_team_prop_threader.cl_jobs import MintGroupJob, ThreadMessageJob
    from red_team_prop_threader.slack_gateway import SlackGateway


__all__ = ("drain_thread_message_inbox", "process_thread_message_job")

_LOG = logging.getLogger(__name__)

_UNSUPPORTED_JOB = "Unsupported job; send Thread Message"
_INVALID_MINT_GROUP = "Invalid mint_group job"
_MISSING_THREAD = "Missing Slack thread"
# do not match emails (foo@bar.com) or existing <@U…> tokens
_HANDLE_RE = re.compile(r"(?<![<A-Za-z0-9._])@([A-Za-z0-9._-]+)")
_SPECIAL_MENTIONS = {"here": "<!here>", "channel": "<!channel>", "everyone": "<!everyone>"}


def process_thread_message_job(job: ThreadMessageJob, *, inbox: Path, slack: SlackGateway, jobs_root: Path, job_json_path: Path | None = None) -> None:
    """Reply in the existing spoke thread as one Slack post.

    Text plus images use a single files_upload_v2 with initial_comment.
    @username tokens are rewritten to <@U…> for channel members. Never mints.

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

    if sent_has_job(jobs_root, job.asset_id, job.job_id):
        _LOG.warning("suppressing already-sent thread_message job %s", job.job_id)
        move_to_done(jobs_root, json_path)
        return

    try:
        receipt_path, claimed = _claim_delivery(job, image_paths=image_paths, jobs_root=jobs_root)
    except OSError as exc:
        _LOG.warning("could not claim thread_message job %s: %s", job.job_id, exc)
        write_failed(jobs_root, job.job_id, asset_key, f"Could not create delivery guard: {exc}")
        move_to_done(jobs_root, json_path)
        return
    if not claimed:
        _LOG.warning("suppressing duplicate thread_message job %s", job.job_id)
        status = _receipt_status(receipt_path)
        if status != "sent":
            write_failed(jobs_root, job.job_id, asset_key, f"Duplicate suppressed; prior delivery status is {status}")
        move_to_done(jobs_root, json_path)
        return

    try:
        body = _link_user_mentions(job.body, slack=slack, channel_id=job.spoke_channel_id)
        if image_paths:
            comment = body.strip() or None
            slack.upload_files(job.spoke_channel_id, file_paths=image_paths, thread_ts=job.spoke_thread_ts, initial_comment=comment)
        elif body.strip():
            slack.post_message(job.spoke_channel_id, text=body, thread_ts=job.spoke_thread_ts)
    except Exception as exc:
        _LOG.warning("thread_message job %s failed: %s", job.job_id, exc)
        _finish_delivery(receipt_path, status="failed", error=str(exc))
        write_failed(jobs_root, job.job_id, asset_key, str(exc))
        move_to_done(jobs_root, json_path)
        return

    _finish_delivery(receipt_path, status="sent")
    try:
        stamp_sent(jobs_root, job.asset_id, job.job_id)
    except OSError:
        _LOG.exception("thread_message job %s posted but sent.json was not updated", job.job_id)
    move_to_done(jobs_root, json_path)


def drain_thread_message_inbox(jobs_root: Path, slack: SlackGateway, *, mint_handler: Callable[[Path, MintGroupJob], None] | None = None) -> None:
    """Process each inbox JSON: thread_message replies, mint_group via handler, else fail.

    Args:
        jobs_root: ReviewPrep external links root (parent of slack_jobs/).
        slack: slack gateway used for replies and uploads.
        mint_handler: called for mint_group jobs; when None they stay in the inbox.

    Returns:
        None: each inbox JSON is posted, failed, or moved as a side effect.
    """
    inbox = jobs_root / "slack_jobs" / "inbox"
    for job_path in list_inbox(jobs_root):
        if is_mint_group_file(job_path):
            if mint_handler is None:
                _LOG.info("leaving mint_group job %s for a worker with mint support", job_path.name)
                continue
            mint_job = parse_mint_group_job(job_path)
            if mint_job is None:
                job_id, _asset_id = _ids_from_job_file(job_path)
                write_failed(jobs_root, job_id, "", _INVALID_MINT_GROUP)
                move_to_done(jobs_root, job_path)
                continue
            mint_handler(job_path, mint_job)
            continue
        job = parse_job(job_path)
        if job is None:
            job_id, asset_id = _ids_from_job_file(job_path)
            write_failed(jobs_root, job_id, asset_id, _UNSUPPORTED_JOB)
            move_to_done(jobs_root, job_path)
            continue
        process_thread_message_job(job, inbox=inbox, slack=slack, jobs_root=jobs_root, job_json_path=job_path)


def _link_user_mentions(text: str, *, slack: SlackGateway, channel_id: str) -> str:
    """Rewrite @username tokens to <@U…> using channel member names.

    Unmatched handles are left as typed. Member lookup failures leave the
    original text so the job can still post.

    Args:
        text: ReviewPrep message body.
        slack: slack gateway for members and users.info.
        channel_id: spoke channel whose members can be mentioned.

    Returns:
        str: body with Slack mention tokens where a member handle matched.
    """
    if "@" not in text:
        return text
    try:
        members = slack.get_conversation_members(channel_id)
    except ExternalServiceError:
        _LOG.warning("could not list members for %s; leaving @handles as typed", channel_id)
        return text

    by_name: dict[str, str] = {}
    info_cache: dict[str, dict[str, Any]] = {}
    for member_id in members:
        if member_id in info_cache:
            info = info_cache[member_id]
        else:
            try:
                info = slack.get_user_info(member_id)
            except ExternalServiceError:
                info = {}
            info_cache[member_id] = info
        name = str(info.get("name") or "").strip().lower()
        if name:
            by_name.setdefault(name, member_id)
        profile = info.get("profile") if isinstance(info.get("profile"), dict) else {}
        if isinstance(profile, dict):
            for key in ("display_name", "display_name_normalized"):
                display = str(profile.get(key) or "").strip().lower()
                if display:
                    by_name.setdefault(display, member_id)

    def _replace(match: re.Match[str]) -> str:
        handle = match.group(1)
        special = _SPECIAL_MENTIONS.get(handle.lower())
        if special is not None:
            return special
        user_id = by_name.get(handle.lower())
        if user_id:
            return f"<@{user_id}>"
        return match.group(0)

    return _HANDLE_RE.sub(_replace, text)


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


def _claim_delivery(job: ThreadMessageJob, *, image_paths: list[Path], jobs_root: Path) -> tuple[Path, bool]:
    """Atomically claim a message fingerprint before making a Slack write.

    A retained claim means an uncertain delivery is never retried. This gives
    thread messages at-most-once semantics across duplicate confirms, multiple
    workers, and process crashes after Slack accepted a request.
    """
    image_digests = [_sha256_file(path) for path in image_paths]
    fingerprint_payload = {"version": 1, "channel_id": job.spoke_channel_id, "thread_ts": job.spoke_thread_ts, "body": job.body, "images": image_digests}
    encoded = json.dumps(fingerprint_payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()
    receipt_dir = jobs_root / "slack_jobs" / "delivery_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{fingerprint}.json"
    receipt = {
        "fingerprint": fingerprint,
        "job_id": job.job_id,
        "asset_id": job.asset_id,
        "channel_id": job.spoke_channel_id,
        "thread_ts": job.spoke_thread_ts,
        "status": "claimed",
        "claimed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with receipt_path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2)
    except FileExistsError:
        return receipt_path, False
    return receipt_path, True


def _finish_delivery(receipt_path: Path, *, status: str, error: str | None = None) -> None:
    """Update an existing delivery claim without ever removing the guard."""
    try:
        raw = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _LOG.exception("could not read delivery receipt %s", receipt_path)
        return
    if not isinstance(raw, dict):
        _LOG.error("delivery receipt %s is not a JSON object", receipt_path)
        return
    receipt = raw
    receipt["status"] = status
    receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
    if error is not None:
        receipt["error"] = error
    tmp = receipt_path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        tmp.replace(receipt_path)
    except OSError:
        _LOG.exception("could not update delivery receipt %s", receipt_path)


def _receipt_status(receipt_path: Path) -> str:
    """Read a receipt status, treating unreadable receipts as unknown."""
    try:
        raw = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "unknown"
    if not isinstance(raw, dict):
        return "unknown"
    status = raw.get("status")
    return status if isinstance(status, str) and status else "unknown"


def _sha256_file(path: Path) -> str:
    """Return a content digest without loading a ReviewPrep image into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
