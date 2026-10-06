"""tests for parsing Flightdeck mint_group inbox jobs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from red_team_prop_threader.cl_jobs import MintGroupPerson, parse_mint_group_job


if TYPE_CHECKING:
    from pathlib import Path


def _job(**overrides: object) -> dict:
    data = {
        "kind": "mint_group",
        "job_id": "j1",
        "created_at": "2026-10-02T22:15:00Z",
        "sent_by": "jgreen2",
        "flightdeck_version": "2.7.0",
        "mode": "test",
        "test_channel_id": "C0B4GJSA1G8",
        "tab_title": "S32 KC_MU5",
        "season_id": "S32",
        "group": {
            "title": "S32 KCMU5 OS Assets",
            "channel_id": "C02PR101SGH",
            "creative_stakeholder": {"name": "Eduardo Agostini", "email": "eagostini@respawn.com"},
            "additional_stakeholders": [{"name": "Jason McKenzie", "email": "jamckenzie@respawn.com"}],
        },
        "assets": [
            {
                "asset_id": 38885,
                "name": "unearthed_king_foundation_02",
                "sg_url": "https://respawn.shotgunstudio.com/detail/Asset/38885",
                "ic_poc": [{"name": "Jared Bosse", "email": "jbosse@ea.com"}],
                "additional_ics": [],
                "shared_thread_with": None,
            },
            {
                "asset_id": 39302,
                "name": "unearthed_king_foundation_03",
                "sg_url": "https://respawn.shotgunstudio.com/detail/Asset/39302",
                "ic_poc": [],
                "additional_ics": [],
                "shared_thread_with": 38885,
            },
        ],
    }
    data.update(overrides)
    return data


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "j1.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_parse_mint_group_job(tmp_path: Path) -> None:
    """A full Flightdeck job parses into group, people, and assets."""
    job = parse_mint_group_job(_write(tmp_path, _job()))
    assert job is not None
    assert (job.job_id, job.mode, job.test_channel_id, job.season_id) == ("j1", "test", "C0B4GJSA1G8", "S32")
    assert job.group_title == "S32 KCMU5 OS Assets"
    assert job.channel_id == "C02PR101SGH"
    assert job.creative_stakeholder == MintGroupPerson("Eduardo Agostini", "eagostini@respawn.com")
    assert [a.asset_id for a in job.assets] == [38885, 39302]
    assert job.assets[0].ic_poc == (MintGroupPerson("Jared Bosse", "jbosse@ea.com"),)
    assert job.assets[1].shared_thread_with == 38885


def test_parse_rejects_other_kinds_and_bad_mode(tmp_path: Path) -> None:
    """Other kinds, unknown modes, and missing group titles return None."""
    assert parse_mint_group_job(_write(tmp_path, _job(kind="thread_message"))) is None
    assert parse_mint_group_job(_write(tmp_path, _job(mode="yolo"))) is None
    assert parse_mint_group_job(_write(tmp_path, _job(group={"title": "", "channel_id": "C1"}))) is None
