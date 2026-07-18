"""tests for channel-canvas preflight and narrow indexing edits."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from dataclasses import field, dataclass

import pytest

from red_team_prop_threader.canvas import CANVAS_TITLE, IndexedAsset, CanvasService, PreflightState, GroupIndexRequest, DuplicateThreadRequest
from red_team_prop_threader.domain import SupportingLink


# ---------------------------------------------------------------------------
# fake slack double
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanvasEditRecord:
    """recorded canvas edit for assertions."""

    operation: str
    markdown: str | None = None
    section_id: str | None = None
    title: str | None = None


@dataclass
class FakeSlackGateway:
    """in-memory slack double used by canvas service tests."""

    canvas_edits: list[CanvasEditRecord] = field(default_factory=list)
    section_lookup_result: list[dict[str, str]] = field(default_factory=list)
    channel_canvas_id: str | None = "Fcanvas"
    canvas_title: str = CANVAS_TITLE
    create_canvas_id: str = "Fnew"
    permission_blocked: bool = False
    plan_tier_blocked: bool = False

    def get_conversation_info(self, channel_id: str) -> dict[str, object]:
        """Return fake conversations.info payload."""
        if self.permission_blocked:
            from red_team_prop_threader._errors import PermissionDeniedError

            raise PermissionDeniedError("bot cannot access channel")
        if self.plan_tier_blocked:
            from red_team_prop_threader._errors import PermissionDeniedError

            raise PermissionDeniedError("canvas plan tier unavailable")
        canvas: dict[str, object] | None = None
        if self.channel_canvas_id is not None:
            canvas = {"file_id": self.channel_canvas_id, "is_empty": False}
        return {"id": channel_id, "properties": {"canvas": canvas} if canvas is not None else {}}

    def get_file_info(self, file_id: str) -> dict[str, object]:
        """Return fake files.info payload with canvas title."""
        return {"id": file_id, "title": self.canvas_title, "name": self.canvas_title}

    def create_channel_canvas(self, channel_id: str, *, title: str) -> str:
        """Create a fake channel canvas and return its id."""
        self.channel_canvas_id = self.create_canvas_id
        self.canvas_title = title
        return self.create_canvas_id

    def rename_canvas(self, canvas_id: str, *, title: str) -> None:
        """Rename a fake canvas title via edit."""
        self.canvas_title = title
        self.canvas_edits.append(CanvasEditRecord(operation="rename", title=title))

    def lookup_sections(self, canvas_id: str, *, contains_text: str | None = None, section_types: tuple[str, ...] = ("any_header",)) -> list[dict[str, str]]:
        """Return configured section lookup results."""
        del canvas_id, contains_text, section_types
        return list(self.section_lookup_result)

    def edit_canvas(self, canvas_id: str, *, operation: str, markdown: str | None = None, section_id: str | None = None, title: str | None = None) -> None:
        """Record a single canvas edit operation."""
        del canvas_id
        self.canvas_edits.append(CanvasEditRecord(operation=operation, markdown=markdown, section_id=section_id, title=title))


# ---------------------------------------------------------------------------
# sample builders
# ---------------------------------------------------------------------------


def sample_new_group(**kwargs: object) -> GroupIndexRequest:
    """Build a group index request for a brand-new canvas group."""
    base: dict[str, object] = dict(
        channel_id="C0B4GJSA1G8",
        canvas_id="Fcanvas",
        group_title="SEASON 31 PROP REQUEST THREADS",
        animator_display="Ada Animator",
        additional_displays=(),
        links=(SupportingLink("Brief", "https://example.com/brief"),),
        assets=(
            IndexedAsset(
                entity_id=1001,
                name="Prop A",
                asset_url="https://respawn.shotgunstudio.com/detail/Asset/1001",
                permalink="https://slack.example/archives/C/p1",
                created_at=datetime(2026, 7, 17, 18, 30, tzinfo=ZoneInfo("UTC")),
                is_latest=True,
            ),
        ),
    )
    base.update(kwargs)
    return GroupIndexRequest(**base)  # type: ignore[arg-type]


def sample_duplicate(**kwargs: object) -> DuplicateThreadRequest:
    """Build a duplicate-thread index request for an existing asset."""
    base: dict[str, object] = dict(
        channel_id="C0B4GJSA1G8",
        canvas_id="Fcanvas",
        group_title="SEASON 31 PROP REQUEST THREADS",
        entity_id=1001,
        asset_name="Prop A",
        asset_url="https://respawn.shotgunstudio.com/detail/Asset/1001",
        permalink="https://slack.example/archives/C/p2",
        created_at=datetime(2026, 7, 17, 19, 0, tzinfo=ZoneInfo("UTC")),
        prior_latest_section_hint="Latest",
    )
    base.update(kwargs)
    return DuplicateThreadRequest(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# plan-required tests
# ---------------------------------------------------------------------------


def test_new_group_is_inserted_at_canvas_start(fake_slack: FakeSlackGateway) -> None:
    """New group sections are inserted at the start of the canvas."""
    service = CanvasService(fake_slack)
    service.index_batch(sample_new_group())
    assert fake_slack.canvas_edits[0].operation == "insert_at_start"


def test_manual_conflict_appends_and_warns_without_replacing_section(fake_slack: FakeSlackGateway) -> None:
    """When section lookup fails, append and require manual cleanup without replace."""
    fake_slack.section_lookup_result = []
    result = CanvasService(fake_slack).add_duplicate_thread(sample_duplicate())
    assert result.manual_cleanup_required
    assert all(edit.operation != "replace" for edit in fake_slack.canvas_edits)


# ---------------------------------------------------------------------------
# preflight and formatting
# ---------------------------------------------------------------------------


def test_preflight_ready_when_title_matches(fake_slack: FakeSlackGateway) -> None:
    """Matching canvas title (ignoring case/colon/whitespace) is READY."""
    fake_slack.canvas_title = "  index of prop requests:  "
    result = CanvasService(fake_slack).preflight("C0B4GJSA1G8")
    assert result.state is PreflightState.READY
    assert result.canvas_id == "Fcanvas"


def test_preflight_create_confirmation_when_missing(fake_slack: FakeSlackGateway) -> None:
    """Missing channel canvas requires create confirmation."""
    fake_slack.channel_canvas_id = None
    result = CanvasService(fake_slack).preflight("C0B4GJSA1G8")
    assert result.state is PreflightState.CREATE_CONFIRMATION_REQUIRED
    assert result.canvas_id is None


def test_preflight_rename_confirmation_for_other_title(fake_slack: FakeSlackGateway) -> None:
    """Existing non-matching title requires rename confirmation."""
    fake_slack.canvas_title = "Channel Notes"
    result = CanvasService(fake_slack).preflight("C0B4GJSA1G8")
    assert result.state is PreflightState.RENAME_CONFIRMATION_REQUIRED
    assert result.current_title == "Channel Notes"


def test_preflight_blocked_on_permission_error(fake_slack: FakeSlackGateway) -> None:
    """Permission and plan-tier failures surface as BLOCKED."""
    fake_slack.permission_blocked = True
    result = CanvasService(fake_slack).preflight("C0B4GJSA1G8")
    assert result.state is PreflightState.BLOCKED


def test_index_batch_uses_pacific_timezone_label(fake_slack: FakeSlackGateway) -> None:
    """Canvas timestamps use America/Los_Angeles with abbreviation."""
    service = CanvasService(fake_slack)
    service.index_batch(sample_new_group())
    markdown = fake_slack.canvas_edits[0].markdown or ""
    assert "PDT" in markdown or "PST" in markdown
    assert "2026-07-17" in markdown or "Jul" in markdown


def test_existing_group_updates_in_place_not_insert_at_start(fake_slack: FakeSlackGateway) -> None:
    """Existing group headings are updated via replace, not moved to start."""
    fake_slack.section_lookup_result = [{"id": "Sgroup", "text": "SEASON 31 PROP REQUEST THREADS"}]
    CanvasService(fake_slack).index_batch(sample_new_group())
    assert fake_slack.canvas_edits
    assert fake_slack.canvas_edits[0].operation == "replace"
    assert fake_slack.canvas_edits[0].section_id == "Sgroup"


def test_duplicate_clears_prior_latest_when_section_found(fake_slack: FakeSlackGateway) -> None:
    """Found prior Latest marker is replaced without append warning."""
    fake_slack.section_lookup_result = [{"id": "Slatest", "text": "Latest"}]
    result = CanvasService(fake_slack).add_duplicate_thread(sample_duplicate())
    assert result.manual_cleanup_required is False
    assert any(edit.operation == "replace" for edit in fake_slack.canvas_edits)
    assert any(edit.operation == "insert_at_end" or edit.operation == "insert_after" for edit in fake_slack.canvas_edits)


@pytest.fixture
def fake_slack() -> FakeSlackGateway:
    """Provide a fresh fake slack gateway per test."""
    return FakeSlackGateway()
