"""Tests for ReviewPrep Slack-spoke season JSON and INDEX/history parsing."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from red_team_prop_threader.spokes import permalink_parts, harvest_lookup_text, history_root_spokes, upsert_season_spoke, canvas_latest_spokes


if TYPE_CHECKING:
    from pathlib import Path


_SATELLITE_MD = """
## S30 Wildcard

**Creative Stakeholder:** unassigned

### uh_hopscotch
- :shotgrid: [ShotGrid](https://respawn.shotgunstudio.com/detail/Asset/39238)
- :slack3: [2026-01-01 12:00 PST](https://respawn.slack.com/archives/C02PGV4E6KV/p1000000000000000)
- :slack3: [2026-09-03 15:00 PDT](https://respawn.slack.com/archives/C02PGV4E6KV/p1784158834442809) — Latest

### leftover_name
- :shotgrid: [ShotGrid](https://respawn.shotgunstudio.com/detail/Asset/111)
"""


def test_canvas_latest_uses_latest_permalink_not_prior() -> None:
    """Latest canvas permalink wins; assets without Latest are omitted."""
    spokes = canvas_latest_spokes(_SATELLITE_MD)
    assert spokes[39238].permalink.endswith("p1784158834442809")
    assert 111 not in spokes
    assert spokes[39238].source == "canvas"
    assert spokes[39238].channel_id == "C02PGV4E6KV"
    assert spokes[39238].thread_ts == "1784158834.442809"


def test_history_roots_ignore_replies_and_keep_newest() -> None:
    """Channel history adopts the newest root and ignores replies."""
    messages = (
        {
            "ts": "10.0",
            "thread_ts": "10.0",
            "text": "https://respawn.shotgunstudio.com/detail/Asset/200 older",
        },
        {
            "ts": "20.0",
            "thread_ts": "20.0",
            "text": "<https://respawn.shotgunstudio.com/detail/Asset/200|asset>",
        },
        {
            "ts": "21.0",
            "thread_ts": "20.0",
            "text": "https://respawn.shotgunstudio.com/detail/Asset/200 reply",
        },
        {"ts": "5.0", "text": "no asset url"},
    )
    spokes = history_root_spokes(messages, channel_id="CABC")
    assert 200 in spokes
    assert spokes[200].thread_ts == "20.0"
    assert spokes[200].source == "search"
    assert spokes[200].permalink.endswith("/p20000000")


def test_history_roots_read_asset_url_from_blocks() -> None:
    """Threader-minted roots store the ShotGrid URL in Block Kit, not fallback text."""
    messages = (
        {
            "ts": "30.0",
            "thread_ts": "30.0",
            "text": ":threadparrot: Asset: frln_fueltank_lrg_01a — FRONTLINE GATE 0 OS BATCH 1 :threadparrot:",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            ":shotgrid: <https://respawn.shotgunstudio.com/detail/Asset/39202"
                            "|frln_fueltank_lrg_01a> (ShotGrid ID: 39202)"
                        ),
                    },
                }
            ],
        },
        {
            "ts": "31.0",
            "thread_ts": "30.0",
            "text": "reply",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "https://respawn.shotgunstudio.com/detail/Asset/39202 reply in blocks",
                    },
                }
            ],
        },
    )
    spokes = history_root_spokes(messages, channel_id="C0BJFK6TPPF")
    assert 39202 in spokes
    assert spokes[39202].thread_ts == "30.0"
    assert spokes[39202].source == "search"


def test_permalink_parts() -> None:
    """Archive permalinks split into channel id and dotted thread_ts."""
    channel, ts = permalink_parts("https://respawn.slack.com/archives/C02PGV4E6KV/p1784158834442809")
    assert channel == "C02PGV4E6KV"
    assert ts == "1784158834.442809"


def test_upsert_merges_one_asset_without_dropping_siblings(tmp_path: Path) -> None:
    """Season JSON upserts one asset key and keeps sibling assets."""
    root = tmp_path / "SG_Card_Links"
    first = upsert_season_spoke(
        root,
        season_id="S30",
        asset_id=1,
        permalink="https://respawn.slack.com/archives/C1/p1000000000000000",
        channel_id="C1",
        thread_ts="1.0",
        source="canvas",
        updated_at="t1",
    )
    assert first is True
    upsert_season_spoke(
        root,
        season_id="S30",
        asset_id=2,
        permalink="https://respawn.slack.com/archives/C1/p2000000000000000",
        channel_id="C1",
        thread_ts="2.0",
        source="search",
        updated_at="t2",
    )
    data = json.loads((root / "slack_threads" / "S30.json").read_text(encoding="utf-8-sig"))
    assert "1" in data["assets"]
    assert "2" in data["assets"]
    assert data["assets"]["2"]["source"] == "search"


def test_harvest_lookup_text_concatenates_string_fields() -> None:
    """Nested canvas lookup payloads contribute every string field."""
    text = harvest_lookup_text(
        [
            {"id": "s1", "markdown": _SATELLITE_MD},
            {"nested": [{"plain_text": "https://respawn.shotgunstudio.com/detail/Asset/9"}]},
        ]
    )
    assert "39238" in text
    assert "detail/Asset/9" in text


def test_upsert_reads_bom_and_does_not_write_bom(tmp_path: Path) -> None:
    """Existing UTF-8 BOM files are merged and rewritten without a BOM."""
    root = tmp_path / "SG_Card_Links"
    path = root / "slack_threads" / "S30.json"
    path.parent.mkdir(parents=True)
    payload = {
        "season_id": "S30",
        "assets": {
            "1": {
                "permalink": "https://respawn.slack.com/archives/C1/p1000000000000000",
                "channel_id": "C1",
                "thread_ts": "1.0",
                "source": "canvas",
                "updated_at": "t0",
            }
        },
    }
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))
    upsert_season_spoke(
        root,
        season_id="S30",
        asset_id=2,
        permalink="https://respawn.slack.com/archives/C1/p2000000000000000",
        channel_id="C1",
        thread_ts="2.0",
        source="search",
        updated_at="t1",
    )
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    data = json.loads(raw.decode("utf-8"))
    assert "1" in data["assets"]
    assert "2" in data["assets"]


def test_upsert_skips_corrupt_season_file(tmp_path: Path) -> None:
    """Corrupt season files are left unchanged."""
    root = tmp_path / "SG_Card_Links"
    path = root / "slack_threads" / "S30.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert (
        upsert_season_spoke(
            root,
            season_id="S30",
            asset_id=1,
            permalink="https://x",
            channel_id="C",
            thread_ts="1.0",
            source="canvas",
            updated_at="t",
        )
        is False
    )
    assert path.read_text(encoding="utf-8") == "{not json"


def test_upsert_skips_when_season_missing(tmp_path: Path) -> None:
    """No season token means no write."""
    assert (
        upsert_season_spoke(
            tmp_path,
            season_id="",
            asset_id=9,
            permalink="https://x",
            channel_id="C",
            thread_ts="1.0",
            source="canvas",
            updated_at="t",
        )
        is False
    )
    slack_dir = tmp_path / "slack_threads"
    assert not slack_dir.exists() or not list(slack_dir.glob("*.json"))
