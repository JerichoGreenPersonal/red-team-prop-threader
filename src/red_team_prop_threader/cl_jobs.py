"""inbox job files under ReviewPrep slack_jobs/."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
import logging
from datetime import datetime, timezone
import contextlib
from dataclasses import dataclass

from red_team_prop_threader._errors import NotFoundError, ExternalServiceError, RetryableExternalServiceError


if TYPE_CHECKING:
    from pathlib import Path
    from collections.abc import Sequence

    from red_team_prop_threader.slack_gateway import SlackGateway


__all__ = (
    "SlackClJob",
    "ThreadMessageJob",
    "list_inbox",
    "move_to_done",
    "parse_cl_job",
    "parse_job",
    "resolve_channel",
    "sent_has",
    "stamp_sent",
    "stamp_sent_cls",
    "write_failed",
)

_LOG = logging.getLogger(__name__)

_THREAD_MESSAGE_KIND = "thread_message"


@dataclass(frozen=True, slots=True)
class ThreadMessageJob:
    """ReviewPrep thread_message inbox job.

    Attributes:
        job_id: ReviewPrep job id.
        asset_id: ShotGrid asset entity id.
        body: reply text; may be empty when images are present.
        image_filenames: image copies in the same folder as the JSON.
        spoke_channel_id: existing spoke channel id.
        spoke_thread_ts: existing spoke thread timestamp.
    """

    job_id: str
    asset_id: int
    body: str
    image_filenames: tuple[str, ...]
    spoke_channel_id: str
    spoke_thread_ts: str


@dataclass(frozen=True)
class SlackClJob:
    """Represents a job payload loaded from the inbox."""

    job_id: str
    asset_id: str
    version_id: str | None = None
    season_id: str | None = None
    cls: tuple[Any, ...] = ()
    body: str | None = None
    template_id: str | None = None
    image_filename: str | None = None
    channel: str | None = None
    group_title: str | None = None
    creative_stakeholder: str | None = None
    additional_stakeholders: tuple[str, ...] | None = None
    ic_poc: str | None = None
    additional_ics: tuple[str, ...] | None = None
    spoke_channel_id: str | None = None
    spoke_thread_ts: str | None = None


def parse_job(path: Path) -> ThreadMessageJob | None:
    """Parse a thread_message inbox JSON file.

    Args:
        path: path to a job JSON file.

    Returns:
        ThreadMessageJob | None: parsed job, or None when kind is missing or not thread_message.
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or data.get("kind") != _THREAD_MESSAGE_KIND:
        return None

    job_id = data.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        _LOG.warning("skipping unparseable job %s: invalid job_id", path.name)
        return None
    try:
        asset_id = int(data.get("asset_id"))
    except (TypeError, ValueError):
        _LOG.warning("skipping unparseable job %s: invalid asset_id", path.name)
        return None

    body_raw = data.get("body")
    body = body_raw if isinstance(body_raw, str) else ""
    images_raw = data.get("images")
    image_filenames: list[str] = []
    if isinstance(images_raw, list):
        for item in images_raw:
            if isinstance(item, str) and item.strip():
                image_filenames.append(item.strip())

    spoke_channel_id = data.get("spoke_channel_id")
    spoke_thread_ts = data.get("spoke_thread_ts")
    return ThreadMessageJob(
        job_id=job_id.strip(),
        asset_id=asset_id,
        body=body,
        image_filenames=tuple(image_filenames),
        spoke_channel_id=spoke_channel_id.strip() if isinstance(spoke_channel_id, str) else "",
        spoke_thread_ts=spoke_thread_ts.strip() if isinstance(spoke_thread_ts, str) else "",
    )


