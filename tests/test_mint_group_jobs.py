"""tests for processing Flightdeck mint_group jobs."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import event, create_engine

from red_team_prop_threader.tables import Base
from red_team_prop_threader._errors import PermissionDeniedError
from red_team_prop_threader.cl_jobs import MintGroupJob, MintGroupAsset, MintGroupPerson
from red_team_prop_threader.mint_group_jobs import process_mint_group_job


if TYPE_CHECKING:
    from pathlib import Path
    from collections.abc import Generator

    from sqlalchemy.engine import Engine

NOW = datetime(2026, 10, 2, 22, 15, tzinfo=timezone.utc)
URL = "https://respawn.shotgunstudio.com/detail/Asset/"
ED = MintGroupPerson("Eduardo Agostini", "eagostini@respawn.com")
JB = MintGroupPerson("Jared Bosse", "jbosse@ea.com")
NOBODY = MintGroupPerson("Mine Yilmaz-Ulas", "mulas@ea.com")


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    """In-memory sqlite engine with the app schema."""
    e = create_engine("sqlite:///:memory:")

    @event.listens_for(e, "connect")
    def _pragmas(dbapi_conn: Any, _record: object) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(e)
    yield e
    e.dispose()


class FakeSlack:
    """Records posts; channel members are U1 (Eduardo) only."""

    def __init__(self, *, member: bool = True) -> None:
        """Start with no posts; ``member`` controls bot channel membership."""
        self.member = member
        self.posts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self._n = 0
        self.canvas = MagicMock()

    def get_conversation_info(self, channel_id: str) -> dict[str, Any]:
        """Return channel info with the bot membership flag."""
        return {"id": channel_id, "is_member": self.member}

    def get_conversation_members(self, channel_id: str) -> tuple[str, ...]:
        """Only Eduardo is in the channel."""
        return ("U1",)

    def list_users(self, *, team_id: str) -> tuple[dict[str, Any], ...]:
        """Two workspace users."""
        return ({"id": "U1", "real_name": "Eduardo Agostini", "profile": {}}, {"id": "U2", "real_name": "Jared Bosse", "profile": {}})

    def lookup_user_by_email(self, email: str) -> str | None:
        """The bot lacks users:read.email."""
        raise PermissionDeniedError("missing_scope")

    def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Return a minimal user profile."""
        names = {"U1": "Eduardo Agostini", "U2": "Jared Bosse"}
        return {"id": user_id, "profile": {"real_name": names.get(user_id, user_id)}}

    def post_message(self, channel_id: str, *, text: str, blocks: Any = None, thread_ts: str | None = None) -> dict[str, Any]:
        """Record a post and return a fresh ts."""
        self._n += 1
        ts = f"1000.{self._n:04d}"
        self.posts.append({"channel": channel_id, "text": text, "blocks": blocks, "thread_ts": thread_ts, "ts": ts})
        return {"ts": ts}

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: Any = None) -> dict[str, Any]:
        """Record a chat.update."""
        self.updates.append({"channel": channel_id, "ts": ts, "text": text, "blocks": blocks})
        return {"ts": ts}

    def delete_message(self, channel_id: str, ts: str) -> None:
        """Remove a recorded post, as chat.delete would."""
        self.posts = [post for post in self.posts if not (post["channel"] == channel_id and post["ts"] == ts)]

    def get_permalink(self, channel_id: str, message_ts: str) -> str:
        """Build a Slack archive permalink."""
        return f"https://respawn.slack.com/archives/{channel_id}/p{message_ts.replace('.', '')}"


