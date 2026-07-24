"""Logic-level tests for summary acknowledgment (no Qt display required)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import date, timedelta

from review_prep.state import StateRepo
from review_prep.models import RouteState, DeliveryRouteKind
from review_prep.ui.main_window import aggregate_card_status
from review_prep.ui.summary_dialog import format_summary_text, acknowledge_summary_close


if TYPE_CHECKING:
    from pathlib import Path


def test_acknowledge_summary_close_acks_run(tmp_path: Path) -> None:
    """Closing the summary must persist ack so latest_unacked_run clears."""
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    run_id = repo.start_prep_run("2026-07-24", "scheduled")
    assert repo.latest_unacked_run() == run_id

    acknowledge_summary_close(repo, run_id)

    assert repo.latest_unacked_run() is None


def test_acknowledge_summary_close_is_idempotent(tmp_path: Path) -> None:
    """Re-acking an already-acked run remains a no-op for unacked lookup."""
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    run_id = repo.start_prep_run("2026-07-24", "manual")
    acknowledge_summary_close(repo, run_id)
    acknowledge_summary_close(repo, run_id)
    assert repo.latest_unacked_run() is None


def test_format_summary_text_includes_route_states(tmp_path: Path) -> None:
    """Summary text lists route states for the prep run on the given date."""
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    run_id = repo.start_prep_run("2026-07-24", "scheduled")
    repo.upsert_route(
        prep_run_id=run_id,
        card_sg_id=1001,
        route_kind=DeliveryRouteKind.ATTACHMENT_ARCHIVE.value,
        route_key="att:9",
        state=RouteState.READY_TO_LAUNCH.value,
        detail='{"launchable":[]}',
    )
    repo.upsert_route(
        prep_run_id=run_id, card_sg_id=1001, route_kind=DeliveryRouteKind.P4_CL.value, route_key="WIP:1", state=RouteState.FAILED.value, detail="sync error"
    )

    text = format_summary_text(repo, run_id, local_date="2026-07-24")

    assert f"Prep run {run_id}" in text
    assert "ready_to_launch: 1" in text
    assert "failed: 1" in text
    assert "Close this dialog to acknowledge." in text


def test_format_summary_text_uses_unacked_run_local_date_not_today(tmp_path: Path) -> None:
    """Unacked run dated other than today still lists that day's routes."""
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    today = date.today().isoformat()
    other_day = (date.today() - timedelta(days=3)).isoformat()
    assert other_day != today

    run_id = repo.start_prep_run(other_day, "scheduled")
    assert repo.latest_unacked_run() == run_id
    repo.upsert_route(
        prep_run_id=run_id,
        card_sg_id=2002,
        route_kind=DeliveryRouteKind.ATTACHMENT_ARCHIVE.value,
        route_key="att:42",
        state=RouteState.READY_TO_LAUNCH.value,
        detail='{"launchable":[]}',
    )

    # Default lookup (as SummaryDialog / startup does) must use the run date.
    text = format_summary_text(repo, run_id)

    assert f"Prep run {run_id} ({other_day})" in text
    assert "ready_to_launch: 1" in text
    assert f"No route rows recorded for this run on {today}." not in text
    assert today not in text.split("\n")[0]


def test_newer_unacked_run_survives_ack_of_older(tmp_path: Path) -> None:
    """Acking an older run leaves a newer unacked run for the next popup."""
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    older = repo.start_prep_run("2026-07-24", "scheduled")
    newer = repo.start_prep_run("2026-07-24", "manual")
    assert repo.latest_unacked_run() == newer

    acknowledge_summary_close(repo, older)

    assert repo.latest_unacked_run() == newer


def test_aggregate_card_status_empty() -> None:
    """Empty routes mean the card is not prepared."""
    assert aggregate_card_status([]) == RouteState.NOT_PREPARED.value


def test_aggregate_card_status_prefers_failed() -> None:
    """Failed wins over ready_to_launch when summarizing a card."""
    routes = [{"state": RouteState.READY_TO_LAUNCH.value}, {"state": RouteState.FAILED.value}]
    assert aggregate_card_status(routes) == RouteState.FAILED.value
