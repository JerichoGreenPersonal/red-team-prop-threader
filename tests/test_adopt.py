"""Tests for /adopt-prop-threads orchestration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from red_team_prop_threader.adopt import AdoptService
from red_team_prop_threader.canvas import PreflightState, PreflightResult
from red_team_prop_threader._errors import PermissionDeniedError


if TYPE_CHECKING:
    from pathlib import Path


_CANVAS_MD = """
### uh_hopscotch
- :shotgrid: [ShotGrid](https://respawn.shotgunstudio.com/detail/Asset/39238)
- :slack3: [t](https://respawn.slack.com/archives/C02PGV4E6KV/p1784158834442809) — Latest
"""


class _Canvas:
    """canvas preflight test double."""

    def __init__(self, state: PreflightState = PreflightState.READY, canvas_id: str | None = "F1") -> None:
        """Store the preflight outcome to return."""
        self.state = state
        self.canvas_id = canvas_id

    def preflight(self, channel_id: str, *, title: str = "INDEX OF PROP REQUESTS") -> PreflightResult:
        """Return the configured preflight result."""
        return PreflightResult(self.state, self.canvas_id, current_title=title)


class _Slack:
    """slack lookup/history test double."""

    def __init__(self, *, markdown: str = _CANVAS_MD, messages: tuple[dict[str, Any], ...] = (), history_error: Exception | None = None) -> None:
        """Store canvas markdown and optional history failure."""
        self.markdown = markdown
        self.messages = messages
        self.history_error = history_error

    def lookup_sections(self, canvas_id: str, *, contains_text: str | None = None, section_types: tuple[str, ...] = ("any_header",)) -> list[dict[str, Any]]:
        """Return harvested canvas markdown as a lookup payload."""
        return [{"markdown": self.markdown}]

    def get_file_info(self, file_id: str) -> dict[str, Any]:
        """Return a titled INDEX canvas file object."""
        return {"id": file_id, "title": "INDEX OF PROP REQUESTS"}

    def get_conversation_history(self, channel_id: str) -> tuple[dict[str, Any], ...]:
        """Return leftover root messages or raise the configured error."""
        if self.history_error is not None:
            raise self.history_error
        return self.messages


class _ShotGrid:
    """shotgrid label test double keyed by asset id."""

    def __init__(self, seasons: dict[int, str | None]) -> None:
        """Store jira season labels per asset."""
        self.seasons = seasons

    def find_asset_labels(self, asset_ids: tuple[int, ...]) -> dict[int, tuple[list[str], list[str], str]]:
        """Return jira labels for requested assets."""
        out: dict[int, tuple[list[str], list[str], str]] = {}
        for asset_id in asset_ids:
            season = self.seasons.get(asset_id)
            jira = [season] if season else []
            out[asset_id] = (jira, [], "")
        return out


def test_adopt_writes_canvas_latest_and_history_leftover(tmp_path: Path) -> None:
    """Canvas Latest and leftover roots both land in the season file."""
    share = tmp_path / "SG_Card_Links"
    leftover = (
        {
            "ts": "20.000000",
            "thread_ts": "20.000000",
            "text": "https://respawn.shotgunstudio.com/detail/Asset/111",
        },
    )
    service = AdoptService(
        canvas=_Canvas(),
        slack=_Slack(messages=leftover),
        shotgrid=_ShotGrid({39238: "30.0.0", 111: "30.0.0"}),
        share_root=share,
        now_iso=lambda: "2026-09-03T21:00:00Z",
    )
    result = service.run(channel_id="C02PGV4E6KV")
    assert 39238 in result.adopted
    assert 111 in result.adopted
    data = json.loads((share / "slack_threads" / "S30.json").read_text(encoding="utf-8"))
    assert data["assets"]["39238"]["source"] == "canvas"
    assert data["assets"]["111"]["source"] == "search"
    assert result.history_available is True


def test_adopt_skips_write_when_season_unknown(tmp_path: Path) -> None:
    """Assets without a grouping season are unmatched and not written."""
    share = tmp_path / "SG_Card_Links"
    service = AdoptService(
        canvas=_Canvas(),
        slack=_Slack(),
        shotgrid=_ShotGrid({39238: None}),
        share_root=share,
        now_iso=lambda: "2026-09-03T21:00:00Z",
    )
    result = service.run(channel_id="C1")
    assert 39238 in result.unmatched
    assert not (share / "slack_threads").exists() or not list((share / "slack_threads").glob("*.json"))


def test_adopt_canvas_succeeds_when_history_denied(tmp_path: Path) -> None:
    """INDEX Latest still upserts when conversations.history is denied."""
    share = tmp_path / "SG_Card_Links"
    service = AdoptService(
        canvas=_Canvas(),
        slack=_Slack(history_error=PermissionDeniedError("missing_scope")),
        shotgrid=_ShotGrid({39238: "30.0.0"}),
        share_root=share,
        now_iso=lambda: "2026-09-03T21:00:00Z",
    )
    result = service.run(channel_id="C1")
    assert 39238 in result.adopted
    assert result.history_available is False
    assert (share / "slack_threads" / "S30.json").is_file()


def test_adopt_refuses_when_index_canvas_not_ready(tmp_path: Path) -> None:
    """PRIMARY or untitled canvases are not scraped."""
    share = tmp_path / "SG_Card_Links"
    service = AdoptService(
        canvas=_Canvas(state=PreflightState.RENAME_CONFIRMATION_REQUIRED, canvas_id="Fprimary"),
        slack=_Slack(),
        shotgrid=_ShotGrid({}),
        share_root=share,
        now_iso=lambda: "2026-09-03T21:00:00Z",
    )
    result = service.run(channel_id="C04H4QZEYUE")
    assert result.adopted == ()
    assert "INDEX OF PROP REQUESTS" in (result.detail or "")
