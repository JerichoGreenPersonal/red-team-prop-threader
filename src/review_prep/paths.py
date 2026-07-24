from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*]')


def sanitize_asset_name(name: str) -> str:
    cleaned = _INVALID.sub("_", name.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or "asset"


def asset_staging_dir(
    root: Path, local_date: date, asset_name: str, shotgrid_id: int
) -> Path:
    day = local_date.strftime("%a").upper()[:3]
    folder = f"{day}_{local_date.strftime('%m_%d_%Y')}"
    leaf = f"{sanitize_asset_name(asset_name)}_{shotgrid_id}"
    return Path(root) / folder / leaf


def assert_local_or_unc(path: Path) -> Path:
    p = Path(path)
    if p == Path() or not str(p).strip():
        raise ValueError("staging root must be a local or UNC path")
    return p
