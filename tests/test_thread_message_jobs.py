"""tests for thread_message inbox drain (reply + uploads, no mint)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from red_team_prop_threader._errors import ExternalServiceError
from red_team_prop_threader.cl_jobs import parse_job
from red_team_prop_threader.thread_message_jobs import drain_thread_message_inbox, process_thread_message_job


if TYPE_CHECKING:
    from pathlib import Path


def _write_thread_job(
    inbox: Path,
    *,
    job_id: str = "j",
    body: str = "hi",
    images: list[str] | None = None,
    spoke_channel_id: str = "C1",
    spoke_thread_ts: str = "1.2",
    asset_id: int = 38864,
) -> Path:
    """Write a ReviewPrep thread_message JSON into inbox."""
    payload = {
        "kind": "thread_message",
        "job_id": job_id,
        "asset_id": asset_id,
        "body": body,
        "images": images if images is not None else [],
        "spoke_channel_id": spoke_channel_id,
        "spoke_thread_ts": spoke_thread_ts,
    }
    path = inbox / f"{job_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_body_and_two_files_posts_once_and_uploads_twice(tmp_path: Path) -> None:
    """Non-empty body posts once, then each images[] file uploads in order."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    images = ["j_0.png", "j_1.png"]
    _write_thread_job(inbox, images=images)
    (inbox / "j_0.png").write_bytes(b"one")
    (inbox / "j_1.png").write_bytes(b"two")
    slack = MagicMock()
    job = parse_job(inbox / "j.json")
    assert job is not None

    with patch("red_team_prop_threader.mint_from_job.process_job") as mint_job:
        process_thread_message_job(job, inbox=inbox, slack=slack, jobs_root=tmp_path)
        mint_job.assert_not_called()

    slack.post_message.assert_called_once_with("C1", text="hi", thread_ts="1.2")
    assert slack.upload_file.call_count == 2
    slack.upload_file.assert_any_call("C1", file_path=inbox / "j_0.png", thread_ts="1.2")
    slack.upload_file.assert_any_call("C1", file_path=inbox / "j_1.png", thread_ts="1.2")
    sent = json.loads((tmp_path / "slack_jobs" / "sent.json").read_text(encoding="utf-8"))
    assert sent["38864"] == ["j"]
    done = tmp_path / "slack_jobs" / "done"
    assert (done / "j.json").is_file()
    assert (done / "j_0.png").is_file()
    assert (done / "j_1.png").is_file()
    assert not (inbox / "j.json").exists()


def test_missing_spoke_writes_failed_and_zero_slack_calls(tmp_path: Path) -> None:
    """Blank spoke ids fail without posting, uploading, minting, or stamping sent."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    _write_thread_job(inbox, spoke_channel_id="", spoke_thread_ts="")
    slack = MagicMock()
    job = parse_job(inbox / "j.json")
    assert job is not None

    with patch("red_team_prop_threader.mint_from_job.process_job") as mint_job:
        process_thread_message_job(job, inbox=inbox, slack=slack, jobs_root=tmp_path)
        mint_job.assert_not_called()

    slack.post_message.assert_not_called()
    slack.upload_file.assert_not_called()
    failed = json.loads((tmp_path / "slack_jobs" / "failed.json").read_text(encoding="utf-8"))
    assert failed[0]["error"] == "Missing Slack thread"
    assert not (tmp_path / "slack_jobs" / "sent.json").exists()


def test_upload_failure_moves_job_off_inbox(tmp_path: Path) -> None:
    """Upload errors must not leave JSON in inbox or a later tick will spam the thread."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    _write_thread_job(inbox, images=["j_0.png"])
    (inbox / "j_0.png").write_bytes(b"img")
    slack = MagicMock()
    slack.upload_file.side_effect = ExternalServiceError("upload failed")
    job = parse_job(inbox / "j.json")
    assert job is not None

    process_thread_message_job(job, inbox=inbox, slack=slack, jobs_root=tmp_path)
    drain_thread_message_inbox(tmp_path, slack)

    slack.post_message.assert_called_once_with("C1", text="hi", thread_ts="1.2")
    assert not (inbox / "j.json").exists()
    assert (tmp_path / "slack_jobs" / "done" / "j.json").is_file()
    failed = json.loads((tmp_path / "slack_jobs" / "failed.json").read_text(encoding="utf-8"))
    assert failed[0]["error"] == "upload failed"
    assert not (tmp_path / "slack_jobs" / "sent.json").exists()


