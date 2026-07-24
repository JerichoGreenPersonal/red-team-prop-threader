"""Tests for the safety-first P4 adapter."""

from __future__ import annotations

from tests.fakes.fake_p4 import FakeP4
from review_prep.p4_adapter import P4Adapter, P4FilePlan


def test_skips_open_files_and_syncs_siblings() -> None:
    fake = FakeP4(
        describe={11290000: ["//depot/a.ma", "//depot/b.ma"]}, opened={"//depot/a.ma"}, map={"//depot/a.ma": "D:/ws/a.ma", "//depot/b.ma": "D:/ws/b.ma"}
    )
    adapter = P4Adapter(runner=fake, client="my_client")
    results = adapter.sync_cl(11290000)
    by_depot = {r.depot: r for r in results}
    assert by_depot["//depot/a.ma"].skipped is True
    assert by_depot["//depot/b.ma"].skipped is False
    assert fake.synced == ["//depot/b.ma@11290000"]


def test_preview_marks_open_unsafe() -> None:
    fake = FakeP4(describe={1: ["//depot/a.ma"]}, opened={"//depot/a.ma"}, map={"//depot/a.ma": "D:/ws/a.ma"})
    adapter = P4Adapter(client="c", runner=fake)
    plans = adapter.preview_sync(1)
    assert plans == [P4FilePlan(depot="//depot/a.ma", local="D:/ws/a.ma", action="edit", safe=False, skip_reason="open")]


def test_skips_writable_conflict_siblings_continue() -> None:
    fake = FakeP4(
        describe={2: ["//depot/w.ma", "//depot/ok.ma"]},
        opened=set(),
        map={"//depot/w.ma": "D:/ws/w.ma", "//depot/ok.ma": "D:/ws/ok.ma"},
        writable={"//depot/w.ma"},
    )
    adapter = P4Adapter(client="c", runner=fake)
    results = adapter.sync_cl(2)
    by_depot = {r.depot: r for r in results}
    assert by_depot["//depot/w.ma"].skipped is True
    assert by_depot["//depot/w.ma"].skip_reason == "writable_conflict"
    assert by_depot["//depot/ok.ma"].skipped is False
    assert fake.synced == ["//depot/ok.ma@2"]


def test_describe_cl_lists_depot_files() -> None:
    fake = FakeP4(describe={9: ["//depot/a.ma", "//depot/b.ma"]}, map={"//depot/a.ma": "D:/ws/a.ma", "//depot/b.ma": "D:/ws/b.ma"})
    adapter = P4Adapter(client="c", runner=fake)
    assert adapter.describe_cl(9) == [("//depot/a.ma", "edit"), ("//depot/b.ma", "edit")]


def test_sync_exit_0_clobber_message_marks_skipped() -> None:
    """Real sync can exit 0 yet still emit clobber text — must not report success."""
    fake = FakeP4(
        describe={3: ["//depot/c.ma", "//depot/ok.ma"]},
        map={"//depot/c.ma": "D:/ws/c.ma", "//depot/ok.ma": "D:/ws/ok.ma"},
        sync_clobber={"//depot/c.ma"},
    )
    adapter = P4Adapter(client="c", runner=fake)
    results = adapter.sync_cl(3)
    by_depot = {r.depot: r for r in results}
    assert by_depot["//depot/c.ma"].skipped is True
    assert by_depot["//depot/c.ma"].skip_reason == "writable_conflict"
    assert by_depot["//depot/ok.ma"].skipped is False
    assert fake.synced == ["//depot/ok.ma@3"]


def test_mid_cl_sync_error_continues_siblings() -> None:
    """Per-file sync failure must not abort the rest of the changelist."""
    fake = FakeP4(
        describe={4: ["//depot/bad.ma", "//depot/good.ma"]},
        map={"//depot/bad.ma": "D:/ws/bad.ma", "//depot/good.ma": "D:/ws/good.ma"},
        sync_errors={"//depot/bad.ma"},
    )
    adapter = P4Adapter(client="c", runner=fake)
    results = adapter.sync_cl(4)
    by_depot = {r.depot: r for r in results}
    assert by_depot["//depot/bad.ma"].skipped is True
    assert by_depot["//depot/bad.ma"].skip_reason is not None
    assert by_depot["//depot/bad.ma"].skip_reason.startswith("sync_error:")
    assert by_depot["//depot/good.ma"].skipped is False
    assert fake.synced == ["//depot/good.ma@4"]
