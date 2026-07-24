"""Tests for Cadet launch coordinator and exactly-once leases."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from review_prep.state import StateRepo
from review_prep.models import RouteState, DeliveryRouteKind
from review_prep.settings import AppSettings
from review_prep.launch_coordinator import _CADET_MISSING_PROMPT, LaunchCoordinator


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _settings() -> AppSettings:
    settings = AppSettings.defaults()
    settings.cadet_launch_templates = {".ma": 'cadet --toolset apex_r5dev --app Maya --file "{file}"'}
    return settings


def _seed_ready_file(repo: StateRepo, *, local_date: str, card_id: int, path: Path) -> None:
    """Insert a READY_TO_LAUNCH route with one launchable path in detail JSON."""
    run_id = repo.start_prep_run(local_date, "test")
    detail = json.dumps({"status": "ready", "launchable": [str(path)]})
    repo.upsert_route(
        prep_run_id=run_id,
        card_sg_id=card_id,
        route_kind=DeliveryRouteKind.ATTACHMENT_LOOSE.value,
        route_key="1",
        state=RouteState.READY_TO_LAUNCH.value,
        detail=detail,
    )


def test_lease_prevents_second_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """First eligible launch takes a lease; a second pass skips the same file."""
    scene = tmp_path / "hero.ma"
    scene.write_text("//maya", encoding="utf-8")

    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    _seed_ready_file(repo, local_date="2026-07-23", card_id=42, path=scene)

    pops: list[list[str]] = []

    def fake_popen(argv: list[str], **kwargs: object) -> MagicMock:
        pops.append(list(argv))
        return MagicMock()

    monkeypatch.setattr(LaunchCoordinator, "cadet_available", lambda self: True)
    monkeypatch.setattr("review_prep.launch_coordinator.subprocess.Popen", fake_popen)

    coordinator = LaunchCoordinator(settings=_settings(), state=repo)
    first = coordinator.launch_eligible("2026-07-23")
    second = coordinator.launch_eligible("2026-07-23")

    assert first.blocked_cadet is False
    assert len(first.launched) == 1
    assert str(scene.resolve()) in first.launched
    assert repo.has_launch_lease(str(scene.resolve()), "2026-07-23") is True

    assert second.launched == []
    assert str(scene.resolve()) in second.skipped_leased
    assert len(pops) == 1
    assert pops[0][0] == "cadet"
    assert str(scene) in " ".join(pops[0]) or str(scene.resolve()) in " ".join(pops[0])


def test_cadet_missing_does_not_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When Cadet is down, report blocked_cadet and do not consume leases."""
    scene = tmp_path / "hero.ma"
    scene.write_text("//maya", encoding="utf-8")

    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    _seed_ready_file(repo, local_date="2026-07-23", card_id=42, path=scene)

    pops: list[list[str]] = []

    def fake_popen(argv: list[str], **kwargs: object) -> MagicMock:
        pops.append(list(argv))
        return MagicMock()

    monkeypatch.setattr(LaunchCoordinator, "cadet_available", lambda self: False)
    monkeypatch.setattr("review_prep.launch_coordinator.subprocess.Popen", fake_popen)

    coordinator = LaunchCoordinator(settings=_settings(), state=repo)
    report = coordinator.launch_eligible("2026-07-23")

    assert report.blocked_cadet is True
    assert _CADET_MISSING_PROMPT in report.messages
    assert report.launched == []
    assert pops == []
    assert repo.has_launch_lease(str(scene.resolve()), "2026-07-23") is False


def test_open_again_bypasses_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Open Again re-launches even when a daily lease is already held."""
    scene = tmp_path / "hero.ma"
    scene.write_text("//maya", encoding="utf-8")

    repo = StateRepo(tmp_path / "prep.db")
    repo.ensure_schema()
    _seed_ready_file(repo, local_date="2026-07-23", card_id=42, path=scene)
    assert repo.record_launch_lease(str(scene.resolve()), "2026-07-23") is True

    pops: list[list[str]] = []

    def fake_popen(argv: list[str], **kwargs: object) -> MagicMock:
        pops.append(list(argv))
        return MagicMock()

    monkeypatch.setattr(LaunchCoordinator, "cadet_available", lambda self: True)
    monkeypatch.setattr("review_prep.launch_coordinator.subprocess.Popen", fake_popen)

    coordinator = LaunchCoordinator(settings=_settings(), state=repo)
    report = coordinator.open_again([42])

    assert report.blocked_cadet is False
    assert len(report.launched) == 1
    assert len(pops) == 1