def test_old_post_cl_json_writes_unsupported(tmp_path: Path) -> None:
    """Legacy Post CL JSON is failed, moved to done, and never posted or minted."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "old.json").write_text(
        json.dumps({"job_id": "old", "asset_id": 1, "cls": [{"label": "WIP", "number": 99}], "image_filename": "old.png"}), encoding="utf-8"
    )
    (inbox / "old.png").write_bytes(b"img")
    slack = MagicMock()

    with patch("red_team_prop_threader.mint_from_job.process_cl_jobs") as mint:
        drain_thread_message_inbox(tmp_path, slack)
        mint.assert_not_called()

    slack.post_message.assert_not_called()
    slack.upload_file.assert_not_called()
    failed = json.loads((tmp_path / "slack_jobs" / "failed.json").read_text(encoding="utf-8"))
    assert failed[0]["error"] == "Unsupported job; send Thread Message"
    done = tmp_path / "slack_jobs" / "done"
    assert (done / "old.json").is_file()
    assert (done / "old.png").is_file()
    assert not (inbox / "old.json").exists()


def test_drain_posts_thread_message_job_from_inbox(tmp_path: Path) -> None:
    """Worker helper lists inbox JSON and processes thread_message jobs."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    _write_thread_job(inbox, body="hello", images=[])
    slack = MagicMock()

    with patch("red_team_prop_threader.mint_from_job.process_cl_jobs") as mint:
        drain_thread_message_inbox(tmp_path, slack)
        mint.assert_not_called()

    slack.post_message.assert_called_once_with("C1", text="hello", thread_ts="1.2")
    slack.upload_file.assert_not_called()
    sent = json.loads((tmp_path / "slack_jobs" / "sent.json").read_text(encoding="utf-8"))
    assert sent["38864"] == ["j"]


def test_worker_tick_drains_thread_message_and_does_not_mint() -> None:
    """Each worker tick drains thread_message jobs and never calls mint."""
    from red_team_prop_threader.jobs import ExecutionResult
    from red_team_prop_threader.config import Settings
    from red_team_prop_threader.worker import run_forever
    from red_team_prop_threader.repositories import BatchStatus

    settings = Settings(
        slack_bot_token="xoxb-test",
        slack_signing_secret="secret",
        slack_app_token="xapp-test",
        shotgrid_script_name="script",
        shotgrid_script_key="key",
        shotgrid_url="https://respawn.shotgunstudio.com",
        slack_public_base_url="https://prop-threader-dev.example.invalid",
        shotgrid_test_page_id=23280,
        database_url="sqlite:///:memory:",
        test_postgres_url=None,
        canvas_timezone="America/Los_Angeles",
        web_host="127.0.0.1",
        web_port=3000,
        worker_poll_seconds=0,
        tunnel_command=None,
        tunnel_health_url=None,
        primary_asset_index_channel_id="C04H4QZEYUE",
        primary_asset_index_canvas_id="F0BKLFG5S0M",
    )
    executor = MagicMock()
    executor.run_once.return_value = ExecutionResult(batch_id="b1", status=BatchStatus.SUCCEEDED, failed_operation=None)

    with (
        patch("red_team_prop_threader.worker.build_engine", return_value=MagicMock()),
        patch("red_team_prop_threader.worker.session_scope") as session_scope,
        patch("red_team_prop_threader.worker.SlackGateway.from_settings"),
        patch("red_team_prop_threader.worker.BatchExecutor", return_value=executor),
        patch("red_team_prop_threader.worker.Repositories.from_session"),
        patch("red_team_prop_threader.worker.ChannelLeaseRepository"),
        patch("red_team_prop_threader.worker.drain_thread_message_inbox") as drain,
        patch("red_team_prop_threader.mint_from_job.process_cl_jobs") as mint,
    ):
        session_scope.return_value.__enter__.return_value = MagicMock()
        session_scope.return_value.__exit__.return_value = None
        run_forever(settings=settings, once=True)

    drain.assert_called_once()
    mint.assert_not_called()
    from pathlib import Path

    assert Path(drain.call_args.args[0]) == Path(settings.reviewprep_external_links_root)
    assert drain.call_args.args[1] is not None
