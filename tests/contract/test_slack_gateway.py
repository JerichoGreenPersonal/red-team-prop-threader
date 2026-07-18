"""live contract tests for Slack gateway read-only checks.

skipped unless RUN_SLACK_CONTRACT=1. these tests must not write messages or
canvas content.
"""

from __future__ import annotations

import os

import pytest

from red_team_prop_threader.config import Settings
from red_team_prop_threader.slack_gateway import SlackGateway


_DEV_CHANNEL = "C0B4GJSA1G8"


@pytest.mark.slack_contract
def test_slack_gateway_readonly_dev_channel_access() -> None:
    """Validate bot auth, private channel access, members, and canvas discovery.

    Raises:
        pytest.skip.Exception: unless RUN_SLACK_CONTRACT=1 is set.
    """
    if os.environ.get("RUN_SLACK_CONTRACT") != "1":
        pytest.skip("set RUN_SLACK_CONTRACT=1 to run live Slack contract tests")

    settings = Settings.from_env()
    gateway = SlackGateway.from_settings(settings)

    auth = gateway.auth_test()
    assert auth.get("ok") is True or auth.get("user_id")

    channel = gateway.get_conversation_info(_DEV_CHANNEL)
    assert channel.get("id") == _DEV_CHANNEL

    members = gateway.get_conversation_members(_DEV_CHANNEL)
    assert members, "expected at least one channel member"

    properties = channel.get("properties") or {}
    canvas = properties.get("canvas") if isinstance(properties, dict) else None
    if isinstance(canvas, dict):
        file_id = canvas.get("file_id") or canvas.get("id")
        if isinstance(file_id, str) and file_id:
            file_info = gateway.get_file_info(file_id)
            assert file_info.get("id") == file_id
