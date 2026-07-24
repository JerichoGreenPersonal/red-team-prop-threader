from pathlib import Path
from datetime import date, timedelta

from review_prep.retention import cleanup_staging


def _day_folder(d: date) -> str:
    day = d.strftime("%a").upper()[:3]
    return f"{day}_{d.strftime('%m_%d_%Y')}"


def _mkdir(root: Path, d: date) -> Path:
    path = root / _day_folder(d)
    path.mkdir(parents=True)
    return path


def test_none_retention_is_noop(tmp_path: Path) -> None:
    today = date(2026, 7, 24)
    old = _mkdir(tmp_path, today - timedelta(days=30))

    deleted = cleanup_staging(tmp_path, today, None)

    assert deleted == []
    assert old.exists()


def test_deletes_folders_beyond_retention(tmp_path: Path) -> None:
    today = date(2026, 7, 24)
    keep = _mkdir(tmp_path, today - timedelta(days=6))
    delete = _mkdir(tmp_path, today - timedelta(days=7))
    stale = _mkdir(tmp_path, today - timedelta(days=30))

    deleted = cleanup_staging(tmp_path, today, retention_days=7)

    assert delete in deleted
    assert stale in deleted
    assert keep.exists()
    assert not delete.exists()
    assert not stale.exists()


def test_never_deletes_today(tmp_path: Path) -> None:
    today = date(2026, 7, 24)
    today_dir = _mkdir(tmp_path, today)
    old = _mkdir(tmp_path, today - timedelta(days=1))

    deleted = cleanup_staging(tmp_path, today, retention_days=0)

    assert today_dir not in deleted
    assert today_dir.exists()
    assert not old.exists()


def test_ignores_non_day_folders(tmp_path: Path) -> None:
    today = date(2026, 7, 24)
    other = tmp_path / "scratch"
    other.mkdir()
    bad_name = tmp_path / "MON_13_07_2026"
    bad_name.mkdir()

    deleted = cleanup_staging(tmp_path, today, retention_days=1)

    assert deleted == []
    assert other.exists()
    assert bad_name.exists()


def test_missing_root_is_noop(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    deleted = cleanup_staging(missing, date(2026, 7, 24), retention_days=7)

    assert deleted == []
