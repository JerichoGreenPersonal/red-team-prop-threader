"""Tests for the prep orchestrator (attachment + P4 routes)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path
import zipfile
from datetime import date
from unittest.mock import MagicMock

from review_prep.state import StateRepo
from review_prep.models import RouteState, DeliveryRouteKind
from tests.fakes.fake_p4 import FakeP4
from review_prep.settings import AppSettings
from review_prep.p4_adapter import P4Adapter
from review_prep.orchestrator import PrepOrchestrator
from tests.fakes.fake_shotgun import FakeShotgun
from review_prep.shotgun_adapter import ShotGridAdapter


if TYPE_CHECKING:
    import pytest


def _zip_bytes(names: dict[str, bytes]) -> bytes:
    """Build an in-memory zip and return its bytes."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in names.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _fake_7z_run(cmd: list[str], **kwargs: object) -> MagicMock:
    """Simulate ``7z x`` by writing members into the ``-o`` staging dir."""
    assert cmd[1] == "x"
    archive = Path(cmd[2])
    out_arg = next(str(a) for a in cmd if str(a).startswith("-o"))
    out_dir = Path(out_arg[2:])
    out_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "r") as zf:
        zf.extractall(out_dir)
    result = MagicMock()
    result.returncode = 0
    result.stderr = ""
    result.stdout = ""
    return result


def _settings(staging_root: Path) -> AppSettings:
    settings = AppSettings.defaults()
    settings.staging_root = str(staging_root)
    settings.p4_client = "test_client"
    settings.seven_zip_exe = "7z.exe"
    return settings


def test_card_runs_attachment_and_cl_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One card with zip attachment + WIP CL records two routes and launchables."""
    monkeypatch.setattr("review_prep.archive_extractor.subprocess.run", _fake_7z_run)

    staging = tmp_path / "staging"
    p4_local = tmp_path / "ws" / "synced.ma"
    p4_local.parent.mkdir(parents=True)
    p4_local.write_text("//maya", encoding="utf-8")

    card_id = 42
    attachment_id = 7
    zip_payload = _zip_bytes({"review/hero.ma": b"//maya scene"})

    fake_sg = FakeShotgun(
        worklist=[{"id": card_id, "code": "hero_asset", "image": None}],
        attachments_by_card={card_id: [{"id": attachment_id, "filename": "delivery.zip", "file_size": len(zip_payload), "created_at": "2026-07-23T10:00:00"}]},
        notes_by_card={card_id: [{"id": 1, "content": "WIP CL 11290000", "created_at": "2026-07-23T11:00:00"}]},
        file_bytes={attachment_id: zip_payload},
    )
    fake_p4 = FakeP4(describe={11290000: ["//depot/synced.ma"]}, map={"//depot/synced.ma": str(p4_local)})

    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    sg = ShotGridAdapter(fake_sg, entity_type="Asset")
    p4 = P4Adapter(client="test_client", runner=fake_p4)

    orch = PrepOrchestrator(settings=_settings(staging), state=repo, shotgun=sg, p4=p4, local_date=date(2026, 7, 23), trigger="test")
    result = orch.run_worklist()

    routes = repo.get_routes_for_card(card_id)
    assert len(routes) == 2
    kinds = {r["route_kind"] for r in routes}
    assert DeliveryRouteKind.ATTACHMENT_ARCHIVE.value in kinds
    assert DeliveryRouteKind.P4_CL.value in kinds

    launchable_names = {Path(p).name for p in result.launchable_files}
    assert "hero.ma" in launchable_names
    assert "synced.ma" in launchable_names

    by_kind = {r["route_kind"]: r for r in routes}
    assert by_kind[DeliveryRouteKind.ATTACHMENT_ARCHIVE.value]["state"] == RouteState.READY_TO_LAUNCH.value
    assert by_kind[DeliveryRouteKind.P4_CL.value]["state"] == RouteState.READY_TO_LAUNCH.value
    assert fake_p4.synced == ["//depot/synced.ma@11290000"]


def test_source_art_cl_is_sync_only_not_launchable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Source Art policy syncs but does not add files to the launchable list."""
    monkeypatch.setattr("review_prep.archive_extractor.subprocess.run", _fake_7z_run)

    staging = tmp_path / "staging"
    p4_local = tmp_path / "ws" / "art.ma"
    p4_local.parent.mkdir(parents=True)
    p4_local.write_text("//maya", encoding="utf-8")

    card_id = 10
    fake_sg = FakeShotgun(
        worklist=[{"id": card_id, "code": "art_asset", "image": None}],
        attachments_by_card={card_id: []},
        notes_by_card={card_id: [{"id": 1, "content": "Source Art CL is 99", "created_at": "2026-07-23T11:00:00"}]},
    )
    fake_p4 = FakeP4(describe={99: ["//depot/art.ma"]}, map={"//depot/art.ma": str(p4_local)})

    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    orch = PrepOrchestrator(
        settings=_settings(staging),
        state=repo,
        shotgun=ShotGridAdapter(fake_sg, entity_type="Asset"),
        p4=P4Adapter(client="test_client", runner=fake_p4),
        local_date=date(2026, 7, 23),
        trigger="test",
    )
    result = orch.prepare_cards([card_id])

    routes = repo.get_routes_for_card(card_id)
    assert len(routes) == 1
    assert routes[0]["route_kind"] == DeliveryRouteKind.P4_CL.value
    assert routes[0]["state"] == RouteState.SYNCED_ONLY.value
    assert result.launchable_files == []
    assert fake_p4.synced == ["//depot/art.ma@99"]


def test_sibling_routes_continue_after_one_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed attachment route must not prevent a sibling P4 route from completing."""
    monkeypatch.setattr("review_prep.archive_extractor.subprocess.run", _fake_7z_run)

    staging = tmp_path / "staging"
    p4_local = tmp_path / "ws" / "ok.ma"
    p4_local.parent.mkdir(parents=True)
    p4_local.write_text("//maya", encoding="utf-8")

    card_id = 55
    attachment_id = 3
    # Corrupt / non-archive payload so extract fails after download.
    fake_sg = FakeShotgun(
        worklist=[{"id": card_id, "code": "partial_asset", "image": None}],
        attachments_by_card={card_id: [{"id": attachment_id, "filename": "broken.zip", "file_size": 4, "created_at": "2026-07-23T10:00:00"}]},
        notes_by_card={card_id: [{"id": 1, "content": "WIP CL 200", "created_at": "2026-07-23T11:00:00"}]},
        file_bytes={attachment_id: b"not-a-zip"},
    )
    fake_p4 = FakeP4(describe={200: ["//depot/ok.ma"]}, map={"//depot/ok.ma": str(p4_local)})

    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    orch = PrepOrchestrator(
        settings=_settings(staging),
        state=repo,
        shotgun=ShotGridAdapter(fake_sg, entity_type="Asset"),
        p4=P4Adapter(client="test_client", runner=fake_p4),
        local_date=date(2026, 7, 23),
        trigger="test",
    )
    result = orch.run_worklist()

    routes = {r["route_kind"]: r for r in repo.get_routes_for_card(card_id)}
    assert routes[DeliveryRouteKind.ATTACHMENT_ARCHIVE.value]["state"] == RouteState.FAILED.value
    assert routes[DeliveryRouteKind.P4_CL.value]["state"] == RouteState.READY_TO_LAUNCH.value
    assert any(Path(p).name == "ok.ma" for p in result.launchable_files)
    assert result.hard_failure is False