def parse_cl_job(path: Path) -> SlackClJob | None:
    """Parse a legacy Post CL job JSON file into a SlackClJob object."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    job_id = data.get("job_id")
    asset_id = data.get("asset_id")
    if not isinstance(job_id, str) or not job_id.strip():
        _LOG.warning("skipping unparseable job %s: invalid job_id", path.name)
        return None
    try:
        asset_id_str = str(int(asset_id))
    except (ValueError, TypeError):
        if isinstance(asset_id, str) and asset_id.strip():
            asset_id_str = asset_id.strip()
        else:
            _LOG.warning("skipping unparseable job %s: invalid asset_id", path.name)
            return None

    cls_raw = data.get("cls", [])
    parsed_cls = []
    if isinstance(cls_raw, list):
        for c in cls_raw:
            if isinstance(c, dict) and "number" in c:
                with contextlib.suppress(ValueError, TypeError):
                    parsed_cls.append(int(c["number"]))
            else:
                with contextlib.suppress(ValueError, TypeError):
                    parsed_cls.append(int(c))
    cls = tuple(parsed_cls)

    stakeholders_raw = data.get("additional_stakeholders")
    additional_stakeholders = tuple(str(item) for item in stakeholders_raw) if isinstance(stakeholders_raw, list) else None
    ics_raw = data.get("additional_ics")
    additional_ics = tuple(str(item) for item in ics_raw) if isinstance(ics_raw, list) else None

    return SlackClJob(
        job_id=job_id.strip(),
        asset_id=asset_id_str,
        version_id=data.get("version_id"),
        season_id=data.get("season_id"),
        cls=cls,
        body=data.get("body"),
        template_id=data.get("template_id"),
        image_filename=data.get("image_filename"),
        channel=data.get("channel"),
        group_title=data.get("group_title"),
        creative_stakeholder=data.get("creative_stakeholder") if isinstance(data.get("creative_stakeholder"), str) else None,
        additional_stakeholders=additional_stakeholders,
        ic_poc=data.get("ic_poc") if isinstance(data.get("ic_poc"), str) else None,
        additional_ics=additional_ics,
        spoke_channel_id=data.get("spoke_channel_id"),
        spoke_thread_ts=data.get("spoke_thread_ts"),
    )


def list_inbox(root: Path) -> tuple[Path, ...]:
    """List valid job JSON files in the inbox directory."""
    inbox = root / "slack_jobs" / "inbox"
    if not inbox.is_dir():
        return ()
    paths = [p for p in inbox.glob("*.json") if not p.name.startswith(".tmp")]
    return tuple(sorted(paths))


def sent_has(root: Path, asset_id: str, cl: int) -> bool:
    """Check if the given asset_id is marked as sent for the specified cl."""
    sent_path = root / "slack_jobs" / "sent.json"
    if not sent_path.is_file():
        return False
    try:
        data = json.loads(sent_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False

    asset_entry = data.get(asset_id, [])
    if isinstance(asset_entry, list):
        return str(cl) in asset_entry
    return False


def _append_sent(root: Path, asset_key: str, values: Sequence[str]) -> None:
    """Append unique string values under sent.json[asset_key]."""
    sent_path = root / "slack_jobs" / "sent.json"
    sent_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_and_patch() -> None:
        data: dict[str, list[str]] = {}
        if sent_path.is_file():
            try:
                raw = json.loads(sent_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except json.JSONDecodeError:
                pass

        if asset_key not in data:
            data[asset_key] = []
        for value in values:
            if value not in data[asset_key]:
                data[asset_key].append(value)

        tmp = sent_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(sent_path)

    try:
        _read_and_patch()
    except OSError:
        _read_and_patch()


def stamp_sent(root: Path, asset_id: int, job_id: str) -> None:
    """Append this job_id under sent.json[str(asset_id)].

    Args:
        root: ReviewPrep external links root.
        asset_id: ShotGrid asset entity id.
        job_id: ReviewPrep thread_message job id.
    """
    _append_sent(root, str(asset_id), (job_id,))


def stamp_sent_cls(root: Path, asset_id: str, cls: Sequence[int]) -> None:
    """Record the given asset_id as sent for the specified cls."""
    _append_sent(root, asset_id, tuple(str(c) for c in cls))


def write_failed(root: Path, job_id: str, asset_id: str, error: str) -> None:
    """Append a failure record to failed.json."""
    failed_path = root / "slack_jobs" / "failed.json"
    failed_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {"job_id": job_id, "asset_id": asset_id, "error": error, "at": datetime.now(timezone.utc).isoformat()}

    data = []
    if failed_path.is_file():
        try:
            raw = json.loads(failed_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                data = raw
        except (json.JSONDecodeError, OSError):
            pass

    replaced = False
    for i, existing in enumerate(data):
        if isinstance(existing, dict) and existing.get("job_id") == job_id:
            data[i] = entry
            replaced = True
            break
    if not replaced:
        data.append(entry)

    tmp = failed_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(failed_path)


def resolve_channel(gateway: SlackGateway, raw: str) -> str:
    """Resolve a channel identifier or name to a channel ID."""
    channel = raw.strip()
    if not channel:
        raise NotFoundError("channel name is empty")

    if (channel.startswith("C") or channel.startswith("G")) and len(channel) > 2 and channel[1:].isalnum():
        return channel

    if channel.startswith("#"):
        name_to_find = channel[1:].lower()
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"types": "public_channel,private_channel", "exclude_archived": True, "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor

            try:
                response = gateway._call("conversations_list", **kwargs)
            except RetryableExternalServiceError:
                raise
            except ExternalServiceError as e:
                raise NotFoundError(f"failed to list channels: {e}") from e

            channels = response.get("channels") or []
            if not isinstance(channels, list):
                break

            for ch in channels:
                if isinstance(ch, dict) and ch.get("name", "").lower() == name_to_find:
                    ch_id = ch.get("id")
                    if isinstance(ch_id, str):
                        return ch_id

            metadata = response.get("response_metadata") or {}
            next_cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else None
            if not next_cursor:
                break
            cursor = str(next_cursor)

        raise NotFoundError(f"channel {channel} not found")

    raise NotFoundError(f"invalid channel format: {channel}")


def move_to_done(root: Path, job_json_path: Path) -> None:
    """Move a job JSON plus image copies and leftover sidecars to done/.

    Args:
        root: ReviewPrep external links root.
        job_json_path: inbox JSON path for this job.
    """
    done_dir = root / "slack_jobs" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)

    if not job_json_path.is_file():
        return

    inbox = job_json_path.parent
    data: dict[str, Any] = {}
    try:
        raw = json.loads(job_json_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data = raw
    except (json.JSONDecodeError, OSError):
        data = {}

    job_id = data.get("job_id")
    filenames: list[str] = []
    image_filename = data.get("image_filename")
    if isinstance(image_filename, str) and image_filename.strip():
        filenames.append(image_filename.strip())
    images = data.get("images")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, str) and item.strip():
                filenames.append(item.strip())

    with contextlib.suppress(OSError):
        job_json_path.replace(done_dir / job_json_path.name)

    moved: set[str] = set()
    for name in filenames:
        if name in moved:
            continue
        moved.add(name)
        src = inbox / name
        if src.is_file():
            with contextlib.suppress(OSError):
                src.replace(done_dir / name)

    if isinstance(job_id, str) and job_id.strip():
        for src in inbox.glob(f"{job_id.strip()}*"):
            if not src.is_file() or src.suffix.lower() == ".json":
                continue
            with contextlib.suppress(OSError):
                src.replace(done_dir / src.name)
