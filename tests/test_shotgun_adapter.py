"""Tests for the ShotGrid worklist adapter and delivery comment selection."""

from __future__ import annotations

from pathlib import Path

from tests.fakes.fake_shotgun import FakeShotgun
from review_prep.shotgun_adapter import Card, Comment, Attachment, ShotGridAdapter, latest_delivery_comment


def test_latest_delivery_comment_skips_later_internal() -> None:
    comments = [
        Comment(id=3, text="thanks", created="2026-07-23T12:00:00"),
        Comment(id=2, text="Source Art CL is 99", created="2026-07-23T11:00:00"),
        Comment(id=1, text="hello", created="2026-07-23T10:00:00"),
    ]
    latest = latest_delivery_comment(comments)
    assert latest is not None
    assert latest.id == 2


def test_latest_delivery_comment_none_when_no_delivery() -> None:
    comments = [Comment(id=1, text="thanks", created="2026-07-23T12:00:00"), Comment(id=2, text="hello", created="2026-07-23T11:00:00")]
    assert latest_delivery_comment(comments) is None


def test_latest_delivery_comment_picks_newest_delivery() -> None:
    comments = [
        Comment(id=1, text="Source Art CL is 10", created="2026-07-23T10:00:00"),
        Comment(id=2, text="WIP CL 20", created="2026-07-23T12:00:00"),
        Comment(id=3, text="ok", created="2026-07-23T13:00:00"),
    ]
    latest = latest_delivery_comment(comments)
    assert latest is not None
    assert latest.id == 2


def test_find_worklist_maps_cards() -> None:
    fake = FakeShotgun(
        worklist=[
            {"id": 38811, "code": "destruction_kit", "image": "https://example/thumb.jpg", "sg_status_list": "ip"},
            {"id": 1, "code": "other", "image": None},
        ]
    )
    adapter = ShotGridAdapter(fake, entity_type="Asset", filters=[], fields=["id", "code", "image", "sg_status_list"])
    cards = adapter.find_worklist()
    assert cards == [
        Card(
            id=38811,
            code="destruction_kit",
            thumbnail_url="https://example/thumb.jpg",
            raw_fields={"id": 38811, "code": "destruction_kit", "image": "https://example/thumb.jpg", "sg_status_list": "ip"},
        ),
        Card(id=1, code="other", thumbnail_url=None, raw_fields={"id": 1, "code": "other", "image": None}),
    ]


def test_list_comments_and_attachments() -> None:
    fake = FakeShotgun(
        worklist=[{"id": 10, "code": "a", "image": None}],
        notes_by_card={
            10: [
                {"id": 3, "content": "thanks", "created_at": "2026-07-23T12:00:00"},
                {"id": 2, "content": "Source Art CL is 99", "created_at": "2026-07-23T11:00:00"},
            ]
        },
        attachments_by_card={10: [{"id": 100, "filename": "review.zip", "file_size": 12, "created_at": "2026-07-23T09:00:00"}]},
    )
    adapter = ShotGridAdapter(fake, entity_type="Asset", filters=[], fields=["id", "code", "image"])
    comments = adapter.list_comments(10)
    assert comments[0] == Comment(id=3, text="thanks", created="2026-07-23T12:00:00")
    delivery = latest_delivery_comment(comments)
    assert delivery is not None
    assert delivery.id == 2

    attachments = adapter.list_attachments(10)
    assert attachments == [
        Attachment(
            id=100, filename="review.zip", file_size=12, raw_fields={"id": 100, "filename": "review.zip", "file_size": 12, "created_at": "2026-07-23T09:00:00"}
        )
    ]


def test_download_attachment_writes_file(tmp_path: Path) -> None:
    fake = FakeShotgun(file_bytes={55: b"zip-bytes"})
    adapter = ShotGridAdapter(fake, entity_type="Asset")
    dest = tmp_path / "out" / "review.zip"
    result = adapter.download_attachment(55, dest)
    assert result == dest
    assert dest.read_bytes() == b"zip-bytes"
    assert fake.downloaded == [(55, str(dest))]
