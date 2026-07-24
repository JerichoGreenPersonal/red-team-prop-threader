from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path

from review_prep.models import ClPolicy
from review_prep.settings import AppSettings, load_settings, save_settings
from review_prep.worker_main import resolve_shotgrid_query_path


if TYPE_CHECKING:
    import pytest


def test_defaults_and_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    s = AppSettings.defaults()
    assert s.schedule_hour == 5
    assert s.schedule_minute == 0
    assert s.retention_days is None
    assert s.cl_policies["WIP"] == ClPolicy.SYNC_AND_OPEN.value
    assert s.shotgrid_query_path == "configs/default_shotgrid_query.json"
    save_settings(path, s)
    loaded = load_settings(path)
    assert loaded.staging_root == s.staging_root
    assert loaded.cl_policies["Source Art"] == ClPolicy.SYNC_ONLY.value


def test_resolve_shotgrid_query_path_prefers_app_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Relative query path resolves under app data (LOCALAPPDATA) before CWD."""
    app_data = tmp_path / "ReviewPrep"
    under_app = app_data / "configs" / "default_shotgrid_query.json"
    under_app.parent.mkdir(parents=True)
    under_app.write_text('{"entity_type":"Asset","filters":[]}\n', encoding="utf-8")

    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "configs").mkdir()
    (cwd / "configs" / "default_shotgrid_query.json").write_text('{"entity_type":"Wrong"}\n', encoding="utf-8")
    monkeypatch.chdir(cwd)

    resolved = resolve_shotgrid_query_path("configs/default_shotgrid_query.json", app_data=app_data)
    assert resolved == under_app
