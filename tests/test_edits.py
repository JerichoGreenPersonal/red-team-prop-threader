"""tests for latest-only post-completion asset and group editing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from datetime import datetime, timezone, timedelta
from dataclasses import field, dataclass

import pytest
from sqlalchemy import event, create_engine
from sqlalchemy.orm import Session

from red_team_prop_threader.edits import MessageRef, EditService, AssetEditRequest, GroupEditRequest, decode_edit_submission
from red_team_prop_threader.tables import Base
from red_team_prop_threader._errors import ValidationError, PermissionDeniedError
from red_team_prop_threader.repositories import MessageKind, Repositories, NewMessageInput


if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Engine


_PRIMARY_CHANNEL = "C04H4QZEYUE"


@dataclass
class FakeClock:
    """deterministic utc clock."""

    _now: datetime = field(default_factory=lambda: datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc))

    def now(self) -> datetime:
        """Return current fake instant."""
        return self._now

    def advance(self, *, minutes: int = 0) -> None:
        """Advance the clock."""
        self._now += timedelta(minutes=minutes)


@dataclass
class MessageUpdate:
    """recorded chat.update call."""

    channel_id: str
    ts: str
    text: str
    blocks: list[dict[str, Any]]
    sends_notifications: bool = False


@dataclass
class FakeSlackGateway:
    """slack double for edit tests."""

    members: set[str] = field(default_factory=lambda: {"Ueditor", "Uanim", "Uadd", "Uasset"})
    updates: list[MessageUpdate] = field(default_factory=list)
    canvas_edits: list[dict[str, Any]] = field(default_factory=list)
    opened_views: list[dict[str, Any]] = field(default_factory=list)
    section_lookup_result: list[dict[str, str]] = field(default_factory=list)
    channel_canvas_ids: dict[str, str] = field(default_factory=dict)
    fail_edit_canvas_id: str | None = None

    @property
    def updated_summary(self) -> MessageUpdate | None:
        """Return the first summary-looking update."""
        for update in self.updates:
            if update.text.startswith("Group summary:"):
                return update
        return None

    @property
    def updated_latest_roots(self) -> list[MessageUpdate]:
        """Return updates that look like asset roots."""
        return [update for update in self.updates if "Asset:" in update.text]

    def open_view(self, trigger_id: str, view: dict[str, Any]) -> dict[str, Any]:
        """Record an opened modal."""
        del trigger_id
        self.opened_views.append(view)
        return {"ok": True}

    def update_message(self, channel_id: str, ts: str, *, text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Record a non-notifying message update."""
        self.updates.append(MessageUpdate(channel_id=channel_id, ts=ts, text=text, blocks=blocks or [], sends_notifications=False))
        return {"ok": True}

    def get_conversation_members(self, channel_id: str) -> tuple[str, ...]:
        """Return configured channel members."""
        del channel_id
        return tuple(sorted(self.members))

    def get_user_info(self, user_id: str) -> dict[str, object]:
        """Return a display name profile."""
        return {
            "id": user_id,
            "name": user_id.lower(),
            "is_bot": False,
            "profile": {"display_name": f"Name {user_id}", "real_name": f"Name {user_id}"},
        }

    def lookup_sections(self, canvas_id: str, *, contains_text: str | None = None, section_types: tuple[str, ...] = ("any_header",)) -> list[dict[str, str]]:
        """Return canvas sections for group replace."""
        del canvas_id, contains_text, section_types
        return list(self.section_lookup_result) or [{"id": "Sgroup", "type": "h2"}]

    def edit_canvas(self, canvas_id: str, *, operation: str, markdown: str | None = None, section_id: str | None = None, title: str | None = None) -> None:
        """Record canvas edits from group updates."""
        if self.fail_edit_canvas_id and canvas_id == self.fail_edit_canvas_id:
            raise PermissionDeniedError(f"edit_canvas denied for {canvas_id}")
        self.canvas_edits.append({"canvas_id": canvas_id, "operation": operation, "markdown": markdown, "section_id": section_id, "title": title})

    def get_conversation_info(self, channel_id: str) -> dict[str, object]:
        """Return channel info with a canvas id."""
        canvas_id = self.channel_canvas_ids.get(channel_id, "Fcanvas")
        return {"id": channel_id, "properties": {"canvas": {"file_id": canvas_id, "is_empty": False}}}

    def get_file_info(self, file_id: str) -> dict[str, object]:
        """Return canvas file metadata."""
        if file_id == "Fprimary":
            return {"id": file_id, "title": "PRIMARY ASSET INDEX", "name": "PRIMARY ASSET INDEX"}
        return {"id": file_id, "title": "INDEX OF PROP REQUESTS", "name": "INDEX OF PROP REQUESTS"}

    def create_channel_canvas(self, channel_id: str, *, title: str) -> str:
        """Create a channel canvas for preflight tests."""
        del channel_id, title
        return "Fcanvas"

    def rename_canvas(self, canvas_id: str, *, title: str) -> None:
        """Rename a canvas for preflight tests."""
        del canvas_id, title


