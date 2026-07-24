from datetime import date
from pathlib import Path

import pytest

from review_prep.paths import assert_local_or_unc, asset_staging_dir, sanitize_asset_name


def test_sanitize_strips_invalid_windows_chars():
    assert sanitize_asset_name('a<>:"/\\|?*b') == "a_________b"


def test_asset_staging_dir_layout():
    root = Path("D:/ReviewPrep")
    p = asset_staging_dir(root, date(2026, 7, 13), "destruction kit interior", 12345)
    assert p == Path("D:/ReviewPrep/MON_07_13_2026/destruction_kit_interior_12345")


def test_reject_mapped_drive_letter_only_relative_claim():
    # UNC and normal paths OK; empty rejected
    assert_local_or_unc(Path("D:/ReviewPrep"))
    assert_local_or_unc(Path("//server/share/ReviewPrep"))
    with pytest.raises(ValueError):
        assert_local_or_unc(Path(""))
