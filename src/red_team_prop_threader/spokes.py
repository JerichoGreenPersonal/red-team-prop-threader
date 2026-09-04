"""parse INDEX Latest / leftover roots and upsert ReviewPrep season JSON."""

from __future__ import annotations

import re
import json
from typing import Any
import logging
from pathlib import Path
from dataclasses import dataclass


__all__ = (
    "SpokeCandidate",
    "canvas_latest_spokes",
    "harvest_lookup_text",
    "history_root_spokes",
    "permalink_from_ts",
    "permalink_parts",
    "upsert_season_spoke",
)

_LOG = logging.getLogger(__name__)

_ASSET_URL_RE = re.compile(r"https://respawn\.shotgunstudio\.com/detail/Asset/(\d+)", re.I)
_PERMALINK_RE = re.compile(r"https://respawn\.slack\.com/archives/([A-Z0-9]+)/p(\d+)", re.I)
_CANVAS_TOKEN_RE = re.compile(
    r"https://respawn\.shotgunstudio\.com/detail/Asset/(\d+)"
    r"|https://respawn\.slack\.com/archives/([A-Z0-9]+)/p(\d+)\)\s*—\s*Latest",
    re.I,
)


@dataclass(frozen=True, slots=True)
class SpokeCandidate:
    """one official slack thread to write into a season file."""

    asset_id: int
    permalink: str
    channel_id: str
    thread_ts: str
    source: str


def permalink_parts(url: str) -> tuple[str, str]:
    """Return ``(channel_id, thread_ts)`` from a slack archive permalink."""
    match = _PERMALINK_RE.search(url or "")
    if match is None:
        return "", ""
    channel_id = match.group(1)
    digits = match.group(2)
    if len(digits) > 6:
        return channel_id, f"{digits[:-6]}.{digits[-6:]}"
    return channel_id, f"0.{digits.rjust(6, '0')}"


def permalink_from_ts(channel_id: str, ts: str) -> str:
    """Build a respawn.slack.com archive permalink from channel id and message ts."""
    left, _, right = str(ts).partition(".")
    frac = (right or "0").ljust(6, "0")[:6]
    seconds = left or "0"
    return f"https://respawn.slack.com/archives/{channel_id}/p{seconds}{frac}"


def harvest_lookup_text(payloads: object) -> str:
    """Concatenate every string field in canvas lookup / files.info payloads."""
    parts: list[str] = []

    def _walk(value: object) -> None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                parts.append(stripped)
            return
        if isinstance(value, dict):
            for item in value.values():
                _walk(item)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                _walk(item)

    _walk(payloads)
    return "\n".join(parts)


def canvas_latest_spokes(markdown: str) -> dict[int, SpokeCandidate]:
    """Parse INDEX markdown: Latest permalink after each ShotGrid asset url."""
    spokes: dict[int, SpokeCandidate] = {}
    current_asset: int | None = None
    for match in _CANVAS_TOKEN_RE.finditer(markdown or ""):
        asset_raw = match.group(1)
        if asset_raw:
            current_asset = int(asset_raw)
            continue
        if current_asset is None:
            continue
        channel_id = match.group(2)
        digits = match.group(3)
        permalink = f"https://respawn.slack.com/archives/{channel_id}/p{digits}"
        channel, thread_ts = permalink_parts(permalink)
        spokes[current_asset] = SpokeCandidate(
            asset_id=current_asset,
            permalink=permalink,
            channel_id=channel,
            thread_ts=thread_ts,
            source="canvas",
        )
    return spokes


def history_root_spokes(messages: object, *, channel_id: str) -> dict[int, SpokeCandidate]:
    """Keep the newest root message per asset id; replies do not count."""
    best: dict[int, tuple[float, SpokeCandidate]] = {}
    if not isinstance(messages, (list, tuple)):
        return {}
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        ts = str(raw.get("ts") or "").strip()
        if not ts:
            continue
        thread_ts = str(raw.get("thread_ts") or "").strip()
        if thread_ts and thread_ts != ts:
            continue
        text = str(raw.get("text") or "")
        asset_match = _ASSET_URL_RE.search(text)
        if asset_match is None:
            continue
        asset_id = int(asset_match.group(1))
        try:
            ts_key = float(ts)
        except ValueError:
            continue
        permalink = permalink_from_ts(channel_id, ts)
        candidate = SpokeCandidate(
            asset_id=asset_id,
            permalink=permalink,
            channel_id=channel_id,
            thread_ts=ts,
            source="search",
        )
        prior = best.get(asset_id)
        if prior is None or ts_key >= prior[0]:
            best[asset_id] = (ts_key, candidate)
    return {asset_id: item[1] for asset_id, item in best.items()}


def upsert_season_spoke(
    share_root: Path,
    *,
    season_id: str,
    asset_id: int,
    permalink: str,
    channel_id: str,
    thread_ts: str,
    source: str,
    updated_at: str,
) -> bool:
    """Upsert one asset key in ``slack_threads/{season}.json``. skip corrupt files."""
    season = str(season_id or "").strip()
    if not season:
        return False
    path = Path(share_root) / "slack_threads" / f"{season}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        _LOG.warning("could not create slack_threads dir")
        return False
    entry = {
        "permalink": permalink,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "source": source,
        "updated_at": updated_at,
    }
    for _attempt in range(2):
        try:
            before = path.read_bytes() if path.is_file() else b""
        except OSError:
            _LOG.warning("could not read season file %s", path.name)
            return False
        if before:
            try:
                data: Any = json.loads(before.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                _LOG.warning("corrupt season file %s; skip write", path.name)
                return False
            if not isinstance(data, dict):
                _LOG.warning("corrupt season file %s; skip write", path.name)
                return False
        else:
            data = {"season_id": season, "assets": {}}
        assets = data.get("assets")
        if not isinstance(assets, dict):
            assets = {}
        assets[str(int(asset_id))] = entry
        data["season_id"] = season
        data["assets"] = assets
        payload = (json.dumps(data, indent=2, ensure_ascii=True) + "\n").encode("utf-8")
        try:
            current = path.read_bytes() if path.is_file() else b""
        except OSError:
            return False
        if current != before:
            continue
        try:
            path.write_bytes(payload)
        except OSError:
            _LOG.warning("could not write season file %s", path.name)
            return False
        return True
    _LOG.warning("season file %s changed during upsert; skipped", path.name)
    return False
