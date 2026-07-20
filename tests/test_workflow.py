"""tests for slash-command workflow: preflight, import drafts, and confirmation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from datetime import datetime, timezone, timedelta
from dataclasses import field, dataclass

import pytest
from sqlalchemy import event, create_engine
from sqlalchemy.orm import Session

from red_team_prop_threader.canvas import CANVAS_TITLE, CanvasService
from red_team_prop_threader.domain import ImportedAsset
from red_team_prop_threader.leases import ChannelLeaseRepository
from red_team_prop_threader.tables import Base
from red_team_prop_threader.workflow import Workflow, DraftSession, CommandRequest, ConfirmResponse


if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Engine


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeSlackGateway:
    """slack double recording modal opens/updates and user lookups."""

    opened_view: dict[str, Any] | None = None
    updated_views: list[dict[str, Any]] = field(default_factory=list)
    display_names: dict[str, str] = field(default_factory=lambda: {"U_OWNER": "Owner Name"})
    channel_canvas_id: str | None = None
    canvas_title: str = CANVAS_TITLE
    members: tuple[str, ...] = ("U_OWNER", "U_SECOND", "U_COMMAND")
    permission_blocked: bool = False

    def open_view(self, trigger_id: str, view: dict[str, Any]) -> dict[str, Any]:
        """Record the first opened modal."""
        del trigger_id
        self.opened_view = view
        return {"ok": True, "view": {"id": "Vopen", "hash": "h1"}}

    def update_view(self, view_id: str, view: dict[str, Any], *, view_hash: str | None = None) -> dict[str, Any]:
        """Record a modal update."""
        del view_id, view_hash
        self.updated_views.append(view)
        return {"ok": True}

    def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Return display name profile data."""
        name = self.display_names.get(user_id, user_id)
        return {"id": user_id, "profile": {"display_name": name, "real_name": name}}

    def get_conversation_info(self, channel_id: str) -> dict[str, object]:
        """Return channel info including optional canvas."""
        if self.permission_blocked:
            from red_team_prop_threader._errors import PermissionDeniedError

            raise PermissionDeniedError("bot cannot access channel")
        canvas = None
        if self.channel_canvas_id is not None:
            canvas = {"file_id": self.channel_canvas_id}
        return {"id": channel_id, "properties": {"canvas": canvas} if canvas else {}}

    def get_file_info(self, file_id: str) -> dict[str, object]:
        """Return canvas file metadata."""
        return {"id": file_id, "title": self.canvas_title}

    def get_conversation_members(self, channel_id: str) -> tuple[str, ...]:
        """Return configured channel members."""
        del channel_id
        return self.members

    def create_channel_canvas(self, channel_id: str, *, title: str) -> str:
        """Create a fake canvas id."""
        del channel_id
        self.channel_canvas_id = "Fnew"
        self.canvas_title = title
        return "Fnew"

    def rename_canvas(self, canvas_id: str, *, title: str) -> None:
        """Rename fake canvas title."""
        del canvas_id
        self.canvas_title = title

    def lookup_sections(self, canvas_id: str, *, contains_text: str | None = None, section_types: tuple[str, ...] = ("any_header",)) -> list[dict[str, str]]:
        """No sections by default."""
        del canvas_id, contains_text, section_types
        return []

    def edit_canvas(self, canvas_id: str, *, operation: str, markdown: str | None = None, section_id: str | None = None, title: str | None = None) -> None:
        """No-op canvas edit."""
        del canvas_id, operation, markdown, section_id, title


@dataclass
class FakeShotGridGateway:
    """shotgrid double that records export attempts."""

    export_calls: list[int] = field(default_factory=list)
    csv_text: str = "Asset Name,Entity ID\nProp A,1001\nProp B,1002\n"

    def export_page(self, page_id: int) -> str:
        """Record and return configured CSV."""
        self.export_calls.append(page_id)
        return self.csv_text


