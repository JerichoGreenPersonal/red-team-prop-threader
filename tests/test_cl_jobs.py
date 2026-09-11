import json
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from red_team_prop_threader._errors import NotFoundError, RetryableExternalServiceError
from red_team_prop_threader.cl_jobs import sent_has, parse_job, list_inbox, stamp_sent, move_to_done, write_failed, resolve_channel
from red_team_prop_threader.slack_gateway import SlackGateway


if TYPE_CHECKING:
    from pathlib import Path


def test_parse_job(tmp_path: "Path") -> None:
    """Test parsing a valid job JSON."""
    job_path = tmp_path / "job1.json"
    job_path.write_text(
        json.dumps({
            "job_id": "job_123",
            "asset_id": "asset_123",
            "cls": [{"label": "CL", "number": 12345}],
            "channel": "#r5-test",
            "image_filename": "job_123.jpg",
            "additional_stakeholders": ["jgreen2", "someone"],
        }),
        encoding="utf-8",
    )

    job = parse_job(job_path)
    assert job is not None
    assert job.job_id == "job_123"
    assert job.asset_id == "asset_123"
    assert job.channel == "#r5-test"
    assert job.image_filename == "job_123.jpg"
    assert len(job.cls) == 1
    assert job.cls[0] == 12345
    assert job.additional_stakeholders == ("jgreen2", "someone")


def test_parse_job_reviewprep_242_handles_not_ids(tmp_path: "Path") -> None:
    """ReviewPrep 2.4.2 jobs use handles; *_id keys are ignored and not required."""
    job_path = tmp_path / "job_242.json"
    job_path.write_text(
        json.dumps({
            "job_id": "uuid-123",
            "asset_id": 777,
            "version_id": 123,
            "season_id": "S2",
            "cls": [{"label": "WIP CL", "number": 12345}],
            "body": "canned line",
            "template_id": "default",
            "image_filename": "uuid-123.jpg",
            "channel": "C777",
            "group_title": "DB Mint Test",
            "creative_stakeholder": "@alice",
            "additional_stakeholders": ["U012ABC"],
            "spoke_channel_id": "C777",
            "spoke_thread_ts": "777.7",
            "creative_stakeholder_id": "UWRONG",
            "ic_poc_id": "UALSOWRONG",
        }),
        encoding="utf-8",
    )

    job = parse_job(job_path)
    assert job is not None
    assert job.creative_stakeholder == "@alice"
    assert job.additional_stakeholders == ("U012ABC",)
    assert job.ic_poc is None
    assert job.additional_ics is None
    assert not hasattr(job, "creative_stakeholder_id")
    assert not hasattr(job, "ic_poc_id")


def test_parse_job_optional_ic_poc_handles(tmp_path: "Path") -> None:
    """Later jobs may add ic_poc / additional_ics handles without requiring *_id."""
    job_path = tmp_path / "job_ic.json"
    job_path.write_text(
        json.dumps({"job_id": "job_ic", "asset_id": "1", "creative_stakeholder": "", "ic_poc": "@alice", "additional_ics": ["bob"]}), encoding="utf-8"
    )

    job = parse_job(job_path)
    assert job is not None
    assert job.creative_stakeholder == ""
    assert job.ic_poc == "@alice"
    assert job.additional_ics == ("bob",)


def test_parse_job_invalid(tmp_path: "Path") -> None:
    """Test parsing an invalid job JSON."""
    job_path = tmp_path / "job2.json"
    job_path.write_text(json.dumps({"asset_id": "asset_123"}), encoding="utf-8")

    assert parse_job(job_path) is None


def test_list_inbox(tmp_path: "Path") -> None:
    """Test listing jobs in the inbox."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)

    (inbox / "a.json").write_text("{}")
    (inbox / "b.json").write_text("{}")
    (inbox / ".tmp.c.json").write_text("{}")

    paths = list_inbox(tmp_path)
    assert len(paths) == 2
    assert paths[0].name == "a.json"
    assert paths[1].name == "b.json"


def test_sent_has(tmp_path: "Path") -> None:
    """Test checking if an asset_id is sent."""
    sent_path = tmp_path / "slack_jobs" / "sent.json"
    sent_path.parent.mkdir(parents=True)
    sent_path.write_text(json.dumps({"asset_1": ["12345"], "asset_2": ["12345"]}), encoding="utf-8")

    assert sent_has(tmp_path, "asset_1", 12345) is True
    assert sent_has(tmp_path, "asset_3", 12345) is False
    assert sent_has(tmp_path, "asset_1", 99999) is False


def test_stamp_sent(tmp_path: "Path") -> None:
    """Test stamping an asset_id as sent."""
    stamp_sent(tmp_path, "asset_1", [12345, 67890])

    sent_path = tmp_path / "slack_jobs" / "sent.json"
    data = json.loads(sent_path.read_text(encoding="utf-8"))
    assert "asset_1" in data
    assert "12345" in data["asset_1"]
    assert "67890" in data["asset_1"]

    stamp_sent(tmp_path, "asset_2", [12345])
    data = json.loads(sent_path.read_text(encoding="utf-8"))
    assert "asset_2" in data
    assert "12345" in data["asset_2"]
    assert "12345" in data["asset_1"]


def test_write_failed(tmp_path: "Path") -> None:
    """Test writing a failure record."""
    write_failed(tmp_path, "job_1", "asset_1", "timeout")
    failed_path = tmp_path / "slack_jobs" / "failed.json"
    data = json.loads(failed_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1
    entry = data[0]
    assert entry["job_id"] == "job_1"
    assert entry["asset_id"] == "asset_1"
    assert entry["error"] == "timeout"
    assert "at" in entry


def test_resolve_channel() -> None:
    """Test resolving channel identifier via slack gateway."""
    gateway = Mock(spec=SlackGateway)

    assert resolve_channel(gateway, "C123456") == "C123456"
    assert resolve_channel(gateway, "G123456") == "G123456"

    gateway._call.return_value = {"channels": [{"id": "C789", "name": "r5-test"}, {"id": "C999", "name": "other"}]}

    assert resolve_channel(gateway, "#r5-test") == "C789"
    gateway._call.assert_called_once_with("conversations_list", types="public_channel,private_channel", exclude_archived=True, limit=200)

    with pytest.raises(NotFoundError):
        resolve_channel(gateway, "#missing")

    with pytest.raises(NotFoundError):
        resolve_channel(gateway, "invalid")

    gateway._call.side_effect = RetryableExternalServiceError("rate limited")
    with pytest.raises(RetryableExternalServiceError):
        resolve_channel(gateway, "#ratelimited")


def test_move_to_done(tmp_path: "Path") -> None:
    """Test moving job files to done directory."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)

    job_path = inbox / "job1.json"
    job_path.write_text(json.dumps({"job_id": "job1", "image_filename": "img1.jpg"}), encoding="utf-8")

    img_path = inbox / "img1.jpg"
    img_path.write_text("data")

    move_to_done(tmp_path, job_path)

    done_dir = tmp_path / "slack_jobs" / "done"
    assert (done_dir / "job1.json").exists()
    assert (done_dir / "img1.jpg").exists()
    assert not job_path.exists()
    assert not img_path.exists()
