from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
import logging
from datetime import datetime, timezone
import contextlib
from dataclasses import dataclass

from red_team_prop_threader._errors import NotFoundError, ExternalServiceError


if TYPE_CHECKING:
    from pathlib import Path
    from collections.abc import Sequence

    from red_team_prop_threader.slack_gateway import SlackGateway


_LOG = logging.getLogger(__name__)


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
    additional_stakeholders: list[str] | None = None
    spoke_channel_id: str | None = None
    spoke_thread_ts: str | None = None


def parse_job(path: Path) -> SlackClJob | None:
    """Parse a job JSON file into a SlackClJob object."""
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
        return None
    if not isinstance(asset_id, str) or not asset_id.strip():
        return None

    cls_raw = data.get("cls", [])
    cls = tuple(cls_raw) if isinstance(cls_raw, list) else ()

    return SlackClJob(
        job_id=job_id.strip(),
        asset_id=asset_id.strip(),
        version_id=data.get("version_id"),
        season_id=data.get("season_id"),
        cls=cls,
        body=data.get("body"),
        template_id=data.get("template_id"),
        image_filename=data.get("image_filename"),
        channel=data.get("channel"),
        group_title=data.get("group_title"),
        creative_stakeholder=data.get("creative_stakeholder"),
        additional_stakeholders=data.get("additional_stakeholders"),
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
    cl_str = str(cl)
    asset_ids = data.get(cl_str, [])
    if isinstance(asset_ids, list):
        return asset_id in asset_ids
    return False


def stamp_sent(root: Path, asset_id: str, cls: Sequence[int]) -> None:
    """Record the given asset_id as sent for the specified cls."""
    sent_path = root / "slack_jobs" / "sent.json"
    sent_path.parent.mkdir(parents=True, exist_ok=True)
    
    def _read_and_patch() -> None:
        data: dict[str, list[str]] = {}
        if sent_path.is_file():
            try:
                raw = json.loads(sent_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except (json.JSONDecodeError, OSError):
                pass
        
        for cl in cls:
            cl_str = str(cl)
            if cl_str not in data:
                data[cl_str] = []
            if asset_id not in data[cl_str]:
                data[cl_str].append(asset_id)
        
        tmp = sent_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(sent_path)

    try:
        _read_and_patch()
    except OSError:
        _read_and_patch()


def write_failed(root: Path, job_id: str, asset_id: str, error: str) -> None:
    """Append a failure record to failed.json."""
    failed_path = root / "slack_jobs" / "failed.json"
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    
    entry = {
        "job_id": job_id,
        "asset_id": asset_id,
        "error": error,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    line = json.dumps(entry) + "\n"
    
    with failed_path.open("a", encoding="utf-8") as f:
        f.write(line)


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
            kwargs: dict[str, Any] = {
                "types": "public_channel,private_channel",
                "exclude_archived": True,
                "limit": 200,
            }
            if cursor:
                kwargs["cursor"] = cursor
            
            try:
                response = gateway._call("conversations_list", **kwargs)
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
    """Move a processed job JSON and its associated image to the done directory."""
    done_dir = root / "slack_jobs" / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    
    if not job_json_path.is_file():
        return

    try:
        data = json.loads(job_json_path.read_text(encoding="utf-8"))
        job_id = data.get("job_id")
        image_filename = data.get("image_filename")
    except (json.JSONDecodeError, OSError):
        return

    target_json = done_dir / job_json_path.name
    with contextlib.suppress(OSError):
        job_json_path.replace(target_json)

    if isinstance(image_filename, str) and image_filename:
        image_path = job_json_path.parent / image_filename
        if image_path.is_file():
            with contextlib.suppress(OSError):
                image_path.replace(done_dir / image_filename)
    elif isinstance(job_id, str) and job_id:
        for suffix in (".jpg", ".png"):
            image_path = job_json_path.parent / f"{job_id}{suffix}"
            if image_path.is_file():
                with contextlib.suppress(OSError):
                    image_path.replace(done_dir / f"{job_id}{suffix}")
