"""channel-canvas preflight, lookup, and narrow indexing edits."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from zoneinfo import ZoneInfo
from dataclasses import dataclass

from red_team_prop_threader._errors import ExternalServiceError, PermissionDeniedError
from red_team_prop_threader.validation import normalize_group_title


if TYPE_CHECKING:
    from datetime import datetime

    from red_team_prop_threader.domain import SupportingLink


__all__ = (
    "CANVAS_TITLE",
    "PRIMARY_CANVAS_TITLE",
    "CanvasService",
    "DuplicateThreadRequest",
    "DuplicateThreadResult",
    "GroupIndexRequest",
    "IndexedAsset",
    "PreflightResult",
    "PreflightState",
    "format_canvas_timestamp",
    "titles_match",
)

CANVAS_TITLE = "INDEX OF PROP REQUESTS"
PRIMARY_CANVAS_TITLE = "PRIMARY ASSET INDEX"
_CANVAS_TZ = ZoneInfo("America/Los_Angeles")
_WHITESPACE_RE = re.compile(r"\s+")


class PreflightState(StrEnum):
    """explicit canvas preflight outcomes."""

    READY = "READY"
    CREATE_CONFIRMATION_REQUIRED = "CREATE_CONFIRMATION_REQUIRED"
    RENAME_CONFIRMATION_REQUIRED = "RENAME_CONFIRMATION_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """result of channel-canvas preflight."""

    state: PreflightState
    canvas_id: str | None
    current_title: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class IndexedAsset:
    """one asset entry to place into the canvas index."""

    entity_id: int
    name: str
    asset_url: str
    permalink: str
    created_at: datetime
    is_latest: bool = True
    prior_permalink: str | None = None
    prior_created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GroupIndexRequest:
    """request to index a group and its assets onto the channel canvas."""

    channel_id: str
    canvas_id: str
    group_title: str
    animator_display: str
    additional_displays: tuple[str, ...]
    links: tuple[SupportingLink, ...]
    assets: tuple[IndexedAsset, ...]
    for_primary: bool = False
    source_channel_display: str = ""


@dataclass(frozen=True, slots=True)
class DuplicateThreadRequest:
    """request to index a new thread for an asset already on the canvas."""

    channel_id: str
    canvas_id: str
    group_title: str
    entity_id: int
    asset_name: str
    asset_url: str
    permalink: str
    created_at: datetime
    prior_latest_section_hint: str = "Latest"


@dataclass(frozen=True, slots=True)
class DuplicateThreadResult:
    """outcome of duplicate-thread canvas indexing."""

    manual_cleanup_required: bool
    detail: str | None = None


class CanvasGateway(Protocol):
    """subset of slack gateway methods required by CanvasService."""

    def get_conversation_info(self, channel_id: str) -> dict[str, object]:
        """Return channel info including canvas properties."""

    def get_file_info(self, file_id: str) -> dict[str, object]:
        """Return file/canvas metadata including title."""

    def create_channel_canvas(self, channel_id: str, *, title: str) -> str:
        """Create the channel canvas and return its id."""

    def rename_canvas(self, canvas_id: str, *, title: str) -> None:
        """Rename an existing canvas title."""

    def lookup_sections(self, canvas_id: str, *, contains_text: str | None = None, section_types: tuple[str, ...] = ("any_header",)) -> list[dict[str, str]]:
        """Lookup canvas sections matching criteria."""

    def edit_canvas(self, canvas_id: str, *, operation: str, markdown: str | None = None, section_id: str | None = None, title: str | None = None) -> None:
        """Apply one canvas edit operation."""


class CanvasService:
    """preflight and narrow edits for INDEX OF PROP REQUESTS."""

    def __init__(self, slack: CanvasGateway) -> None:
        """Initialize with a slack gateway or test double.

        Args:
            slack: gateway exposing conversation/file/canvas methods.
        """
        self._slack = slack

    def preflight(self, channel_id: str, *, title: str = CANVAS_TITLE) -> PreflightResult:
        """Inspect the channel canvas before import/data entry.

        Args:
            channel_id: slack channel id.
            title: expected canonical canvas title.

        Returns:
            PreflightResult: READY, create/rename confirmation, or BLOCKED.
        """
        try:
            channel = self._slack.get_conversation_info(channel_id)
        except PermissionDeniedError as exc:
            return PreflightResult(PreflightState.BLOCKED, None, detail=str(exc))
        except ExternalServiceError as exc:
            return PreflightResult(PreflightState.BLOCKED, None, detail=str(exc))

        canvas_id = _extract_canvas_id(channel)
        if canvas_id is None:
            return PreflightResult(PreflightState.CREATE_CONFIRMATION_REQUIRED, None)

        try:
            file_info = self._slack.get_file_info(canvas_id)
        except PermissionDeniedError as exc:
            return PreflightResult(PreflightState.BLOCKED, canvas_id, detail=str(exc))
        except ExternalServiceError as exc:
            return PreflightResult(PreflightState.BLOCKED, canvas_id, detail=str(exc))

        current_title = str(file_info.get("title") or file_info.get("name") or "")
        if titles_match(current_title, title):
            return PreflightResult(PreflightState.READY, canvas_id, current_title=current_title)
        return PreflightResult(PreflightState.RENAME_CONFIRMATION_REQUIRED, canvas_id, current_title=current_title)

    def ensure_canvas(self, channel_id: str, *, create: bool = False, rename: bool = False, title: str = CANVAS_TITLE) -> str:
        """Create or rename the channel canvas after explicit confirmation.

        Args:
            channel_id: slack channel id.
            create: create a missing canvas when True.
            rename: rename an existing mismatched title when True.
            title: expected canonical canvas title for create/rename/checks.

        Returns:
            str: canvas id ready for indexing.

        Raises:
            ExternalServiceError: when canvas cannot be prepared.
        """
        result = self.preflight(channel_id, title=title)
        if result.state is PreflightState.READY and result.canvas_id:
            return result.canvas_id
        if result.state is PreflightState.CREATE_CONFIRMATION_REQUIRED and create:
            return self._slack.create_channel_canvas(channel_id, title=title)
        if result.state is PreflightState.RENAME_CONFIRMATION_REQUIRED and rename and result.canvas_id:
            self._slack.rename_canvas(result.canvas_id, title=title)
            return result.canvas_id
        raise ExternalServiceError("canvas is not ready for indexing")

    def ensure_primary_canvas(self, channel_id: str) -> str:
        """Ensure the primary channel has a canvas titled PRIMARY ASSET INDEX.

        Creates or renames as needed. Raises ExternalServiceError / PermissionDeniedError
        on Slack failures (caller treats as best-effort).
        """
        return self.ensure_canvas(channel_id, create=True, rename=True, title=PRIMARY_CANVAS_TITLE)

    def index_batch(self, request: GroupIndexRequest) -> None:
        """Index a group and its assets using one edit operation.

        New groups are inserted at the canvas start. Existing groups are
        replaced in place when their heading section can be found.

        Args:
            request: group and asset content to index.
        """
        markdown = render_group_markdown(request)
        title = normalize_group_title(request.group_title)
        if request.for_primary:
            display = (request.source_channel_display or request.channel_id).strip()
            lookup_title = f"{title} ({display})"
        else:
            lookup_title = title
        sections = self._slack.lookup_sections(request.canvas_id, contains_text=lookup_title, section_types=("h1", "h2", "any_header"))
        section_id = _first_section_id(sections)
        if section_id is None:
            self._slack.edit_canvas(request.canvas_id, operation="insert_at_start", markdown=markdown)
            return
        self._slack.edit_canvas(request.canvas_id, operation="replace", section_id=section_id, markdown=markdown)

    def add_duplicate_thread(self, request: DuplicateThreadRequest) -> DuplicateThreadResult:
        """Index a new Latest thread link for an existing asset.

        When the prior Latest marker section cannot be found because of manual
        edits, append the new entry and require manual cleanup without using
        replace.

        Args:
            request: duplicate thread indexing request.

        Returns:
            DuplicateThreadResult: whether manual cleanup is required.
        """
        new_line = _asset_thread_line(request.permalink, request.created_at, is_latest=True)
        # "Latest" lives on list-item/paragraph text, not headers — look up by
        # text only (empty section_types). The gateway omits section_types when
        # empty; sending [] makes Slack return invalid_arguments.
        sections = self._slack.lookup_sections(request.canvas_id, contains_text=request.prior_latest_section_hint, section_types=())
        prior_id = _first_section_id(sections)
        if prior_id is None:
            # Do not append orphan asset fragments without a group heading —
            # callers should fall back to index_batch for a full group rewrite.
            return DuplicateThreadResult(manual_cleanup_required=True, detail=f"prior Latest marker for entity {request.entity_id} needs manual cleanup")
        # clear Latest on the prior marker without rewriting unmanaged neighbors
        self._slack.edit_canvas(request.canvas_id, operation="replace", section_id=prior_id, markdown=new_line.replace(" — Latest", ""))
        self._slack.edit_canvas(
            request.canvas_id,
            operation="insert_after",
            section_id=prior_id,
            markdown=(f"### [{_escape_md(request.asset_name)}]({request.asset_url})\n- {new_line}\n"),
        )
        return DuplicateThreadResult(manual_cleanup_required=False)


def titles_match(actual: str, expected: str) -> bool:
    """Return True when canvas titles match ignoring case, space, and colon.

    Args:
        actual: title read from Slack.
        expected: required canonical title.

    Returns:
        bool: whether the titles are equivalent under canvas matching rules.
    """
    return _normalize_title(actual) == _normalize_title(expected)


def format_canvas_timestamp(value: datetime) -> str:
    """Format a timestamp for canvas display in America/Los_Angeles.

    Args:
        value: aware or naive datetime; naive values are treated as UTC.

    Returns:
        str: local timestamp with timezone abbreviation.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    local = value.astimezone(_CANVAS_TZ)
    return local.strftime("%Y-%m-%d %H:%M %Z")


