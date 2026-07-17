"""Live contract test for the ShotGrid page export API.

This test requires a live ShotGrid connection and will be skipped by default.
Set RUN_SHOTGRID_CONTRACT=1 and populate all required Settings env vars to run.
"""

from __future__ import annotations

import os

import pytest

from red_team_prop_threader.config import Settings
from red_team_prop_threader.shotgrid import ShotGridGateway


@pytest.mark.shotgrid_contract
def test_shotgrid_export_page_returns_nonempty_csv() -> None:
    """Live export of the configured test page returns nonempty CSV.

    Raises:
        pytest.skip.Exception: unless RUN_SHOTGRID_CONTRACT=1 is set.
    """
    if os.environ.get("RUN_SHOTGRID_CONTRACT") != "1":
        pytest.skip("set RUN_SHOTGRID_CONTRACT=1 to run live ShotGrid contract tests")
    settings = Settings.from_env()
    gw = ShotGridGateway.from_settings(settings)
    csv_text = gw.export_page(settings.shotgrid_test_page_id)
    assert csv_text, "export_page returned empty CSV"
