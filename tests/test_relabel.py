"""tests for Requestor to IC POC message rewrites and backfill."""

from __future__ import annotations

from typing import Any

from red_team_prop_threader._errors import PermissionDeniedError, RetryableExternalServiceError
from red_team_prop_threader.relabel import GROUP_REPLACEMENTS, RelabelHit, rewrite_message_payload, backfill_requestor_labels


_HEADER_REQUESTOR = {
    "type": "section",
    "block_id": "ar_header",
    "text": {"type": "mrkdwn", "text": ":threadparrot: *Asset:* Prop\n*Group:* G\n*Requestor:* <@U1>\n*Group POCs:* unassigned"},
}
_HEADER_IC_POC = {
    "type": "section",
    "block_id": "ar_header",
    "text": {"type": "mrkdwn", "text": ":threadparrot: *Asset:* Prop\n*Group:* G\n*IC POC:* <@U1>\n*Group POCs:* unassigned"},
}
_HEADER_IC_POC_ADDITIONAL = {
    "type": "section",
    "block_id": "ar_header",
    "text": {"type": "mrkdwn", "text": ":threadparrot: *Asset:* Prop\n*Group:* G\n*IC POC:* <@U1>  *Additional:* <@U2>\n*Group POCs:* unassigned"},
}
_HEADER_IC_POC_ADDITIONAL_ICS = {
    "type": "section",
    "block_id": "ar_header",
    "text": {"type": "mrkdwn", "text": ":threadparrot: *Asset:* Prop\n*Group:* G\n*IC POC:* <@U1>  *Additional ICs:* <@U2>\n*Group POCs:* unassigned"},
}
_GROUP_ADDITIONAL = {
    "type": "section",
    "block_id": "gs_header",
    "text": {"type": "mrkdwn", "text": "*Title*\n*Creative Stakeholder:* <@U1>  *Additional:* <@U2>"},
}
_GROUP_ADDITIONAL_STAKEHOLDERS = {
    "type": "section",
    "block_id": "gs_header",
    "text": {"type": "mrkdwn", "text": "*Title*\n*Creative Stakeholder:* <@U1>  *Additional stakeholders:* <@U2>"},
}


