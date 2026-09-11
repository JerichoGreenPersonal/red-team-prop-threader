"""rewrite posted asset-root Requestor labels to IC POC without new posts."""

from __future__ import annotations

from time import sleep
from typing import Any, Protocol
import logging
from dataclasses import dataclass

from red_team_prop_threader._errors import ExternalServiceError, PermissionDeniedError, RetryableExternalServiceError


__all__ = ("ASSET_ROOT_BLOCK_ID", "BackfillResult", "RelabelHit", "backfill_requestor_labels", "rewrite_message_payload")

_LOG = logging.getLogger(__name__)

ASSET_ROOT_BLOCK_ID = "ar_header"
_OLD_LABEL = "*Requestor:*"
_NEW_LABEL = "*IC POC:*"
_UPDATE_ATTEMPTS = 5


class RelabelSlack(Protocol):
    """slack methods required to scan and rewrite posted asset roots."""

    def auth_test(self) -> dict[str, Any]:
        """Return auth.test payload with bot_id and user_id."""

    def list_joined_channels(self) -> tuple[str, ...]:
        """Return channel ids the bot is a member of."""

    def get_conversation_history(self, channel_id: str) -> tuple[dict[str, Any], ...]:
        """Return channel history messages."""

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Replace a bot message in place."""


@dataclass(frozen=True, slots=True)
class RelabelHit:
    """one asset-root message that still has the Requestor label."""

    channel_id: str
    ts: str


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """outcome of a Requestor to IC POC scan or apply pass."""

    scanned_channels: int
    scanned_messages: int
    hits: tuple[RelabelHit, ...]
    updated: int
    errors: tuple[str, ...]
    dry_run: bool


def rewrite_message_payload(*, text: str, blocks: object) -> tuple[str, object, bool]:
    """Replace Requestor labels in fallback text and Block Kit JSON.

    Args:
        text: message fallback text.
        blocks: message blocks payload, or None.

    Returns:
        tuple[str, object, bool]: rewritten text, rewritten blocks, and whether anything changed.
    """
    new_text = text.replace(_OLD_LABEL, _NEW_LABEL)
    new_blocks, blocks_changed = _replace_strings(blocks)
    return new_text, new_blocks, new_text != text or blocks_changed


def backfill_requestor_labels(slack: RelabelSlack, *, apply: bool = False, channel_ids: tuple[str, ...] = ()) -> BackfillResult:
    """Scan bot asset-root messages and optionally rewrite Requestor to IC POC.

    Dry-run (apply=False) never calls chat.update. Apply rewrites matching messages
    in place and does not post new threads.

    Args:
        slack: gateway satisfying RelabelSlack.
        apply: when True, chat.update matching messages.
        channel_ids: optional explicit channel ids; otherwise all joined channels.

    Returns:
        BackfillResult: scan counts, hits, updates, and per-channel errors.
    """
    auth = slack.auth_test()
    bot_id = str(auth.get("bot_id") or "")
    bot_user_id = str(auth.get("user_id") or "")
    targets = channel_ids or slack.list_joined_channels()
    hits: list[RelabelHit] = []
    errors: list[str] = []
    scanned_messages = 0
    updated = 0

    for channel_id in targets:
        try:
            messages = slack.get_conversation_history(channel_id)
        except PermissionDeniedError as exc:
            errors.append(f"{channel_id}: {exc}")
            _LOG.warning("skipping channel %s: %s", channel_id, exc)
            continue
        except ExternalServiceError as exc:
            errors.append(f"{channel_id}: {exc}")
            _LOG.warning("skipping channel %s: %s", channel_id, exc)
            continue

        for message in messages:
            scanned_messages += 1
            if not _is_our_bot(message, bot_id=bot_id, bot_user_id=bot_user_id):
                continue
            if not _is_asset_root(message):
                continue
            text = str(message.get("text") or "")
            blocks = message.get("blocks")
            new_text, new_blocks, changed = rewrite_message_payload(text=text, blocks=blocks)
            if not changed:
                continue
            ts = str(message.get("ts") or "")
            if not ts:
                continue
            hits.append(RelabelHit(channel_id=channel_id, ts=ts))
            if not apply:
                continue
            blocks_out = _as_block_list(new_blocks)
            try:
                _update_with_retry(slack, channel_id, ts, text=new_text or text or " ", blocks=blocks_out)
            except ExternalServiceError as exc:
                errors.append(f"{channel_id} ts={ts}: {exc}")
                _LOG.warning("failed to update %s ts=%s: %s", channel_id, ts, exc)
                continue
            updated += 1

    return BackfillResult(
        scanned_channels=len(targets), scanned_messages=scanned_messages, hits=tuple(hits), updated=updated, errors=tuple(errors), dry_run=not apply
    )


def _is_our_bot(message: dict[str, Any], *, bot_id: str, bot_user_id: str) -> bool:
    """Return True when the history item was posted by this bot."""
    if bot_id and str(message.get("bot_id") or "") == bot_id:
        return True
    return bool(bot_user_id and str(message.get("user") or "") == bot_user_id)


def _is_asset_root(message: dict[str, Any]) -> bool:
    """Return True when the message is a posted asset-root Block Kit payload."""
    blocks = message.get("blocks")
    if not isinstance(blocks, list):
        return False
    return any(isinstance(block, dict) and block.get("block_id") == ASSET_ROOT_BLOCK_ID for block in blocks)


def _as_block_list(blocks: object) -> list[dict[str, Any]] | None:
    """Return Block Kit blocks if the rewritten payload is a list of dicts."""
    if not isinstance(blocks, list):
        return None
    typed: list[dict[str, Any]] = []
    for block in blocks:
        if isinstance(block, dict):
            typed.append({str(key): value for key, value in block.items()})
    return typed


def _replace_strings(value: Any) -> tuple[Any, bool]:
    """Recursively replace Requestor labels inside JSON-like values."""
    if isinstance(value, str):
        replaced = value.replace(_OLD_LABEL, _NEW_LABEL)
        return replaced, replaced != value
    if isinstance(value, list):
        items: list[Any] = []
        changed = False
        for item in value:
            new_item, item_changed = _replace_strings(item)
            items.append(new_item)
            changed = changed or item_changed
        return items, changed
    if isinstance(value, dict):
        mapping: dict[Any, Any] = {}
        changed = False
        for key, item in value.items():
            new_item, item_changed = _replace_strings(item)
            mapping[key] = new_item
            changed = changed or item_changed
        return mapping, changed
    return value, False


def _update_with_retry(slack: RelabelSlack, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None) -> None:
    """Retry chat.update on slack rate limits."""
    last_error: RetryableExternalServiceError | None = None
    for attempt in range(_UPDATE_ATTEMPTS):
        try:
            slack.update_message(channel_id, ts, text=text, blocks=blocks)
            return
        except RetryableExternalServiceError as exc:
            last_error = exc
            wait = exc.retry_after if exc.retry_after is not None else float(attempt + 1)
            _LOG.warning("rate limited updating %s ts=%s; sleeping %.1fs", channel_id, ts, wait)
            sleep(wait)
    if last_error is not None:
        raise last_error
