"""tests for mint_from_job."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock


if TYPE_CHECKING:
    from pathlib import Path

from red_team_prop_threader._errors import ExternalServiceError
from red_team_prop_threader.mint_from_job import process_cl_jobs
from red_team_prop_threader.slack_gateway import SlackGateway


def test_skip_mint_when_spoke_exists(tmp_path: Path) -> None:
    """Test skip mint when spoke exists."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    
    job_path = inbox / "job1.json"
    job_data = {
        "job_id": "job1",
        "asset_id": "123",
        "cls": [100],
        "body": "Hello",
        "spoke_channel_id": "C1",
        "spoke_thread_ts": "100.1",
        "image_filename": "job1.jpg"
    }
    job_path.write_text(json.dumps(job_data))
    (inbox / "job1.jpg").write_text("image")
    
    slack = MagicMock(spec=SlackGateway)
    slack._call.return_value = {"messages": []}  # no existing replies
    
    process_cl_jobs(tmp_path, slack)
    
    slack.post_message.assert_called_once_with("C1", text="Hello", thread_ts="100.1")
    slack.upload_file.assert_called_once_with("C1", file_path=inbox / "job1.jpg", thread_ts="100.1")
    
    # Verify sent stamp and moved to done
    sent = json.loads((tmp_path / "slack_jobs" / "sent.json").read_text())
    assert "100" in sent["123"]
    assert not job_path.exists()
    assert (tmp_path / "slack_jobs" / "done" / "job1.json").exists()

def test_upload_fail_does_not_stamp(tmp_path: Path) -> None:
    """Test upload fail does not stamp sent."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    
    job_path = inbox / "job2.json"
    job_data = {
        "job_id": "job2",
        "asset_id": "124",
        "cls": [101],
        "body": "Hello 2",
        "spoke_channel_id": "C1",
        "spoke_thread_ts": "100.1",
        "image_filename": "job2.jpg"
    }
    job_path.write_text(json.dumps(job_data))
    (inbox / "job2.jpg").write_text("image")
    
    slack = MagicMock(spec=SlackGateway)
    slack._call.return_value = {"messages": []}
    slack.upload_file.side_effect = ExternalServiceError("upload failed")
    
    process_cl_jobs(tmp_path, slack)
    
    slack.post_message.assert_called_once_with("C1", text="Hello 2", thread_ts="100.1")
    slack.upload_file.assert_called_once_with("C1", file_path=inbox / "job2.jpg", thread_ts="100.1")
    
    # Should not stamp sent
    assert not (tmp_path / "slack_jobs" / "sent.json").exists()
    # Failed.json should have entry
    failed = json.loads((tmp_path / "slack_jobs" / "failed.json").read_text())
    assert failed[0]["error"] == "upload failed"
    # Should leave inbox file
    assert job_path.exists()

def test_reply_already_posted_skips_post_message(tmp_path: Path) -> None:
    """Test reply already posted skips post message."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    
    job_path = inbox / "job3.json"
    job_data = {
        "job_id": "job3",
        "asset_id": "125",
        "cls": [102],
        "body": "Duplicate body",
        "spoke_channel_id": "C1",
        "spoke_thread_ts": "100.1",
        "image_filename": "job3.jpg"
    }
    job_path.write_text(json.dumps(job_data))
    (inbox / "job3.jpg").write_text("image")
    
    slack = MagicMock(spec=SlackGateway)
    slack._call.return_value = {"messages": [{"text": "Duplicate body"}]}
    
    process_cl_jobs(tmp_path, slack)
    
    # Post message NOT called
    slack.post_message.assert_not_called()
    # Upload file called
    slack.upload_file.assert_called_once_with("C1", file_path=inbox / "job3.jpg", thread_ts="100.1")
    
    sent = json.loads((tmp_path / "slack_jobs" / "sent.json").read_text())
    assert "102" in sent["125"]

def test_mint_skipped_when_spoke_set(tmp_path: Path) -> None:
    """Test mint skipped when spoke set."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    
    job_path = inbox / "job_skip_mint.json"
    job_data = {
        "job_id": "job_skip",
        "asset_id": "999",
        "channel": "C999",
        "spoke_channel_id": "C999",
        "spoke_thread_ts": "999.9"
    }
    job_path.write_text(json.dumps(job_data))
    
    slack = MagicMock()
    slack._call.return_value = {"messages": []}
    
    process_cl_jobs(tmp_path, slack, engine=None)
    
    # post_message is not called because no body
    # But it did not write failed.json for "no database for mint"
    assert not (tmp_path / "slack_jobs" / "failed.json").exists()

def test_mint_requires_engine(tmp_path: Path) -> None:
    """Test mint fails nicely without engine."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    
    job_path = inbox / "job_needs_mint.json"
    job_data = {
        "job_id": "job_nm",
        "asset_id": "888",
        "channel": "C888"
    }
    job_path.write_text(json.dumps(job_data))
    
    slack = MagicMock()
    slack._call.return_value = {"messages": []}
    
    process_cl_jobs(tmp_path, slack, engine=None)
    
    failed = json.loads((tmp_path / "slack_jobs" / "failed.json").read_text())
    assert failed[0]["error"] == "no database for mint"
    
def test_mint_creates_group_and_roots(tmp_path: Path) -> None:
    """Test actual mint against sqlite."""
    from sqlalchemy import create_engine

    from red_team_prop_threader.tables import Base
    
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    
    job_path = inbox / "job_mint_db.json"
    job_data = {
        "job_id": "job_db",
        "asset_id": "777",
        "channel": "C777",
        "group_title": "DB Mint Test",
        "season_id": "S2",
        "body": "Hi there"
    }
    job_path.write_text(json.dumps(job_data))
    
    slack = MagicMock()
    slack._call.return_value = {"messages": []}
    slack.get_conversation_members.return_value = []
    slack.post_message.return_value = {"ts": "123.45"}
    slack.get_permalink.return_value = "https://example.com"
    
    process_cl_jobs(tmp_path, slack, engine=engine)
    
    # Verify the thread was created
    assert slack.post_message.call_count == 3 # 1 group summary, 1 asset root, 1 reply
    
    # Check season file was written
    season = json.loads((tmp_path / "slack_threads" / "S2.json").read_text(encoding="utf-8-sig"))
    assert season["assets"]["777"]["source"] == "mint"

def test_skip_mint_when_season_has_asset(tmp_path: Path) -> None:
    """Test skip mint when season has asset."""
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True)
    
    job_path = inbox / "job4.json"
    job_data = {
        "job_id": "job4",
        "asset_id": "126",
        "season_id": "S1",
        "cls": [103],
        "body": "Hello 4",
        # missing spoke_channel_id and spoke_thread_ts, will read from season
    }
    job_path.write_text(json.dumps(job_data))
    
    slack_threads = tmp_path / "slack_threads"
    slack_threads.mkdir(parents=True)
    (slack_threads / "S1.json").write_text(json.dumps({
        "season_id": "S1",
        "assets": {
            "126": {
                "channel_id": "C2",
                "thread_ts": "200.2"
            }
        }
    }))
    
    slack = MagicMock(spec=SlackGateway)
    slack._call.return_value = {"messages": []}
    
    process_cl_jobs(tmp_path, slack)
    
    slack.post_message.assert_called_once_with("C2", text="Hello 4", thread_ts="200.2")
    sent = json.loads((tmp_path / "slack_jobs" / "sent.json").read_text())
    assert "103" in sent["126"]
