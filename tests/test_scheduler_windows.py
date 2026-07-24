"""Tests for Windows Task Scheduler helpers and worker dry-run."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from review_prep.orchestrator import PrepRunResult
from review_prep.scheduler_windows import (
    DAILY_TASK_NAME,
    LOGON_TASK_NAME,
    _daily_task_xml,
    register_daily_task,
    register_logon_trigger,
)
from review_prep.settings import AppSettings, save_settings
from review_prep.worker_main import main, settings_path


if TYPE_CHECKING:
    import pytest


def test_register_daily_task_builds_schtasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Daily registration creates via /XML with StartWhenAvailable catch-up."""
    calls: list[list[str]] = []
    xml_snapshots: list[str] = []

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        calls.append(list(cmd))
        xml_path = Path(cmd[cmd.index("/XML") + 1])
        xml_snapshots.append(xml_path.read_text(encoding="utf-16"))
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    monkeypatch.setattr("review_prep.scheduler_windows.subprocess.run", fake_run)
    monkeypatch.setattr("review_prep.scheduler_windows.getpass.getuser", lambda: "testuser")

    register_daily_task(r"C:\Apps\review-prep-worker.exe", hour=5, minute=0)

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "schtasks"
    assert "/Create" in cmd
    assert "/F" in cmd
    assert cmd[cmd.index("/TN") + 1] == DAILY_TASK_NAME
    assert "/XML" in cmd
    xml_body = xml_snapshots[0]
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml_body
    assert r"C:\Apps\review-prep-worker.exe" in xml_body
    assert "<Command>" in xml_body
    assert "05:00:00" in xml_body
    assert "testuser" in xml_body
    assert "LeastPrivilege" in xml_body


def test_daily_task_xml_includes_start_when_available() -> None:
    """Generated task XML enables StartWhenAvailable for missed-run catch-up."""
    xml_body = _daily_task_xml(Path(r"C:\Apps\worker.exe"), hour=5, minute=0, user="alice")
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml_body
    assert "<Command>C:\\Apps\\worker.exe</Command>" in xml_body
    assert "2000-01-01T05:00:00" in xml_body


def test_register_daily_task_custom_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom hour/minute land in the CalendarTrigger StartBoundary."""
    calls: list[list[str]] = []
    xml_snapshots: list[str] = []

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        calls.append(list(cmd))
        xml_path = Path(cmd[cmd.index("/XML") + 1])
        xml_snapshots.append(xml_path.read_text(encoding="utf-16"))
        return MagicMock(returncode=0)

    monkeypatch.setattr("review_prep.scheduler_windows.subprocess.run", fake_run)
    monkeypatch.setattr("review_prep.scheduler_windows.getpass.getuser", lambda: "u")

    register_daily_task(Path(r"D:\bin\worker.exe"), hour=6, minute=30)

    assert "06:30:00" in xml_snapshots[0]
    assert r"D:\bin\worker.exe" in xml_snapshots[0]


def test_register_logon_trigger_builds_schtasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Logon registration uses ONLOGON and an unquoted absolute /TR path."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "review_prep.scheduler_windows.subprocess.run",
        lambda cmd, **kwargs: calls.append(list(cmd)) or MagicMock(returncode=0),
    )
    monkeypatch.setattr("review_prep.scheduler_windows.getpass.getuser", lambda: "testuser")

    register_logon_trigger(r"C:\Apps\review-prep.exe")

    cmd = calls[0]
    assert cmd[cmd.index("/TN") + 1] == LOGON_TASK_NAME
    assert cmd[cmd.index("/SC") + 1] == "ONLOGON"
    assert cmd[cmd.index("/TR") + 1] == r"C:\Apps\review-prep.exe"
    assert cmd[cmd.index("/RU") + 1] == "testuser"


def test_worker_dry_run_monkeypatches_orchestrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker loads settings/DB under LOCALAPPDATA and exits 0 when orchestrator succeeds."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    settings = AppSettings.defaults()
    settings.staging_root = str(tmp_path / "staging")
    settings.p4_client = "everyday"
    settings.shotgrid_script_name = "script"
    save_settings(settings_path(), settings)
    (tmp_path / "staging").mkdir()

    monkeypatch.setattr("review_prep.worker_main.wire_adapters", lambda _settings: (MagicMock(name="shotgun"), MagicMock(name="p4")))

    class FakeOrchestrator:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def run_worklist(self) -> PrepRunResult:
            return PrepRunResult(prep_run_id=1, local_date="2026-07-24", hard_failure=False)

    monkeypatch.setattr("review_prep.worker_main.PrepOrchestrator", FakeOrchestrator)

    assert main([]) == 0
    assert (tmp_path / "ReviewPrep" / "prep.db").is_file() or (tmp_path / "ReviewPrep").is_dir()


def test_worker_hard_failure_exits_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker returns exit code 1 when orchestrator reports hard_failure."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_settings(settings_path(), AppSettings.defaults())
    monkeypatch.setattr("review_prep.worker_main.wire_adapters", lambda _settings: (MagicMock(), MagicMock()))

    class FailOrchestrator:
        def __init__(self, **kwargs: object) -> None:
            pass

        def run_worklist(self) -> PrepRunResult:
            return PrepRunResult(prep_run_id=2, local_date="2026-07-24", hard_failure=True, errors=["bad staging"])

    monkeypatch.setattr("review_prep.worker_main.PrepOrchestrator", FailOrchestrator)

    assert main() == 1