def render_group_markdown(request: GroupIndexRequest) -> str:
    """Render a full group section for canvas insert/replace.

    Args:
        request: group index request.

    Returns:
        str: markdown document fragment for the group, ending with two blank
        lines so consecutive groups stay visually separated on the canvas.
    """
    title = normalize_group_title(request.group_title)
    if request.for_primary:
        display = (request.source_channel_display or request.channel_id).strip()
        heading = f"## {title} ({display})"
    else:
        heading = f"## {title}"
    people_parts = [part for part in (request.animator_display, *request.additional_displays) if part and part.strip()]
    people = ", ".join(people_parts) if people_parts else "unassigned"
    link_lines = "\n".join(f"- [{_escape_md(link.label)}]({link.url})" for link in request.links)
    asset_parts: list[str] = []
    for asset in request.assets:
        lines = [
            f"### {_escape_md(asset.name)}",
            f"- :shotgrid: [ShotGrid]({asset.asset_url})",
            f"- {_asset_thread_line(asset.permalink, asset.created_at, is_latest=asset.is_latest)}",
        ]
        if asset.prior_permalink and asset.prior_created_at is not None:
            lines.append(f"- {_asset_thread_line(asset.prior_permalink, asset.prior_created_at, is_latest=False)}")
        asset_parts.append("\n".join(lines))
    sections = [heading]
    if request.for_primary:
        src = (request.source_channel_display or request.channel_id).strip()
        sections.append(f"**Source channel:** #{src}")
    sections.append(f"**Creative Stakeholder:** {people}")
    if link_lines:
        sections.append("**Group Links:**\n" + link_lines)
    if asset_parts:
        sections.append("\n\n".join(asset_parts))
    # Two trailing blank lines separate this group from the previous group below.
    return "\n\n".join(sections) + "\n\n\n"