class _Slack:
    """in-memory slack double for relabel backfill."""

    def __init__(
        self,
        *,
        channels: tuple[str, ...] = ("C1",),
        messages: dict[str, tuple[dict[str, Any], ...]] | None = None,
        history_errors: dict[str, Exception] | None = None,
        update_errors: list[Exception] | None = None,
    ) -> None:
        """Store channels, history, and optional failures."""
        self.channels = channels
        self.messages = messages or {}
        self.history_errors = history_errors or {}
        self.update_errors = list(update_errors or [])
        self.updates: list[tuple[str, str, str, list[dict[str, Any]] | None]] = []

    def auth_test(self) -> dict[str, Any]:
        """Return a stable bot identity."""
        return {"bot_id": "B1", "user_id": "Ubot"}

    def list_joined_channels(self) -> tuple[str, ...]:
        """Return configured channel ids."""
        return self.channels

    def get_conversation_history(self, channel_id: str) -> tuple[dict[str, Any], ...]:
        """Return history or raise the configured channel error."""
        error = self.history_errors.get(channel_id)
        if error is not None:
            raise error
        return self.messages.get(channel_id, ())

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Record an in-place update, optionally raising a queued error first."""
        if self.update_errors:
            raise self.update_errors.pop(0)
        self.updates.append((channel_id, ts, text, blocks))
        return {"ok": True}


def test_rewrite_replaces_requestor_in_text_and_blocks() -> None:
    """Nested Block Kit strings and fallback text both become IC POC."""
    text, blocks, changed = rewrite_message_payload(text="*Requestor:* <@U1>", blocks=[_HEADER_REQUESTOR])
    assert changed is True
    assert text == "*IC POC:* <@U1>"
    assert blocks == [_HEADER_IC_POC]


def test_rewrite_is_noop_when_already_ic_poc() -> None:
    """Messages already labeled IC POC are left unchanged."""
    text, blocks, changed = rewrite_message_payload(text="*IC POC:* <@U1>", blocks=[_HEADER_IC_POC])
    assert changed is False
    assert text == "*IC POC:* <@U1>"
    assert blocks == [_HEADER_IC_POC]


def test_rewrite_asset_additional_to_additional_ics() -> None:
    """Bare Additional on an asset root becomes Additional ICs."""
    text, blocks, changed = rewrite_message_payload(text="*Additional:* <@U2>", blocks=[_HEADER_IC_POC_ADDITIONAL])
    assert changed is True
    assert text == "*Additional ICs:* <@U2>"
    assert blocks == [_HEADER_IC_POC_ADDITIONAL_ICS]


def test_rewrite_group_additional_to_additional_stakeholders() -> None:
    """Bare Additional on a group summary becomes Additional stakeholders."""
    text, blocks, changed = rewrite_message_payload(text="*Additional:* <@U2>", blocks=[_GROUP_ADDITIONAL], replacements=GROUP_REPLACEMENTS)
    assert changed is True
    assert text == "*Additional stakeholders:* <@U2>"
    assert blocks == [_GROUP_ADDITIONAL_STAKEHOLDERS]


def test_backfill_dry_run_does_not_update() -> None:
    """Dry-run reports hits without calling chat.update."""
    slack = _Slack(messages={"C1": (_bot_root("1.0", [_HEADER_REQUESTOR]),)})
    result = backfill_requestor_labels(slack, apply=False)
    assert result.dry_run is True
    assert result.updated == 0
    assert slack.updates == []
    assert result.hits == (RelabelHit(channel_id="C1", ts="1.0"),)


def test_backfill_apply_updates_only_bot_asset_roots() -> None:
    """Apply rewrites our Requestor roots and ignores other messages."""
    slack = _Slack(
        messages={
            "C1": (
                _bot_root("1.0", [_HEADER_REQUESTOR]),
                _bot_root("2.0", [_HEADER_IC_POC]),
                {"ts": "3.0", "bot_id": "Bother", "blocks": [_HEADER_REQUESTOR]},
                {"ts": "4.0", "bot_id": "B1", "text": "*Requestor:* x", "blocks": [{"type": "section", "block_id": "other"}]},
                {"ts": "5.0", "user": "Uhuman", "blocks": [_HEADER_REQUESTOR]},
            )
        }
    )
    result = backfill_requestor_labels(slack, apply=True)
    assert result.updated == 1
    assert len(result.hits) == 1
    assert slack.updates[0][0] == "C1"
    assert slack.updates[0][1] == "1.0"
    assert slack.updates[0][2] == " "
    assert slack.updates[0][3] == [_HEADER_IC_POC]


def test_backfill_skips_channel_on_permission_error() -> None:
    """A denied channel is recorded and does not abort the rest of the scan."""
    slack = _Slack(
        channels=("Cbad", "C1"),
        messages={"C1": (_bot_root("1.0", [_HEADER_REQUESTOR]),)},
        history_errors={"Cbad": PermissionDeniedError("slack permission denied (not_in_channel)")},
    )
    result = backfill_requestor_labels(slack, apply=True)
    assert result.updated == 1
    assert result.errors[0].startswith("Cbad:")


def test_backfill_retries_rate_limit_then_updates() -> None:
    """Transient slack rate limits are retried until chat.update succeeds."""
    slack = _Slack(
        messages={"C1": (_bot_root("1.0", [_HEADER_REQUESTOR], text="*Requestor:* <@U1>"),)},
        update_errors=[RetryableExternalServiceError("slack api temporarily unavailable", retry_after=0)],
    )
    result = backfill_requestor_labels(slack, apply=True)
    assert result.updated == 1
    assert slack.updates[0][2] == "*IC POC:* <@U1>"


def test_backfill_rewrites_group_summary_additional() -> None:
    """Group summaries with bare Additional are rewritten to Additional stakeholders."""
    slack = _Slack(messages={"C1": (_bot_root("1.0", [_GROUP_ADDITIONAL]),)})
    result = backfill_requestor_labels(slack, apply=True)
    assert result.updated == 1
    assert slack.updates[0][3] == [_GROUP_ADDITIONAL_STAKEHOLDERS]


def test_backfill_honors_explicit_channel_ids() -> None:
    """An explicit channel list is used instead of users.conversations."""
    slack = _Slack(channels=("Cskip",), messages={"Cskip": (_bot_root("9.0", [_HEADER_REQUESTOR]),), "C1": (_bot_root("1.0", [_HEADER_REQUESTOR]),)})
    result = backfill_requestor_labels(slack, apply=True, channel_ids=("C1",))
    assert result.scanned_channels == 1
    assert result.updated == 1
    assert slack.updates[0][0] == "C1"


def _bot_root(ts: str, blocks: list[dict[str, Any]], *, text: str = "") -> dict[str, Any]:
    """Build a bot-authored asset-root history item."""
    return {"ts": ts, "bot_id": "B1", "user": "Ubot", "text": text, "blocks": blocks}
