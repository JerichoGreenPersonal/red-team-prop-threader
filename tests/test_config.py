"""Tests for configuration loading and logging redaction."""

from __future__ import annotations

import logging

import pytest

from red_team_prop_threader.config import Settings
from red_team_prop_threader._errors import ConfigurationError
from red_team_prop_threader._logging import RedactionFilter


# ---------------------------------------------------------------------------
# Settings — required fields
# ---------------------------------------------------------------------------


def test_settings_missing_required_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """All required fields missing raises ConfigurationError."""
    for key in ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SHOTGRID_SCRIPT_NAME", "SHOTGRID_SCRIPT_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_settings_missing_slack_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing SLACK_BOT_TOKEN raises ConfigurationError."""
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    with pytest.raises(ConfigurationError, match="SLACK_BOT_TOKEN"):
        Settings.from_env()


def test_settings_empty_slack_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty SLACK_BOT_TOKEN raises ConfigurationError."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "   ")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


# ---------------------------------------------------------------------------
# Settings — SHOTGRID_URL validation
# ---------------------------------------------------------------------------


def test_settings_rejects_wrong_shotgrid_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-HTTPS SHOTGRID_URL raises ConfigurationError mentioning HTTPS."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_URL", "http://example.com")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    with pytest.raises(ConfigurationError, match="HTTPS"):
        Settings.from_env()


def test_settings_rejects_wrong_host_https(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTPS but wrong host raises ConfigurationError mentioning the required host."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_URL", "https://example.com")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    with pytest.raises(ConfigurationError, match=r"respawn\.shotgunstudio\.com"):
        Settings.from_env()


def test_settings_shotgrid_url_no_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    """SHOTGRID_URL is normalized without a trailing slash."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    monkeypatch.setenv("SHOTGRID_URL", "https://respawn.shotgunstudio.com/")
    s = Settings.from_env()
    assert s.shotgrid_url == "https://respawn.shotgunstudio.com"


# ---------------------------------------------------------------------------
# Settings — defaults
# ---------------------------------------------------------------------------


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults are applied for all optional fields."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    for var in (
        "SHOTGRID_URL",
        "SLACK_PUBLIC_BASE_URL",
        "SHOTGRID_TEST_PAGE_ID",
        "DATABASE_URL",
        "CANVAS_TIMEZONE",
        "WEB_HOST",
        "WEB_PORT",
        "WORKER_POLL_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings.from_env()
    assert s.shotgrid_url == "https://respawn.shotgunstudio.com"
    assert s.slack_public_base_url == "https://prop-threader-dev.example.invalid"
    assert s.shotgrid_test_page_id == 23280
    assert s.database_url == "sqlite:///local/prop-threader.db"
    assert s.canvas_timezone == "America/Los_Angeles"
    assert s.web_host == "127.0.0.1"
    assert s.web_port == 3000
    assert s.worker_poll_seconds == 2


def test_settings_optional_fields_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optional fields absent from environment are None."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    monkeypatch.delenv("TEST_POSTGRES_URL", raising=False)
    monkeypatch.delenv("TUNNEL_COMMAND", raising=False)
    monkeypatch.delenv("TUNNEL_HEALTH_URL", raising=False)
    s = Settings.from_env()
    assert s.test_postgres_url is None
    assert s.tunnel_command is None
    assert s.tunnel_health_url is None


# ---------------------------------------------------------------------------
# Settings — integer parsing
# ---------------------------------------------------------------------------


def test_settings_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-integer WEB_PORT raises ConfigurationError."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    monkeypatch.setenv("WEB_PORT", "notanumber")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_settings_port_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """WEB_PORT of 0 is out of valid range and raises ConfigurationError."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    monkeypatch.setenv("WEB_PORT", "0")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_settings_invalid_worker_poll_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-integer WORKER_POLL_SECONDS raises ConfigurationError."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    monkeypatch.setenv("WORKER_POLL_SECONDS", "abc")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


# ---------------------------------------------------------------------------
# Settings — secret safety
# ---------------------------------------------------------------------------


def test_settings_repr_hides_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """repr(settings) must not contain any secret value."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-supersecret")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "signing-supersecret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key-supersecret")
    s = Settings.from_env()
    r = repr(s)
    assert "xoxb-supersecret" not in r
    assert "signing-supersecret" not in r
    assert "key-supersecret" not in r


def test_settings_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings instances are immutable."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    s = Settings.from_env()
    with pytest.raises((AttributeError, TypeError)):
        s.web_port = 9999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Logging redaction
# ---------------------------------------------------------------------------


def _make_record(msg: str, args: tuple[object, ...] = ()) -> logging.LogRecord:
    """Create a minimal log record for testing."""
    return logging.LogRecord(name="test", level=logging.INFO, pathname="", lineno=0, msg=msg, args=args, exc_info=None)


def test_redaction_filter_slack_token_xoxb() -> None:
    """xoxb- token is redacted from message text."""
    record = _make_record("token is xoxb-1234-5678-test")
    RedactionFilter().filter(record)
    assert "xoxb-1234-5678-test" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_redaction_filter_all_slack_prefixes() -> None:
    """All xox* prefixes are redacted."""
    for prefix in ("xoxb-", "xoxp-", "xoxa-", "xoxr-", "xoxs-"):
        record = _make_record(f"token={prefix}12345")
        RedactionFilter().filter(record)
        assert prefix not in record.getMessage(), f"prefix {prefix} not redacted"


def test_redaction_filter_authorization_bearer() -> None:
    """Authorization: Bearer ... is redacted."""
    record = _make_record("Authorization: Bearer abc123supersecret")
    RedactionFilter().filter(record)
    assert "abc123supersecret" not in record.getMessage()


def test_redaction_filter_url_query_string() -> None:
    """URL query strings are stripped; scheme+host+path are preserved."""
    record = _make_record("fetching https://api.example.com/data?token=secret&key=value")
    RedactionFilter().filter(record)
    msg = record.getMessage()
    assert "secret" not in msg
    assert "value" not in msg
    assert "https://api.example.com/data" in msg


def test_redaction_does_not_mutate_args() -> None:
    """Caller-owned args tuple is not mutated by redaction."""
    original_args: tuple[str, ...] = ("xoxb-secret",)
    record = _make_record("token=%s", original_args)
    RedactionFilter().filter(record)
    assert original_args[0] == "xoxb-secret"
    assert "xoxb-secret" not in record.getMessage()


def test_redaction_extra_secrets() -> None:
    """Configured extra secrets are redacted."""
    record = _make_record("key=my-script-key-abc")
    RedactionFilter(extra_secrets=("my-script-key-abc",)).filter(record)
    assert "my-script-key-abc" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()
