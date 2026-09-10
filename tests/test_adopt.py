"""Tests for /adopt-prop-threads orchestration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from red_team_prop_threader.adopt import AdoptResult, AdoptService, format_adopt_ephemeral
from red_team_prop_threader.canvas import PreflightState, PreflightResult
from red_team_prop_threader.spokes import upsert_season_spoke
from red_team_prop_threader._errors import ExternalServiceError, PermissionDeniedError


if TYPE_CHECKING:
    from pathlib import Path


_CANVAS_MD = """
### uh_hopscotch
- :shotgrid: [ShotGrid](https://respawn.shotgunstudio.com/detail/Asset/39238)
- :slack3: [t](https://respawn.slack.com/archives/C02PGV4E6KV/p1784158834442809) — Latest
"""

_NANOSHAPE_MD = """
### Motorcycle
- :shotgrid: [ShotGrid](https://respawn.shotgunstudio.com/detail/Asset/38862)
- :slack3: [emote](https://respawn.slack.com/archives/C02PGV4E6KV/p1778706626350199)
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
    """slack canvas-document / history test double."""

    def __init__(
        self,
        *,
        document: str = _CANVAS_MD,
        messages: tuple[dict[str, Any], ...] = (),
        history_error: Exception | None = None,
        document_error: Exception | None = None,
    ) -> None:
        """Store canvas document text and optional history/download failure."""
        self.document = document
        self.messages = messages
        self.history_error = history_error
        self.document_error = document_error

    def get_canvas_document(self, canvas_id: str) -> str:
        """Return INDEX body or raise the configured download error."""
        if self.document_error is not None:
            raise self.document_error
        return self.document

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


def test_adopt_writes_missing_canvas_href_and_skips_occupied(tmp_path: Path) -> None:
    """INDEX href fills a hole; existing keys are not overwritten."""
    share = tmp_path / "SG_Card_Links"
    upsert_season_spoke(
        share,
        season_id="S31.1",
        asset_id=38867,
        permalink="https://respawn.slack.com/archives/C02PGV4E6KV/p1784937709498399",
        channel_id="C02PGV4E6KV",
        thread_ts="1784937709.498399",
        source="search",
        updated_at="old",
    )
    body = (
        _NANOSHAPE_MD
        + "\n### Wing Pack\n- :shotgrid: [ShotGrid](https://respawn.shotgunstudio.com/detail/Asset/38867)\n"
        + "- :slack3: [t](https://respawn.slack.com/archives/C02PGV4E6KV/p1778707717246969)\n"
    )
    service = AdoptService(
        canvas=_Canvas(),
        slack=_Slack(document=body),
        shotgrid=_ShotGrid({38862: "31.0.0", 38867: "31.1.0"}),
        share_root=share,
        now_iso=lambda: "2026-09-10T06:00:00Z",
    )
    result = service.run(channel_id="C02PGV4E6KV")
    assert 38862 in result.adopted
    assert 38867 in result.already_present
    assert 38867 not in result.adopted
    data = json.loads((share / "slack_threads" / "S31.json").read_text(encoding="utf-8"))
    assert data["assets"]["38862"]["source"] == "canvas"
    wraith = json.loads((share / "slack_threads" / "S31.1.json").read_text(encoding="utf-8"))
    assert wraith["assets"]["38867"]["permalink"].endswith("p1784937709498399")
    assert wraith["assets"]["38867"]["updated_at"] == "old"


def test_adopt_index_unread_still_writes_missing_history(tmp_path: Path) -> None:
    """Download failure does not parse INDEX; history leftover for a missing id still writes."""
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
        slack=_Slack(messages=leftover, document_error=ExternalServiceError("files.info missing url_private_download")),
        shotgrid=_ShotGrid({111: "30.0.0"}),
        share_root=share,
        now_iso=lambda: "2026-09-10T06:00:00Z",
    )
    result = service.run(channel_id="C1")
    assert 111 in result.adopted
    assert result.detail == "INDEX file unread."
    data = json.loads((share / "slack_threads" / "S30.json").read_text(encoding="utf-8"))
    assert data["assets"]["111"]["source"] == "search"


def test_adopt_history_does_not_overwrite_occupied(tmp_path: Path) -> None:
    """History leftover for an id already on disk is already-present, not a rewrite."""
    share = tmp_path / "SG_Card_Links"
    upsert_season_spoke(
        share,
        season_id="S30",
        asset_id=111,
        permalink="https://respawn.slack.com/archives/COLD/p1000000000000000",
        channel_id="COLD",
        thread_ts="1.0",
        source="search",
        updated_at="old",
    )
    leftover = (
        {
            "ts": "20.000000",
            "thread_ts": "20.000000",
            "text": "https://respawn.shotgunstudio.com/detail/Asset/111",
        },
    )
    service = AdoptService(
        canvas=_Canvas(),
        slack=_Slack(document="", messages=leftover),
        shotgrid=_ShotGrid({111: "30.0.0"}),
        share_root=share,
        now_iso=lambda: "2026-09-10T06:00:00Z",
    )
    result = service.run(channel_id="C1")
    assert result.adopted == ()
    assert 111 in result.already_present
    data = json.loads((share / "slack_threads" / "S30.json").read_text(encoding="utf-8"))
    assert data["assets"]["111"]["updated_at"] == "old"
    assert data["assets"]["111"]["channel_id"] == "COLD"


def test_format_adopt_ephemeral_wrote_and_already_present() -> None:
    """Ephemeral reports new writes, not a recount of existing keys."""
    text = format_adopt_ephemeral(
        AdoptResult(
            adopted=(38862,),
            unmatched=(),
            history_available=True,
            already_present=(1, 2, 3),
            detail=None,
        )
    )
    assert text.startswith("Wrote 1 new.")
    assert "Already present 3." in text
    assert "Adopted" not in text


def test_adopt_empty_index_and_history(tmp_path: Path) -> None:
    """No hrefs and no leftover roots produce a clear empty detail."""
    share = tmp_path / "SG_Card_Links"
    service = AdoptService(
        canvas=_Canvas(),
        slack=_Slack(document="no links here"),
        shotgrid=_ShotGrid({}),
        share_root=share,
        now_iso=lambda: "2026-09-10T06:00:00Z",
    )
    result = service.run(channel_id="C1")
    assert result.adopted == ()
    assert result.detail == "No INDEX hrefs or leftover roots found."


def test_adopt_shotgrid_failure_does_not_write(tmp_path: Path) -> None:
    """ShotGrid lookup failure unmatched candidates and writes nothing."""
    share = tmp_path / "SG_Card_Links"

    class _Boom(_ShotGrid):
        def find_asset_labels(self, asset_ids: tuple[int, ...]) -> dict[int, tuple[list[str], list[str], str]]:
            raise ExternalServiceError("sg down")

    service = AdoptService(
        canvas=_Canvas(),
        slack=_Slack(),
        shotgrid=_Boom({}),
        share_root=share,
        now_iso=lambda: "2026-09-10T06:00:00Z",
    )
    result = service.run(channel_id="C1")
    assert 39238 in result.unmatched
    assert result.adopted == ()
    assert result.detail == "ShotGrid lookup failed."


def test_format_adopt_ephemeral_unmatched_and_history() -> None:
    """Unmatched and history-unavailable sentences still append."""
    text = format_adopt_ephemeral(
        AdoptResult(
            adopted=(),
            unmatched=(1, 2),
            history_available=False,
            already_present=(),
            detail="INDEX file unread.",
        )
    )
    assert text.startswith("Wrote 0 new.")
    assert "Unmatched 2." in text
    assert "Channel history unavailable" in text
    assert "INDEX file unread." in text
