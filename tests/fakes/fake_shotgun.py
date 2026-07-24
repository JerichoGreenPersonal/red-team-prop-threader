"""Fake Shotgun client for unit tests."""

from __future__ import annotations

from typing import Any
from pathlib import Path
from collections.abc import Mapping


def _linked_entity_id(filters: list[Any], link_field: str) -> int | None:
    """Extract linked entity id from ``[[field, 'is', {'type': ..., 'id': N}]]``."""
    for clause in filters:
        if not isinstance(clause, (list, tuple)) or len(clause) < 3:
            continue
        if clause[0] != link_field or clause[1] != "is":
            continue
        target = clause[2]
        if isinstance(target, Mapping) and "id" in target:
            return int(target["id"])
    return None


def _apply_order(records: list[dict[str, Any]], order: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    """Sort records by the first ShotGrid-style order item when present."""
    if not order:
        return records
    field_name = order[0].get("field_name")
    if not field_name:
        return records
    descending = order[0].get("direction", "asc").lower() == "desc"
    return sorted(records, key=lambda r: r.get(field_name) or "", reverse=descending)


class FakeShotgun:
    """Injects find/download results for :class:`~review_prep.shotgun_adapter.ShotGridAdapter`.

    Attributes:
        downloaded (list[tuple[int, str]]): ``(attachment_id, file_path)`` pairs written.
    """

    def __init__(
        self,
        *,
        worklist: list[dict[str, Any]] | None = None,
        notes_by_card: dict[int, list[dict[str, Any]]] | None = None,
        attachments_by_card: dict[int, list[dict[str, Any]]] | None = None,
        file_bytes: dict[int, bytes] | None = None,
        worklist_entity_type: str = "Asset",
    ) -> None:
        """Configure synthetic worklist, notes, attachments, and download bytes.

        Args:
            worklist (list[dict[str, Any]] | None): Entities returned for worklist finds.
            notes_by_card (dict[int, list[dict[str, Any]]] | None): Card id → Note records.
            attachments_by_card (dict[int, list[dict[str, Any]]] | None): Card id → Attachment records.
            file_bytes (dict[int, bytes] | None): Attachment id → file contents.
            worklist_entity_type (str): Entity type treated as the worklist (default ``Asset``).
        """
        self._worklist = [dict(r) for r in (worklist or [])]
        self._notes_by_card = {int(k): [dict(n) for n in v] for k, v in (notes_by_card or {}).items()}
        self._attachments_by_card = {int(k): [dict(a) for a in v] for k, v in (attachments_by_card or {}).items()}
        self._file_bytes = {int(k): v for k, v in (file_bytes or {}).items()}
        self._worklist_entity_type = worklist_entity_type
        self.downloaded: list[tuple[int, str]] = []
        self.export_calls: list[tuple[int, str, str | None]] = []

    def export_page(self, page_id: int, format: str = "csv", layout_name: str | None = None) -> str:
        """Return a CSV export of the configured worklist (layout_3 path).

        Args:
            page_id (int): ShotGrid page id (e.g. 12787).
            format (str): Export format (only ``csv`` supported in the fake).
            layout_name (str | None): Layout bookmark name (e.g. ``layout_3``).

        Returns:
            (str) CSV text with Entity ID / Asset Name / Image columns.

        Raises:
            (ValueError) If ``format`` is not ``csv``.
        """
        if format != "csv":
            raise ValueError(f"fake export_page only supports csv, got {format!r}")
        self.export_calls.append((int(page_id), format, layout_name))
        lines = ["Entity ID,Asset Name,Image"]
        for record in self._worklist:
            entity_id = record.get("id", "")
            code = record.get("code", "")
            image = record.get("image") or ""
            lines.append(f"{entity_id},{code},{image}")
        return "\n".join(lines) + "\n"

    def find(
        self,
        entity_type: str,
        filters: list[Any] | tuple[Any, ...] | dict[str, Any],
        fields: list[str] | None = None,
        order: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Return synthetic entities for worklist, Note, or Attachment queries.

        Args:
            entity_type (str): ShotGrid entity type.
            filters (list | tuple | dict): Find filters.
            fields (list[str] | None): Requested fields (unused; full records returned).
            order (list[dict[str, str]] | None): Optional sort.
            **kwargs: Ignored extra Shotgun find kwargs.

        Returns:
            (list[dict[str, Any]]) Matching synthetic records.

        Raises:
            (ValueError) If the entity type or filter shape is unsupported.
        """
        del fields, kwargs  # fake returns full stored records
        filter_list: list[Any] = list(filters) if isinstance(filters, (list, tuple)) else []

        if entity_type == self._worklist_entity_type:
            return _apply_order([dict(r) for r in self._worklist], order)

        if entity_type == "Note":
            card_id = _linked_entity_id(filter_list, "note_links")
            if card_id is None:
                raise ValueError("Note find requires note_links is {type,id} filter")
            return _apply_order([dict(n) for n in self._notes_by_card.get(card_id, [])], order)

        if entity_type == "Attachment":
            card_id = _linked_entity_id(filter_list, "attachment_links")
            if card_id is None:
                raise ValueError("Attachment find requires attachment_links is {type,id} filter")
            return _apply_order([dict(a) for a in self._attachments_by_card.get(card_id, [])], order)

        raise ValueError(f"unsupported fake entity type: {entity_type}")

    def download_attachment(
        self, attachment: dict[str, Any] | bool = False, file_path: str | None = None, attachment_id: int | None = None
    ) -> str | bytes | None:
        """Write configured bytes to ``file_path`` or return them.

        Args:
            attachment (dict[str, Any] | bool): Optional attachment dict with ``id``.
            file_path (str | None): Destination path when downloading to disk.
            attachment_id (int | None): Attachment id when not passed via ``attachment``.

        Returns:
            (str | bytes | None) ``file_path`` when writing to disk, else bytes.

        Raises:
            (ValueError) If the attachment id is missing or has no configured bytes.
        """
        aid = attachment_id
        if aid is None and isinstance(attachment, dict):
            aid = attachment.get("id")
        if aid is None:
            raise ValueError("attachment_id is required")
        aid = int(aid)
        data = self._file_bytes.get(aid)
        if data is None:
            raise ValueError(f"no fake file bytes for attachment {aid}")

        if file_path:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            self.downloaded.append((aid, str(path)))
            return str(path)

        self.downloaded.append((aid, ""))
        return data
