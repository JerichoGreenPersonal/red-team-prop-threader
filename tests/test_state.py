from pathlib import Path
import sqlite3

import pytest

from review_prep.state import StateRepo
from review_prep.models import RouteState, DeliveryRouteKind


def test_launch_lease_is_exactly_once(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    assert repo.record_launch_lease("file-a", "2026-07-23") is True
    assert repo.record_launch_lease("file-a", "2026-07-23") is False
    assert repo.record_launch_lease("file-a", "2026-07-24") is True


def test_release_launch_lease_allows_reclaim(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    assert repo.record_launch_lease("file-a", "2026-07-23") is True
    repo.release_launch_lease("file-a", "2026-07-23")
    assert repo.has_launch_lease("file-a", "2026-07-23") is False
    assert repo.record_launch_lease("file-a", "2026-07-23") is True


def test_summary_ack(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    run_id = repo.start_prep_run("2026-07-23", "scheduled")
    assert repo.latest_unacked_run() == run_id
    repo.ack_summary(run_id)
    assert repo.latest_unacked_run() is None


def test_get_prep_run_local_date(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    run_id = repo.start_prep_run("2026-07-21", "manual")
    assert repo.get_prep_run_local_date(run_id) == "2026-07-21"
    assert repo.get_prep_run_local_date(99999) is None


def test_route_upsert_roundtrip(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    run_id = repo.start_prep_run("2026-07-23", "manual")
    repo.upsert_route(
        prep_run_id=run_id,
        card_sg_id=38811,
        route_kind=DeliveryRouteKind.P4_CL.value,
        route_key="WIP:11290000",
        state=RouteState.SYNCED_ONLY.value,
        detail="ok",
    )
    routes = repo.get_routes_for_card(38811)
    assert routes[0]["state"] == RouteState.SYNCED_ONLY.value


def test_orphan_route_insert_raises_integrity_error(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    with pytest.raises(sqlite3.IntegrityError):
        repo.upsert_route(
            prep_run_id=99999,
            card_sg_id=38811,
            route_kind=DeliveryRouteKind.P4_CL.value,
            route_key="WIP:orphan",
            state=RouteState.SYNCED_ONLY.value,
            detail="orphan",
        )