@pytest.fixture
def engine() -> Generator[Engine, None, None]:
    """in-memory sqlite engine."""
    e = create_engine("sqlite:///:memory:")

    @event.listens_for(e, "connect")
    def _pragmas(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    """Open session."""
    with Session(engine) as sess:
        yield sess


@pytest.fixture
def clock() -> FakeClock:
    """Clock fixture."""
    return FakeClock()


@pytest.fixture
def fake_slack() -> FakeSlackGateway:
    """Slack double."""
    return FakeSlackGateway()


@pytest.fixture
def repositories(session: Session) -> Repositories:
    """Repository bundle."""
    return Repositories.from_session(session)


@pytest.fixture
def edit_service(repositories: Repositories, fake_slack: FakeSlackGateway, clock: FakeClock) -> EditService:
    """Edit service under test."""
    return EditService(repositories=repositories, slack=fake_slack, canvas_slack=fake_slack, clock=clock)


def _seed_group(repositories: Repositories, session: Session, clock: FakeClock, *, channel_id: str = "C1") -> str:
    """Create a group and return its id."""
    group = repositories.groups.create(
        workspace_id="W1",
        channel_id=channel_id,
        display_title="SEASON 31 PROP REQUEST THREADS",
        normalized_title="season 31 prop request threads",
        now=clock.now(),
    )
    session.flush()
    return group.id


def _asset_snapshot(entity_id: int) -> dict[str, Any]:
    """Build editable asset snapshot metadata."""
    return {
        "kind": "asset_root",
        "entity_id": entity_id,
        "asset_name": f"Prop {entity_id}",
        "asset_url": f"https://respawn.shotgunstudio.com/detail/Asset/{entity_id}",
        "group_title": "SEASON 31 PROP REQUEST THREADS",
        "created_ts": 1700000000,
        "asset_animator_id": "Uasset",
        "asset_additional_ids": [],
        "asset_links": [],
        "group_animator_id": "Uanim",
        "group_additional_ids": [],
        "group_links": [{"label": "Brief", "url": "https://example.com/brief"}],
        "group_animator_display": "Name Uanim",
        "group_additional_displays": [],
        "message_identity": f"batch:{entity_id}",
    }


def historical_message(repositories: Repositories, session: Session, clock: FakeClock) -> MessageRef:
    """Seed historical + latest asset roots and return a ref to the historical one."""
    group_id = _seed_group(repositories, session, clock)
    batch = repositories.batches.create(group_id=group_id, workspace_id="W1", channel_id="C1", submitter_user_id="Ueditor", payload={}, now=clock.now())
    session.flush()
    historical = repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group_id,
            batch_id=batch.id,
            kind=MessageKind.ASSET_ROOT,
            asset_entity_id=1001,
            slack_ts="100.1",
            permalink="https://slack.example/historical",
            canvas_metadata={"edit": _asset_snapshot(1001)},
            now=clock.now(),
        )
    )
    clock.advance(minutes=1)
    repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group_id,
            batch_id=batch.id,
            kind=MessageKind.ASSET_ROOT,
            asset_entity_id=1001,
            slack_ts="100.2",
            permalink="https://slack.example/latest",
            canvas_metadata={"edit": _asset_snapshot(1001)},
            now=clock.now(),
        )
    )
    session.flush()
    del historical
    return MessageRef(workspace_id="W1", channel_id="C1", user_id="Ueditor", message_ts="100.1", message_identity="batch:1001")