class FakeClock:
    """deterministic utc clock."""

    def __init__(self) -> None:
        """Initialize at a fixed UTC instant."""
        self._now = datetime(2026, 7, 17, 18, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        """Return current fake time."""
        return self._now


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def sample_command(**kwargs: object) -> CommandRequest:
    """Build a slash-command request."""
    base: dict[str, object] = dict(
        workspace_id="W1",
        channel_id="C1",
        user_id="U_COMMAND",
        trigger_id="T123",
        text="https://respawn.shotgunstudio.com/page/23280",
        response_url="https://hooks.slack.com/commands/x",
    )
    base.update(kwargs)
    return CommandRequest(**base)  # type: ignore[arg-type]


def sample_draft(**kwargs: object) -> DraftSession:
    """Build an in-memory draft ready for confirmation."""
    assets = (
        ImportedAsset(entity_id=1001, name="Prop A", url="https://respawn.shotgunstudio.com/detail/Asset/1001", source_index=0),
        ImportedAsset(entity_id=1002, name="Prop B", url="https://respawn.shotgunstudio.com/detail/Asset/1002", source_index=1),
    )
    base: dict[str, object] = dict(
        draft_id="draft-1",
        workspace_id="W1",
        channel_id="C1",
        user_id="U_SECOND",
        page_url="https://respawn.shotgunstudio.com/page/23280",
        assets=assets,
        duplicate_count=0,
        group_title="SEASON 31 PROP REQUEST THREADS",
        group_animator_id="U_SECOND",
        group_additional_ids=(),
        group_links_text="",
        included_entity_ids=(1001, 1002),
        asset_animators={1001: "U_SECOND", 1002: "U_SECOND"},
        asset_additional={},
        asset_links_text={},
        imported_at=datetime(2026, 7, 17, 17, 0, 0, tzinfo=timezone.utc),
        canvas_id="Fcanvas",
        page_index=0,
    )
    base.update(kwargs)
    return DraftSession(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


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
    """Open session for lease/draft persistence."""
    s = Session(engine)
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def fake_slack() -> FakeSlackGateway:
    """Fresh slack fake requiring create confirmation (no canvas)."""
    return FakeSlackGateway(channel_canvas_id=None)


@pytest.fixture
def workflow(session: Session, engine: Engine, fake_slack: FakeSlackGateway) -> Workflow:
    """Workflow wired to fakes and sqlite leases."""
    clock = FakeClock()
    shotgrid = FakeShotGridGateway()
    leases = ChannelLeaseRepository(session, engine)
    canvas = CanvasService(fake_slack)
    return Workflow(
        slack=fake_slack, shotgrid=shotgrid, canvas=canvas, leases=leases, clock=clock, shotgrid_base_url="https://respawn.shotgunstudio.com", session=session
    )


# ---------------------------------------------------------------------------
# plan-required tests
# ---------------------------------------------------------------------------


def test_command_opens_canvas_preflight_before_import(workflow: Workflow, fake_slack: FakeSlackGateway) -> None:
    """Command opens canvas preflight before any ShotGrid export."""
    workflow.handle_command(sample_command(text="https://respawn.shotgunstudio.com/page/23280"))
    assert fake_slack.opened_view is not None
    assert fake_slack.opened_view["callback_id"] == "canvas_preflight"
    assert workflow.shotgrid.export_calls == []


def test_busy_confirmation_preserves_draft_and_names_owner(workflow: Workflow) -> None:
    """Busy channel lease keeps the draft and names the current owner."""
    workflow.leases.acquire("C1", "U_OWNER", workflow.clock.now(), timedelta(minutes=10))
    draft = sample_draft(user_id="U_SECOND")
    workflow.drafts.put(draft)
    response = workflow.confirm_batch(draft)
    assert isinstance(response, ConfirmResponse)
    assert "@Owner Name" in response.private_text
    assert workflow.drafts.exists(response.draft_id)


# ---------------------------------------------------------------------------
# additional coverage
# ---------------------------------------------------------------------------


def test_ready_canvas_updates_to_import_view(workflow: Workflow, fake_slack: FakeSlackGateway) -> None:
    """When canvas is ready, the modal updates to the import screen."""
    fake_slack.channel_canvas_id = "Fcanvas"
    fake_slack.canvas_title = CANVAS_TITLE
    workflow.handle_command(sample_command())
    assert fake_slack.opened_view is not None
    assert fake_slack.opened_view["callback_id"] == "canvas_preflight"
    assert fake_slack.updated_views
    assert fake_slack.updated_views[-1]["callback_id"] == "import_assets"
    assert workflow.shotgrid.export_calls == []


def test_import_url_exports_and_opens_asset_page(workflow: Workflow, fake_slack: FakeSlackGateway) -> None:
    """Submitting the import URL exports ShotGrid and opens asset page 0."""
    fake_slack.channel_canvas_id = "Fcanvas"
    workflow.handle_command(sample_command())
    draft_id = str(fake_slack.opened_view["private_metadata"])
    view = workflow.submit_import_url(draft_id=draft_id, page_url="https://respawn.shotgunstudio.com/page/23280")
    assert workflow.shotgrid.export_calls == [23280]
    assert view["callback_id"] == "asset_page"
    assert workflow.drafts.exists(draft_id)


def test_blocked_preflight_shows_user_safe_error(workflow: Workflow, fake_slack: FakeSlackGateway) -> None:
    """Permission failures update the modal with safe blocked copy."""
    fake_slack.permission_blocked = True
    workflow.handle_command(sample_command())
    assert fake_slack.updated_views
    text = str(fake_slack.updated_views[-1])
    assert "cannot" in text.lower() or "permission" in text.lower() or "blocked" in text.lower()


def test_canvas_create_rename_and_decline(workflow: Workflow, fake_slack: FakeSlackGateway) -> None:
    """create/rename confirmation paths reach import; decline discards the draft."""
    workflow.handle_command(sample_command(text=""))
    draft_id = str(fake_slack.opened_view["private_metadata"])
    import_view = workflow.confirm_canvas_create(draft_id)
    assert import_view["callback_id"] == "import_assets"
    assert fake_slack.channel_canvas_id == "Fnew"

    fake_slack.canvas_title = "Wrong Title"
    workflow.handle_command(sample_command(text=""))
    rename_draft = str(fake_slack.opened_view["private_metadata"])
    renamed = workflow.confirm_canvas_rename(rename_draft)
    assert renamed["callback_id"] == "import_assets"
    assert fake_slack.canvas_title == CANVAS_TITLE

    workflow.handle_command(sample_command(text=""))
    decline_id = str(fake_slack.opened_view["private_metadata"])
    workflow.decline_canvas(decline_id)
    assert not workflow.drafts.exists(decline_id)


def test_asset_page_save_open_confirm_and_accept(workflow: Workflow, fake_slack: FakeSlackGateway) -> None:
    """Save page state, open confirmation, and accept a free channel lease."""
    fake_slack.channel_canvas_id = "Fcanvas"
    fake_slack.members = ("U_COMMAND", "U_SECOND", "U_OWNER")
    workflow.handle_command(sample_command())
    draft_id = str(fake_slack.opened_view["private_metadata"])
    workflow.submit_import_url(draft_id=draft_id, page_url="https://respawn.shotgunstudio.com/page/23280")

    state = {
        "values": {
            "group_title": {"group_title": {"value": "SEASON 31 PROP REQUEST THREADS"}},
            "group_animator": {"group_animator": {"selected_user": "U_COMMAND"}},
            "group_additional": {"group_additional": {"selected_users": []}},
            "group_links": {"group_links": {"value": ""}},
            "asset_1001_include": {"asset_1001_include": {"selected_options": [{"value": "included"}]}},
            "asset_1001_animator": {"asset_1001_animator": {"selected_user": "U_COMMAND"}},
            "asset_1001_additional": {"asset_1001_additional": {"selected_users": []}},
            "asset_1001_links": {"asset_1001_links": {"value": ""}},
            "asset_1002_include": {"asset_1002_include": {"selected_options": [{"value": "included"}]}},
            "asset_1002_animator": {"asset_1002_animator": {"selected_user": "U_COMMAND"}},
            "asset_1002_additional": {"asset_1002_additional": {"selected_users": []}},
            "asset_1002_links": {"asset_1002_links": {"value": ""}},
        }
    }
    draft = workflow.save_asset_page(draft_id=draft_id, page_index=0, view_state=state)
    assert draft.group_animator_id == "U_COMMAND"
    assert draft.included_entity_ids == (1001, 1002)
    page = workflow.open_asset_page(draft_id, 0)
    assert page["callback_id"] == "asset_page"
    confirm = workflow.open_confirmation(draft_id)
    assert confirm["callback_id"] == "confirm_batch"
    response = workflow.confirm_batch(draft)
    assert response.accepted
    assert response.lease_token
