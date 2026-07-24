from pathlib import Path

from review_prep.models import ClPolicy
from review_prep.settings import AppSettings, load_settings, save_settings


def test_defaults_and_roundtrip(tmp_path: Path):
    path = tmp_path / "settings.json"
    s = AppSettings.defaults()
    assert s.schedule_hour == 5
    assert s.schedule_minute == 0
    assert s.retention_days is None
    assert s.cl_policies["WIP"] == ClPolicy.SYNC_AND_OPEN.value
    save_settings(path, s)
    loaded = load_settings(path)
    assert loaded.staging_root == s.staging_root
    assert loaded.cl_policies["Source Art"] == ClPolicy.SYNC_ONLY.value
