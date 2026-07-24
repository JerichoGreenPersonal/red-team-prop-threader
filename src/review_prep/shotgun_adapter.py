"""ShotGrid worklist adapter: cards, attachments, comments, delivery selection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol
from pathlib import Path
from dataclasses import field, dataclass


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from review_prep.cl_parser import is_delivery_comment


@dataclass(frozen=True)
class Card:
    """One ShotGrid worklist entity (e.g. Asset).

    Attributes:
        id (int): ShotGrid entity id.
        code (str): Display code / name.
        thumbnail_url (str | None): Image URL when present.
        raw_fields (dict[str, Any]): Full find() record for downstream use.
    """

    id: int
    code: str
    thumbnail_url: str | None
    raw_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Comment:
    """A note/comment on a worklist card.

    Attributes:
        id (int): ShotGrid Note id.
        text (str): Note body (``content``).
        created (str): Creation timestamp string (sortable ISO-like).
    """

    id: int
    text: str
    created: str


@dataclass(frozen=True)
class Attachment:
    """A file attachment linked to a worklist card.

    Attributes:
        id (int): ShotGrid Attachment id.
        filename (str): Attachment file name.
        file_size (int | None): Size in bytes when known.
        raw_fields (dict[str, Any]): Full find() record.
    """

    id: int
    filename: str
    file_size: int | None = None
    raw_fields: dict[str, Any] = field(default_factory=dict)


class ShotgunClient(Protocol):
    """Minimal Shotgun API surface used by :class:`ShotGridAdapter`."""

    def find(
        self,
        entity_type: str,
        filters: list[Any] | tuple[Any, ...] | dict[str, Any],
        fields: list[str] | None = None,
        order: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """Find entities matching filters."""
        ...

    def download_attachment(
        self, attachment: dict[str, Any] | bool = False, file_path: str | None = None, attachment_id: int | None = None
    ) -> str | bytes | None:
        """Download an attachment to ``file_path`` or return bytes."""
        ...


def load_shotgrid_query(path: Path) -> dict[str, Any]:
    """Load a ShotGrid query JSON config.

    Args:
        path (Path): Path to query JSON (entity_type, filters, fields, order).

    Returns:
        (dict[str, Any]) Parsed query config.
    """
    return json.loads(Path(path).read_text(encoding="utf-8"))


def latest_delivery_comment(comments: Sequence[Comment]) -> Comment | None:
    """Return the newest comment that contains a labeled Perforce CL.

    Later internal comments without a deliverable do not hide an earlier delivery.

    Args:
        comments (Sequence[Comment]): Notes for one card (any order).

    Returns:
        (Comment | None) Newest delivery comment, or None if none qualify.
    """
    ordered = sorted(comments, key=lambda c: c.created, reverse=True)
    for comment in ordered:
        if is_delivery_comment(comment.text):
            return comment
    return None


def _as_created_str(value: Any) -> str:
    """Normalize ShotGrid created_at to a comparable string."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


class ShotGridAdapter:
    """Worklist / attachments / notes adapter over ``shotgun_api3`` (or a fake)."""

    def __init__(
        self, sg: Any, *, entity_type: str, filters: list[Any] | None = None, fields: list[str] | None = None, order: list[dict[str, str]] | None = None
    ) -> None:
        """Initialize adapter with an injected Shotgun-like client and query.

        Args:
            sg (Any): Live ``Shotgun`` instance or test fake implementing find/download.
            entity_type (str): Worklist entity type (e.g. ``Asset``).
            filters (list[Any] | None): ShotGrid find filters for the worklist.
            fields (list[str] | None): Fields to request on worklist entities.
            order (list[dict[str, str]] | None): Optional find order.
        """
        if not entity_type:
            raise ValueError("entity_type is required")
        self._sg = sg
        self._entity_type = entity_type
        self._filters: list[Any] = list(filters or [])
        self._fields: list[str] = list(fields or ["id", "code", "image"])
        self._order: list[dict[str, str]] = list(order or [])

    @classmethod
    def connect(cls, *, site_url: str, script_name: str, api_key: str, query: Mapping[str, Any]) -> ShotGridAdapter:
        """Build an adapter from credentials and a query config mapping.

        Args:
            site_url (str): ShotGrid site URL.
            script_name (str): Script user name.
            api_key (str): Script API key.
            query (Mapping[str, Any]): Query JSON (entity_type, filters, fields, order).

        Returns:
            (ShotGridAdapter) Connected adapter.
        """
        from shotgun_api3 import Shotgun

        sg = Shotgun(site_url, script_name=script_name, api_key=api_key)
        return cls(
            sg,
            entity_type=str(query["entity_type"]),
            filters=list(query.get("filters") or []),
            fields=list(query.get("fields") or ["id", "code", "image"]),
            order=list(query.get("order") or []),
        )

    @classmethod
    def from_query_file(cls, *, site_url: str, script_name: str, api_key: str, query_path: Path) -> ShotGridAdapter:
        """Connect using credentials and a query JSON path.

        Args:
            site_url (str): ShotGrid site URL.
            script_name (str): Script user name.
            api_key (str): Script API key.
            query_path (Path): Path to query JSON.

        Returns:
            (ShotGridAdapter) Connected adapter.
        """
        query = load_shotgrid_query(query_path)
        # Prefer site_url from credentials call; query may also document it.
        return cls.connect(site_url=site_url, script_name=script_name, api_key=api_key, query=query)

    def find_worklist(self) -> list[Card]:
        """Return worklist cards for the configured query.

        Returns:
            (list[Card]) Matching entities as cards.
        """
        records = self._sg.find(self._entity_type, self._filters, fields=self._fields, order=self._order or None)
        cards: list[Card] = []
        for record in records:
            image = record.get("image")
            thumbnail_url = image if isinstance(image, str) else None
            cards.append(Card(id=int(record["id"]), code=str(record.get("code") or ""), thumbnail_url=thumbnail_url, raw_fields=dict(record)))
        return cards

    def list_attachments(self, card_id: int) -> list[Attachment]:
        """List Attachment entities linked to a worklist card.

        Args:
            card_id (int): ShotGrid entity id for the card.

        Returns:
            (list[Attachment]) Linked attachments.
        """
        records = self._sg.find(
            "Attachment", [["attachment_links", "is", {"type": self._entity_type, "id": card_id}]], fields=["id", "filename", "file_size", "created_at"]
        )
        attachments: list[Attachment] = []
        for record in records:
            size = record.get("file_size")
            attachments.append(
                Attachment(
                    id=int(record["id"]), filename=str(record.get("filename") or ""), file_size=int(size) if size is not None else None, raw_fields=dict(record)
                )
            )
        return attachments

    def list_comments(self, card_id: int) -> list[Comment]:
        """List Note comments linked to a worklist card (newest first).

        Args:
            card_id (int): ShotGrid entity id for the card.

        Returns:
            (list[Comment]) Linked notes as comments.
        """
        records = self._sg.find(
            "Note",
            [["note_links", "is", {"type": self._entity_type, "id": card_id}]],
            fields=["id", "content", "created_at"],
            order=[{"field_name": "created_at", "direction": "desc"}],
        )
        return [Comment(id=int(record["id"]), text=str(record.get("content") or ""), created=_as_created_str(record.get("created_at"))) for record in records]

    def download_attachment(self, attachment_id: int, dest: Path) -> Path:
        """Download an attachment to ``dest``.

        Args:
            attachment_id (int): ShotGrid Attachment id.
            dest (Path): Destination file path.

        Returns:
            (Path) The destination path written.
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._sg.download_attachment(attachment_id=attachment_id, file_path=str(dest))
        return dest