def _asset_thread_line(permalink: str, created_at: datetime, *, is_latest: bool) -> str:
    """Render one timestamped thread link line."""
    stamp = format_canvas_timestamp(created_at)
    latest = " — Latest" if is_latest else ""
    return f":Slack: [{stamp}]({permalink}){latest}"


def _normalize_title(value: str) -> str:
    """Normalize a canvas title for comparison."""
    text = _WHITESPACE_RE.sub(" ", value.strip()).casefold()
    if text.endswith(":"):
        text = text[:-1].rstrip()
    return text


def _extract_canvas_id(channel: dict[str, object]) -> str | None:
    """Extract the channel canvas file id from conversations.info.

    Prefers the legacy ``properties.canvas.file_id`` field when present. Newer
    Slack channel canvases appear only as ``properties.tabs`` /
    ``properties.tabz`` entries with ``type == "canvas"``.
    """
    properties = channel.get("properties")
    if not isinstance(properties, dict):
        return None

    canvas = properties.get("canvas")
    if isinstance(canvas, dict):
        file_id = canvas.get("file_id") or canvas.get("id")
        if isinstance(file_id, str) and file_id:
            return file_id

    for key in ("tabs", "tabz"):
        tabs = properties.get(key)
        if not isinstance(tabs, list):
            continue
        for tab in tabs:
            if not isinstance(tab, dict) or tab.get("type") != "canvas":
                continue
            data = tab.get("data")
            if not isinstance(data, dict):
                continue
            file_id = data.get("file_id") or data.get("id")
            if isinstance(file_id, str) and file_id:
                return file_id
    return None


def _first_section_id(sections: list[dict[str, str]]) -> str | None:
    """Return the first section id from a lookup response."""
    for section in sections:
        section_id = section.get("id") or section.get("section_id")
        if isinstance(section_id, str) and section_id:
            return section_id
    return None


def _escape_md(text: str) -> str:
    """Escape brackets in markdown link labels."""
    return text.replace("[", "\\[").replace("]", "\\]")
