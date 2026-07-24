from __future__ import annotations

import re
import shutil
from pathlib import Path
from datetime import date, timedelta


_DAY_FOLDER = re.compile(r"^[A-Z]{3}_(\d{2})_(\d{2})_(\d{4})$")


def _parse_day_folder(name: str) -> date | None:
    match = _DAY_FOLDER.match(name)
    if match is None:
        return None
    month, day, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def cleanup_staging(root: Path, today: date, retention_days: int | None) -> list[Path]:
    """Delete staging day folders older than the retention window.

    Args:
        root (Path): Staging root containing ``DAY_MM_DD_YYYY`` folders.
        today (date): Current local date; today's folder is never removed.
        retention_days (int | None): Days to retain; ``None`` disables cleanup.

    Returns:
        (list[Path]) Paths of deleted day folders.
    """
    if retention_days is None or not Path(root).is_dir():
        return []

    cutoff = today - timedelta(days=retention_days)
    deleted: list[Path] = []

    for entry in Path(root).iterdir():
        if not entry.is_dir():
            continue
        folder_date = _parse_day_folder(entry.name)
        if folder_date is None or folder_date == today or folder_date > cutoff:
            continue
        shutil.rmtree(entry)
        deleted.append(entry)

    return deleted