def sample_group_edit(repositories: Repositories, session: Session, clock: FakeClock) -> GroupEditRequest:
    """Seed a latest summary plus three latest roots and return a group edit request."""
    group_id = _seed_group(repositories, session, clock)
    batch = repositories.batches.create(group_id=group_id, workspace_id="W1", channel_id="C1", submitter_user_id="Ueditor", payload={}, now=clock.now())
    session.flush()
    repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group_id,
            batch_id=batch.id,
            kind=MessageKind.GROUP_SUMMARY,
            asset_entity_id=None,
            slack_ts="200.1",
            permalink="https://slack.example/summary",
            canvas_metadata={
                "canvas_id": "Fcanvas",
                "edit": {
                    "kind": "group_summary",
                    "canvas_id": "Fcanvas",
                    "group_title": "SEASON 31 PROP REQUEST THREADS",
                    "group_animator_id": "Uanim",
                    "group_additional_ids": [],
                    "group_links": [{"label": "Brief", "url": "https://example.com/brief"}],
                    "group_animator_display": "Name Uanim",
                    "group_additional_displays": [],
                    "included_asset_count": 3,
                    "processing_status": "Complete",
                    "completion_count": 3,
                    "failure_count": 0,
                    "message_identity": batch.id,
                },
            },
            now=clock.now(),
        )
    )
    for entity_id, ts in ((1001, "201.1"), (1002, "201.2"), (1003, "201.3")):
        repositories.history.record(
            NewMessageInput(
                workspace_id="W1",
                channel_id="C1",
                group_id=group_id,
                batch_id=batch.id,
                kind=MessageKind.ASSET_ROOT,
                asset_entity_id=entity_id,
                slack_ts=ts,
                permalink=f"https://slack.example/{entity_id}",
                canvas_metadata={"edit": _asset_snapshot(entity_id)},
                now=clock.now(),
            )
        )
    session.flush()
    return GroupEditRequest(
        workspace_id="W1",
        channel_id="C1",
        user_id="Ueditor",
        message_ts="200.1",
        animator_id="Uanim",
        additional_ids=("Uadd",),
        links_text="Notes: https://example.com/notes",
    )


