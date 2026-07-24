from pathlib import Path

from review_prep.models import DeliveryRouteKind, RouteState
from review_prep.state import StateRepo


def test_launch_lease_is_exactly_once(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    assert repo.record_launch_lease("file-a", "2026-07-23") is True
    assert repo.record_launch_lease("file-a", "2026-07-23") is False
    assert repo.record_launch_lease("file-a", "2026-07-24") is True


def test_summary_ack(tmp_path: Path):
    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    run_id = repo.start_prep_run("2026-07-23", "scheduled")
    assert repo.latest_unacked_run() == run_id
    repo.ack_summary(run_id)
    assert repo.latest_unacked_run() is None


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