def _job(mode: str = "live", assets: tuple[MintGroupAsset, ...] | None = None, job_id: str = "j1") -> MintGroupJob:
    return MintGroupJob(
        job_id=job_id,
        mode=mode,
        test_channel_id="C0B4GJSA1G8",
        tab_title="S32 KC_MU5",
        season_id="S32",
        sent_by="jgreen2",
        group_title="S32 KCMU5 OS Assets",
        channel_id="C02PR101SGH",
        creative_stakeholder=ED,
        additional_stakeholders=(),
        assets=assets
        or (
            MintGroupAsset(38885, "unearthed_king_foundation_02", f"{URL}38885", (JB,), (NOBODY,), None),
            MintGroupAsset(39302, "unearthed_king_foundation_03", f"{URL}39302", (), (), 38885),
        ),
    )


def _run(tmp_path: Path, engine: Engine | None, slack: FakeSlack, job: MintGroupJob, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    inbox = tmp_path / "slack_jobs" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    job_path = inbox / f"{job.job_id}.json"
    job_path.write_text(json.dumps({"kind": "mint_group", "job_id": job.job_id}), encoding="utf-8")
    monkeypatch.setattr("red_team_prop_threader.mint_group_jobs.CanvasService", lambda _slack: slack.canvas)
    slack.canvas.ensure_canvas.return_value = "F1"
    return process_mint_group_job(
        job_path,
        job,
        slack=slack,  # type: ignore[arg-type]
        engine=engine,
        jobs_root=tmp_path,
        team_id="T0297NTAU",
        workspace_id="T0297NTAU",
        now=NOW,
    )


def test_live_creates_group_root_and_shared_reply(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Live: top post, IC POC root, shared reply, spokes, index, sent.json."""
    slack = FakeSlack()
    result = _run(tmp_path, engine, slack, _job(), monkeypatch)
    assert result["status"] == "done_with_issues"
    assert result["group"]["outcome"] == "created"
    top, root, reply = slack.posts
    assert top["channel"] == "C02PR101SGH"
    assert top["thread_ts"] is None
    assert "*1* asset(s) included." in json.dumps(top["blocks"])
    assert "*IC POC:* <@U2>" in json.dumps(root["blocks"])
    assert reply["thread_ts"] == root["ts"]
    assert reply["text"] == "Also tracked here: unearthed_king_foundation_03 (ShotGrid ID: 39302)"
    outcomes = {a["asset_id"]: a for a in result["assets"]}
    assert outcomes[38885]["outcome"] == "created"
    assert outcomes[38885]["not_tagged"] == ["Mine Yilmaz-Ulas"]
    assert "mentioned, not in channel: Jared Bosse" in outcomes[38885]["notes"]
    assert outcomes[39302]["outcome"] == "shared"
    season = json.loads((tmp_path / "slack_threads" / "S32.json").read_text(encoding="utf-8"))
    assert season["assets"]["39302"]["thread_ts"] == root["ts"]
    assert season["assets"]["38885"]["source"] == "mint"
    slack.canvas.index_batch.assert_called_once()
    indexed = slack.canvas.index_batch.call_args.args[0]
    assert sorted(a.entity_id for a in indexed.assets) == [38885, 39302]
    sent = json.loads((tmp_path / "slack_jobs" / "sent.json").read_text(encoding="utf-8"))
    assert "j1" in sent["38885"]
    assert "j1" in sent["39302"]
    assert (tmp_path / "slack_jobs" / "done" / "j1.result.json").is_file()
    assert (tmp_path / "slack_jobs" / "done" / "j1.json").is_file()


def test_live_join_updates_count_and_skips_threaded(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """A second job joins the group, skips threaded assets, and bumps the count."""
    slack = FakeSlack()
    _run(tmp_path, engine, slack, _job(assets=(MintGroupAsset(1, "a", f"{URL}1", (JB,), (), None),)), monkeypatch)
    first_top_ts = slack.posts[0]["ts"]
    slack.posts.clear()
    assets = (MintGroupAsset(1, "a", f"{URL}1", (JB,), (), None), MintGroupAsset(2, "b", f"{URL}2", (JB,), (), None))
    result = _run(tmp_path, engine, slack, _job(assets=assets, job_id="j2"), monkeypatch)
    assert result["group"]["outcome"] == "joined"
    assert len(slack.posts) == 1
    assert slack.posts[0]["thread_ts"] is None
    assert {a["asset_id"]: a["outcome"] for a in result["assets"]} == {1: "skipped", 2: "created"}
    assert slack.updates[-1]["ts"] == first_top_ts
    assert "*2* asset(s) included." in json.dumps(slack.updates[-1]["blocks"])


def test_test_mode_plain_names_and_test_folder(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test mode posts to the test channel with plain names and test spokes only."""
    slack = FakeSlack()
    result = _run(tmp_path, engine, slack, _job(mode="test"), monkeypatch)
    assert {p["channel"] for p in slack.posts} == {"C0B4GJSA1G8"}
    everything = json.dumps([p["blocks"] for p in slack.posts if p["blocks"]])
    assert "<@" not in everything
    assert "Jared Bosse (jbosse@ea.com) - would tag U2 (via name)" in everything
    assert (tmp_path / "slack_threads_test" / "S32.json").is_file()
    assert not (tmp_path / "slack_threads").exists()
    assert not (tmp_path / "slack_jobs" / "sent.json").exists()
    slack.canvas.index_batch.assert_not_called()
    assert result["destination"] == "C0B4GJSA1G8"


def test_dry_run_writes_preview_only(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dry run posts nothing, writes no records, and leaves a preview file."""
    slack = FakeSlack()
    result = _run(tmp_path, engine, slack, _job(mode="dry_run"), monkeypatch)
    assert slack.posts == []
    preview = json.loads((tmp_path / "slack_jobs" / "done" / "j1.preview.json").read_text(encoding="utf-8"))
    assert len(preview["posts"]) == 3
    assert preview["group_outcome"] == "created"
    assert not (tmp_path / "slack_threads").exists()
    assert result["status"] in {"done", "done_with_issues"}
    second = _run(tmp_path, engine, FakeSlack(), _job(mode="dry_run", job_id="j2"), monkeypatch)
    assert second["group"]["outcome"] == "created"


def test_shared_only_job_posts_no_top_post(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no new roots and no existing group, no top post is created."""
    slack = FakeSlack()
    result = _run(tmp_path, engine, slack, _job(assets=(MintGroupAsset(5, "x", f"{URL}5", (), (), 999),)), monkeypatch)
    assert result["group"]["outcome"] == "not_needed"
    assert slack.posts == []
    assert result["assets"][0]["outcome"] == "failed"
    assert result["assets"][0]["error"] == "Shared thread target not found"


def test_database_lock_after_group_post_removes_it(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """A database failure after the group header deletes that header and posts no threads."""
    from red_team_prop_threader.repositories import HistoryRepository

    original = HistoryRepository.record
    calls = {"n": 0}

    def _record(self: HistoryRepository, inp: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return original(self, inp)

    monkeypatch.setattr(HistoryRepository, "record", _record)
    slack = FakeSlack()
    result = _run(tmp_path, engine, slack, _job(), monkeypatch)
    assert result["status"] == "failed"
    assert "database is locked" in result["error"]
    assert slack.posts == []
    assert result["group"]["permalink"] == ""
    assert all(asset["outcome"] == "" for asset in result["assets"])


def test_bot_not_in_channel_fails_job(tmp_path: Path, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """A channel without the bot fails the whole job and records failed.json."""
    slack = FakeSlack(member=False)
    result = _run(tmp_path, engine, slack, _job(), monkeypatch)
    assert (result["status"], result["error"]) == ("failed", "Bot not in channel")
    assert slack.posts == []
    failed = json.loads((tmp_path / "slack_jobs" / "failed.json").read_text(encoding="utf-8"))
    assert failed[0]["job_id"] == "j1"
    assert failed[0]["error"] == "Bot not in channel"
    assert (tmp_path / "slack_jobs" / "done" / "j1.json").is_file()