def test_historical_asset_edit_is_refused_with_latest_link(edit_service: EditService, repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Historical roots are refused and point at the current Latest permalink."""
    result = edit_service.open_asset_editor(historical_message(repositories, session, clock))
    assert result.refused
    assert result.latest_permalink == "https://slack.example/latest"


def test_group_edit_updates_latest_roots_without_notifications(
    edit_service: EditService, fake_slack: FakeSlackGateway, repositories: Repositories, session: Session, clock: FakeClock
) -> None:
    """Group edits update summary + all latest roots via non-notifying chat.update."""
    edit_service.apply_group_edit(sample_group_edit(repositories, session, clock))
    assert fake_slack.updated_summary is not None
    assert len(fake_slack.updated_latest_roots) == 3
    assert all(update.sends_notifications is False for update in fake_slack.updates)
    assert fake_slack.canvas_edits


def test_group_edit_updates_primary_canvas(
    repositories: Repositories, fake_slack: FakeSlackGateway, session: Session, clock: FakeClock
) -> None:
    """Satellite group edits mirror onto the primary channel canvas."""
    fake_slack.channel_canvas_ids = {"C1": "Fcanvas", _PRIMARY_CHANNEL: "Fprimary"}
    service = EditService(
        repositories=repositories,
        slack=fake_slack,
        canvas_slack=fake_slack,
        clock=clock,
        primary_asset_index_channel_id=_PRIMARY_CHANNEL,
    )
    service.apply_group_edit(sample_group_edit(repositories, session, clock))
    primary_edits = [edit for edit in fake_slack.canvas_edits if edit["canvas_id"] == "Fprimary"]
    assert primary_edits
    assert any("Source channel:" in str(edit.get("markdown") or "") for edit in primary_edits)


def test_group_edit_primary_failure_does_not_raise(
    repositories: Repositories, fake_slack: FakeSlackGateway, session: Session, clock: FakeClock
) -> None:
    """Primary canvas failures are logged but do not fail the edit."""
    fake_slack.channel_canvas_ids = {"C1": "Fcanvas", _PRIMARY_CHANNEL: "Fprimary"}
    fake_slack.fail_edit_canvas_id = "Fprimary"
    service = EditService(
        repositories=repositories,
        slack=fake_slack,
        canvas_slack=fake_slack,
        clock=clock,
        primary_asset_index_channel_id=_PRIMARY_CHANNEL,
    )
    service.apply_group_edit(sample_group_edit(repositories, session, clock))
    satellite_edits = [edit for edit in fake_slack.canvas_edits if edit["canvas_id"] == "Fcanvas"]
    assert satellite_edits


def test_group_edit_skips_primary_when_channel_is_primary(
    repositories: Repositories, fake_slack: FakeSlackGateway, session: Session, clock: FakeClock
) -> None:
    """Primary-channel group edits skip the primary mirror."""
    fake_slack.channel_canvas_ids = {_PRIMARY_CHANNEL: "Fprimary"}
    group_id = _seed_group(repositories, session, clock, channel_id=_PRIMARY_CHANNEL)
    batch = repositories.batches.create(
        group_id=group_id,
        workspace_id="W1",
        channel_id=_PRIMARY_CHANNEL,
        submitter_user_id="Ueditor",
        payload={},
        now=clock.now(),
    )
    session.flush()
    repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id=_PRIMARY_CHANNEL,
            group_id=group_id,
            batch_id=batch.id,
            kind=MessageKind.GROUP_SUMMARY,
            asset_entity_id=None,
            slack_ts="200.1",
            permalink="https://slack.example/summary",
            canvas_metadata={
                "canvas_id": "Fprimary",
                "edit": {
                    "kind": "group_summary",
                    "canvas_id": "Fprimary",
                    "group_title": "SEASON 31 PROP REQUEST THREADS",
                    "group_animator_id": "Uanim",
                    "group_additional_ids": [],
                    "group_links": [{"label": "Brief", "url": "https://example.com/brief"}],
                    "group_animator_display": "Name Uanim",
                    "group_additional_displays": [],
                    "included_asset_count": 1,
                    "processing_status": "Complete",
                    "completion_count": 1,
                    "failure_count": 0,
                    "message_identity": batch.id,
                },
            },
            now=clock.now(),
        )
    )
    repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id=_PRIMARY_CHANNEL,
            group_id=group_id,
            batch_id=batch.id,
            kind=MessageKind.ASSET_ROOT,
            asset_entity_id=1001,
            slack_ts="201.1",
            permalink="https://slack.example/1001",
            canvas_metadata={"edit": _asset_snapshot(1001)},
            now=clock.now(),
        )
    )
    session.flush()
    service = EditService(
        repositories=repositories,
        slack=fake_slack,
        canvas_slack=fake_slack,
        clock=clock,
        primary_asset_index_channel_id=_PRIMARY_CHANNEL,
    )
    service.apply_group_edit(
        GroupEditRequest(
            workspace_id="W1",
            channel_id=_PRIMARY_CHANNEL,
            user_id="Ueditor",
            message_ts="200.1",
            animator_id="Uanim",
            additional_ids=(),
            links_text="",
        )
    )
    assert len(fake_slack.canvas_edits) == 1
    assert fake_slack.canvas_edits[0]["canvas_id"] == "Fprimary"


def test_asset_edit_updates_one_latest_root(
    edit_service: EditService, fake_slack: FakeSlackGateway, repositories: Repositories, session: Session, clock: FakeClock
) -> None:
    """Asset edits rewrite only the current latest root and store audit fields."""
    group_id = _seed_group(repositories, session, clock)
    batch = repositories.batches.create(group_id=group_id, workspace_id="W1", channel_id="C1", submitter_user_id="Ueditor", payload={}, now=clock.now())
    session.flush()
    root = repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group_id,
            batch_id=batch.id,
            kind=MessageKind.ASSET_ROOT,
            asset_entity_id=1001,
            slack_ts="300.1",
            permalink="https://slack.example/300",
            canvas_metadata={"edit": _asset_snapshot(1001)},
            now=clock.now(),
        )
    )
    session.flush()
    edit_service.apply_asset_edit(
        AssetEditRequest(
            workspace_id="W1",
            channel_id="C1",
            user_id="Ueditor",
            message_ts=root.slack_ts,
            animator_id="Uasset",
            additional_ids=("Uadd",),
            links_text="Ref: https://example.com/ref",
        )
    )
    assert len(fake_slack.updates) == 1
    updated = repositories.history.get_by_channel_ts(workspace_id="W1", channel_id="C1", slack_ts="300.1")
    assert updated is not None
    assert updated.last_editor_id == "Ueditor"
    assert updated.last_edited_at == clock.now()


def test_open_editor_omits_empty_initial_user(edit_service: EditService, repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Unassigned people must not send empty initial_option (Slack rejects empty initials)."""
    group_id = _seed_group(repositories, session, clock)
    batch = repositories.batches.create(group_id=group_id, workspace_id="W1", channel_id="C1", submitter_user_id="Ueditor", payload={}, now=clock.now())
    session.flush()
    snapshot = _asset_snapshot(1001)
    snapshot["asset_animator_id"] = ""
    snapshot["asset_additional_ids"] = []
    root = repositories.history.record(
        NewMessageInput(
            workspace_id="W1",
            channel_id="C1",
            group_id=group_id,
            batch_id=batch.id,
            kind=MessageKind.ASSET_ROOT,
            asset_entity_id=1001,
            slack_ts="400.1",
            permalink="https://slack.example/400",
            canvas_metadata={"edit": snapshot},
            now=clock.now(),
        )
    )
    session.flush()
    result = edit_service.open_asset_editor(
        MessageRef(workspace_id="W1", channel_id="C1", user_id="Ueditor", message_ts=root.slack_ts, message_identity="a")
    )
    assert not result.refused
    assert result.view is not None
    animator_block = result.view["blocks"][0]
    assert animator_block["element"]["type"] == "static_select"
    assert "initial_option" not in animator_block["element"]
    assert "initial_user" not in animator_block["element"]
    assert animator_block.get("optional") is True
    additional_block = result.view["blocks"][1]
    assert additional_block["element"]["type"] == "multi_static_select"
    assert "initial_options" not in additional_block["element"]
    assert "initial_users" not in additional_block["element"]
    assert any("@ueditor" in opt["text"]["text"] for opt in animator_block["element"]["options"])
    assert any("Name Ueditor" in opt["text"]["text"] for opt in animator_block["element"]["options"])

def test_open_latest_editors_return_views(edit_service: EditService, repositories: Repositories, session: Session, clock: FakeClock) -> None:
    """Latest asset/group editors return modal views."""
    request = sample_group_edit(repositories, session, clock)
    group_ref = MessageRef(workspace_id="W1", channel_id="C1", user_id="Ueditor", message_ts=request.message_ts, message_identity="g")
    group_result = edit_service.open_group_editor(group_ref)
    assert not group_result.refused
    assert group_result.view is not None
    assert group_result.view["callback_id"]

    root = repositories.history.list_latest_asset_roots_for_group(
        repositories.history.get_by_channel_ts(workspace_id="W1", channel_id="C1", slack_ts=request.message_ts).group_id  # type: ignore[union-attr]
    )[0]
    asset_result = edit_service.open_asset_editor(
        MessageRef(workspace_id="W1", channel_id="C1", user_id="Ueditor", message_ts=root.slack_ts, message_identity="a")
    )
    assert not asset_result.refused
    assert asset_result.view is not None


def test_non_member_cannot_open_editor(
    edit_service: EditService, fake_slack: FakeSlackGateway, repositories: Repositories, session: Session, clock: FakeClock
) -> None:
    """non-members are rejected before opening editors."""
    request = sample_group_edit(repositories, session, clock)
    fake_slack.members = {"Uanim"}
    with pytest.raises(ValidationError, match="channel members"):
        edit_service.open_group_editor(MessageRef(workspace_id="W1", channel_id="C1", user_id="Ueditor", message_ts=request.message_ts, message_identity="g"))


def test_edit_validation_errors_route_link_parse_to_links_block() -> None:
    """Link format failures must not be attributed to the Animator block."""
    from red_team_prop_threader.edits import edit_validation_errors
    from red_team_prop_threader._errors import ValidationError

    errors = edit_validation_errors(ValidationError("line 1: Supporting links require a label (label: link)"))
    assert errors == {"edit_links": "line 1: Supporting links require a label (label: link)"}
    membership = edit_validation_errors(ValidationError("selected users must be members of the target channel"))
    assert membership == {"edit_animator": "selected users must be members of the target channel"}


def test_decode_edit_submission_parses_metadata_and_fields() -> None:
    """Edit modal decoding splits channel|ts metadata and people fields."""
    view = {
        "private_metadata": "C1|12.34",
        "state": {
            "values": {
                "edit_animator": {"edit_animator": {"selected_user": "Uanim"}},
                "edit_additional": {"edit_additional": {"selected_users": ["Uadd"]}},
                "edit_links": {"edit_links": {"value": "A: https://example.com/a"}},
            }
        },
    }
    channel_id, message_ts, animator_id, additional_ids, links_text = decode_edit_submission(view)
    assert channel_id == "C1"
    assert message_ts == "12.34"
    assert animator_id == "Uanim"
    assert additional_ids == ("Uadd",)
    assert "example.com" in links_text
