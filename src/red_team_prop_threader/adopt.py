"""adopt INDEX hrefs and leftover channel roots into ReviewPrep season JSON."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from datetime import datetime, timezone
from dataclasses import dataclass

from red_team_prop_threader.canvas import CANVAS_TITLE, PreflightState
from red_team_prop_threader.season import grouping_season_with_fallback
from red_team_prop_threader.spokes import occupied_asset_ids, history_root_spokes, upsert_season_spoke, canvas_latest_spokes
from red_team_prop_threader._errors import ExternalServiceError, PermissionDeniedError


if TYPE_CHECKING:
    from pathlib import Path
    from collections.abc import Callable

    from red_team_prop_threader.canvas import PreflightResult
    from red_team_prop_threader.spokes import SpokeCandidate


__all__ = ("AdoptResult", "AdoptService", "format_adopt_ephemeral")


@dataclass(frozen=True, slots=True)
class AdoptResult:
    """outcome of one /adopt-prop-threads run in a satellite channel."""

    adopted: tuple[int, ...]
    unmatched: tuple[int, ...]
    history_available: bool
    already_present: tuple[int, ...] = ()
    detail: str | None = None


class _CanvasPreflight(Protocol):
    def preflight(self, channel_id: str, *, title: str = CANVAS_TITLE) -> PreflightResult:
        """Inspect the channel canvas title."""


class _SlackAdopt(Protocol):
    def get_canvas_document(self, canvas_id: str) -> str:
        """Return INDEX canvas body text."""

    def get_conversation_history(self, channel_id: str) -> tuple[dict[str, object], ...]:
        """Return channel history pages."""


class _ShotGridAdopt(Protocol):
    def find_asset_labels(self, asset_ids: tuple[int, ...]) -> dict[int, tuple[list[str], list[str], str]]:
        """Return jira labels, tags, and code per asset id."""


class AdoptService:
    """parse one satellite channel and upsert official slack spokes."""

    def __init__(
        self,
        *,
        canvas: _CanvasPreflight,
        slack: _SlackAdopt,
        shotgrid: _ShotGridAdopt,
        share_root: Path,
        now_iso: Callable[[], str] | None = None,
    ) -> None:
        """Bind canvas, slack, shotgrid, and the ReviewPrep share root."""
        self._canvas = canvas
        self._slack = slack
        self._shotgrid = shotgrid
        self._share_root = share_root
        self._now_iso = now_iso or (lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def run(self, channel_id: str) -> AdoptResult:
        """Adopt INDEX hrefs then leftover roots in ``channel_id``."""
        preflight = self._canvas.preflight(channel_id, title=CANVAS_TITLE)
        if preflight.state is not PreflightState.READY or not preflight.canvas_id:
            return AdoptResult(
                adopted=(),
                unmatched=(),
                history_available=True,
                detail="This channel has no INDEX OF PROP REQUESTS canvas.",
            )
        index_unread = False
        try:
            document = self._slack.get_canvas_document(preflight.canvas_id)
        except ExternalServiceError:
            document = ""
            index_unread = True
        canvas_spokes = canvas_latest_spokes(document)
        history_available = True
        history_spokes: dict[int, SpokeCandidate] = {}
        try:
            messages = self._slack.get_conversation_history(channel_id)
            history_spokes = history_root_spokes(messages, channel_id=channel_id)
        except PermissionDeniedError:
            history_available = False
        except ExternalServiceError:
            history_available = False
        merged = dict(canvas_spokes)
        for asset_id, spoke in history_spokes.items():
            if asset_id not in merged:
                merged[asset_id] = spoke
        unread_detail = "INDEX file unread." if index_unread else None
        if not merged:
            detail = unread_detail or "No INDEX hrefs or leftover roots found."
            return AdoptResult(adopted=(), unmatched=(), history_available=history_available, detail=detail)
        occupied = occupied_asset_ids(self._share_root)
        already = tuple(sorted(asset_id for asset_id in merged if asset_id in occupied))
        candidates = {asset_id: spoke for asset_id, spoke in merged.items() if asset_id not in occupied}
        if not candidates:
            return AdoptResult(
                adopted=(),
                unmatched=(),
                history_available=history_available,
                already_present=already,
                detail=unread_detail,
            )
        try:
            labels = self._shotgrid.find_asset_labels(tuple(candidates))
        except ExternalServiceError:
            return AdoptResult(
                adopted=(),
                unmatched=tuple(sorted(candidates)),
                history_available=history_available,
                already_present=already,
                detail=unread_detail or "ShotGrid lookup failed.",
            )
        adopted: list[int] = []
        unmatched: list[int] = []
        updated_at = str(self._now_iso())
        for asset_id, spoke in candidates.items():
            jira, tags, code = labels.get(asset_id, ([], [], ""))
            season = grouping_season_with_fallback(jira, tags=tags, gantt_season=code)
            if not season:
                unmatched.append(asset_id)
                continue
            wrote = upsert_season_spoke(
                self._share_root,
                season_id=season,
                asset_id=asset_id,
                permalink=spoke.permalink,
                channel_id=spoke.channel_id,
                thread_ts=spoke.thread_ts,
                source=spoke.source,
                updated_at=updated_at,
            )
            if wrote:
                adopted.append(asset_id)
            else:
                unmatched.append(asset_id)
        return AdoptResult(
            adopted=tuple(adopted),
            unmatched=tuple(unmatched),
            history_available=history_available,
            already_present=already,
            detail=unread_detail,
        )


def format_adopt_ephemeral(result: AdoptResult) -> str:
    """user-facing ephemeral summary for /adopt-prop-threads."""
    if result.detail and not result.adopted and not result.unmatched and not result.already_present:
        return result.detail
    adopted_n = len(result.adopted)
    already_n = len(result.already_present)
    unmatched_n = len(result.unmatched)
    parts = [f"Wrote {adopted_n} new."]
    if already_n:
        parts.append(f"Already present {already_n}.")
    if unmatched_n:
        parts.append(f"Unmatched {unmatched_n}.")
    if not result.history_available:
        parts.append("Channel history unavailable (Connect or missing scope).")
    if result.detail:
        parts.append(result.detail)
    return " ".join(parts)
