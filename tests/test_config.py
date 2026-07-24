"""Tests for configuration loading and logging redaction."""

from __future__ import annotations

from typing import TYPE_CHECKING
import logging

import pytest

from red_team_prop_threader.config import Settings
from red_team_prop_threader._errors import ConfigurationError
from red_team_prop_threader._logging import RedactionFilter


if TYPE_CHECKING:
    from collections.abc import Iterator


_ENV_KEYS = (
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "SLACK_APP_TOKEN",
    "SLACK_PUBLIC_BASE_URL",
    "SHOTGRID_URL",
    "SHOTGRID_SCRIPT_NAME",
    "SHOTGRID_SCRIPT_KEY",
    "SHOTGRID_TEST_PAGE_ID",
    "DATABASE_URL",
    "TEST_POSTGRES_URL",
    "CANVAS_TIMEZONE",
    "WEB_HOST",
    "WEB_PORT",
    "WORKER_POLL_SECONDS",
    "TUNNEL_COMMAND",
    "TUNNEL_HEALTH_URL",
    "PRIMARY_ASSET_INDEX_CHANNEL_ID",
)


@pytest.fixture(autouse=True)
def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear every supported setting before each configuration test."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set valid required settings."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "signing-secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "script-key")


# ---------------------------------------------------------------------------
# Settings — required fields
# ---------------------------------------------------------------------------


def test_settings_missing_required_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """All required fields missing raises ConfigurationError."""
    for key in ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN", "SHOTGRID_SCRIPT_NAME", "SHOTGRID_SCRIPT_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_settings_missing_slack_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing SLACK_BOT_TOKEN raises ConfigurationError."""
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    with pytest.raises(ConfigurationError, match="SLACK_BOT_TOKEN"):
        Settings.from_env()


def test_settings_missing_slack_app_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing SLACK_APP_TOKEN raises ConfigurationError."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.delenv("SLACK_APP_TOKEN", raising=False)
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    with pytest.raises(ConfigurationError, match="SLACK_APP_TOKEN"):
        Settings.from_env()


def test_settings_empty_slack_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty SLACK_BOT_TOKEN raises ConfigurationError."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "   ")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_settings_strips_required_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Required values, including secrets, are stripped before storage."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "  xoxb-test  ")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "  signing-secret  ")
    monkeypatch.setenv("SLACK_APP_TOKEN", "  xapp-test  ")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "  threader  ")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "  script-key  ")

    settings = Settings.from_env()

    assert settings.slack_bot_token == "xoxb-test"
    assert settings.slack_signing_secret == "signing-secret"
    assert settings.slack_app_token == "xapp-test"
    assert settings.shotgrid_script_name == "threader"
    assert settings.shotgrid_script_key == "script-key"


def test_configuration_errors_never_include_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuration errors never echo configured secret values."""
    sentinels = ("xoxb-SENTINEL-BOT", "SENTINEL-SIGNING", "xapp-SENTINEL-APP", "SENTINEL-SCRIPT-KEY")
    monkeypatch.setenv("SLACK_BOT_TOKEN", sentinels[0])
    monkeypatch.setenv("SLACK_SIGNING_SECRET", sentinels[1])
    monkeypatch.setenv("SLACK_APP_TOKEN", sentinels[2])
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", sentinels[3])
    monkeypatch.setenv("WEB_PORT", "invalid")

    with pytest.raises(ConfigurationError) as exc_info:
        Settings.from_env()

    assert all(secret not in str(exc_info.value) for secret in sentinels)


# ---------------------------------------------------------------------------
# Settings — SHOTGRID_URL validation
# ---------------------------------------------------------------------------


def test_settings_rejects_wrong_shotgrid_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-HTTPS SHOTGRID_URL raises ConfigurationError mentioning HTTPS."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_URL", "http://example.com")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    with pytest.raises(ConfigurationError, match="HTTPS"):
        Settings.from_env()


def test_settings_rejects_wrong_host_https(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTPS but wrong host raises ConfigurationError mentioning the required host."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_URL", "https://example.com")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    with pytest.raises(ConfigurationError, match=r"respawn\.shotgunstudio\.com"):
        Settings.from_env()


def test_settings_shotgrid_url_no_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    """SHOTGRID_URL is normalized without a trailing slash."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    monkeypatch.setenv("SHOTGRID_URL", "https://respawn.shotgunstudio.com/")
    s = Settings.from_env()
    assert s.shotgrid_url == "https://respawn.shotgunstudio.com"


# ---------------------------------------------------------------------------
# Settings — defaults
# ---------------------------------------------------------------------------


def test_primary_asset_index_channel_id_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRIMARY_ASSET_INDEX_CHANNEL_ID defaults to C04H4QZEYUE."""
    _set_required(monkeypatch)
    monkeypatch.delenv("PRIMARY_ASSET_INDEX_CHANNEL_ID", raising=False)
    settings = Settings.from_env()
    assert settings.primary_asset_index_channel_id == "C04H4QZEYUE"


def test_primary_asset_index_channel_id_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRIMARY_ASSET_INDEX_CHANNEL_ID can be overridden."""
    _set_required(monkeypatch)
    monkeypatch.setenv("PRIMARY_ASSET_INDEX_CHANNEL_ID", "C999OVERRIDE")
    settings = Settings.from_env()
    assert settings.primary_asset_index_channel_id == "C999OVERRIDE"


def test_primary_asset_index_canvas_id_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """PRIMARY_ASSET_INDEX_CANVAS_ID defaults to the pilot canvas file id."""
    _set_required(monkeypatch)
    monkeypatch.delenv("PRIMARY_ASSET_INDEX_CANVAS_ID", raising=False)
    settings = Settings.from_env()
    assert settings.primary_asset_index_canvas_id == "F0BKLFG5S0M"


def test_primary_asset_index_canvas_id_empty_uses_channel_canvas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty PRIMARY_ASSET_INDEX_CANVAS_ID falls back to channel-canvas discovery."""
    _set_required(monkeypatch)
    monkeypatch.setenv("PRIMARY_ASSET_INDEX_CANVAS_ID", "")
    settings = Settings.from_env()
    assert settings.primary_asset_index_canvas_id is None


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults are applied for all optional fields."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
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
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
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
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    monkeypatch.setenv("WEB_PORT", "notanumber")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_settings_port_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    """WEB_PORT of 0 is out of valid range and raises ConfigurationError."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    monkeypatch.setenv("WEB_PORT", "0")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


def test_settings_invalid_worker_poll_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-integer WORKER_POLL_SECONDS raises ConfigurationError."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    monkeypatch.setenv("WORKER_POLL_SECONDS", "abc")
    with pytest.raises(ConfigurationError):
        Settings.from_env()


@pytest.mark.parametrize("value", [" 3000", "3000 ", "+3000", "-1", "3_000", "\uff10"])
def test_settings_rejects_non_ascii_decimal_integers(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Integer settings reject whitespace, signs, underscores, and non-ASCII digits."""
    _set_required(monkeypatch)
    monkeypatch.setenv("WEB_PORT", value)

    with pytest.raises(ConfigurationError, match="ASCII decimal"):
        Settings.from_env()


@pytest.mark.parametrize("value", ["0", "65536"])
def test_settings_rejects_web_port_outside_bounds(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """WEB_PORT must be between 1 and 65535 inclusive."""
    _set_required(monkeypatch)
    monkeypatch.setenv("WEB_PORT", value)

    with pytest.raises(ConfigurationError, match="WEB_PORT"):
        Settings.from_env()


def test_settings_accepts_web_port_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    """WEB_PORT accepts both inclusive bounds."""
    _set_required(monkeypatch)
    monkeypatch.setenv("WEB_PORT", "1")
    assert Settings.from_env().web_port == 1
    monkeypatch.setenv("WEB_PORT", "65535")
    assert Settings.from_env().web_port == 65535


# ---------------------------------------------------------------------------
# Settings — secret safety
# ---------------------------------------------------------------------------


def test_settings_repr_hides_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """repr(settings) must not contain any secret value."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-supersecret")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "signing-supersecret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-supersecret")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key-supersecret")
    s = Settings.from_env()
    r = repr(s)
    assert "xoxb-supersecret" not in r
    assert "signing-supersecret" not in r
    assert "xapp-supersecret" not in r
    assert "key-supersecret" not in r


def test_settings_is_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings instances are immutable."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "secret")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.setenv("SHOTGRID_SCRIPT_NAME", "threader")
    monkeypatch.setenv("SHOTGRID_SCRIPT_KEY", "key")
    s = Settings.from_env()
    with pytest.raises((AttributeError, TypeError)):
        s.web_port = 9999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Logging redaction
# ---------------------------------------------------------------------------


def _make_record(msg: str, args: tuple[object, ...] | dict[str, object] = ()) -> logging.LogRecord:
    """Create a minimal log record for testing."""
    return logging.LogRecord(name="test", level=logging.INFO, pathname="", lineno=0, msg=msg, args=args, exc_info=None)


def test_redaction_filter_slack_token_xoxb() -> None:
    """xoxb- token is redacted from message text."""
    record = _make_record("token is xoxb-1234-5678-test")
    RedactionFilter().filter(record)
    assert "xoxb-1234-5678-test" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_redaction_filter_all_slack_prefixes() -> None:
    """All xox* and xapp- prefixes are redacted."""
    for prefix in ("xoxb-", "xoxp-", "xoxa-", "xoxr-", "xoxs-", "xapp-"):
        record = _make_record(f"token={prefix}12345")
        RedactionFilter().filter(record)
        assert prefix not in record.getMessage(), f"prefix {prefix} not redacted"


def test_redaction_filter_authorization_bearer() -> None:
    """Authorization: Bearer ... is redacted."""
    record = _make_record("Authorization: Bearer abc123supersecret")
    RedactionFilter().filter(record)
    assert "abc123supersecret" not in record.getMessage()


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        ("Authorization: Basic dXNlcjpwYXNz", "dXNlcjpwYXNz"),
        ("Authorization: Digest username=admin", "username=admin"),
        ("Authorization: ApiKey top-secret-key", "top-secret-key"),
        ("{'Authorization': 'Bearer abc123'}", "abc123"),
        ('{"Authorization": "Basic dXNlcjpwYXNz"}', "dXNlcjpwYXNz"),
    ],
)
def test_redaction_filter_complete_authorization_values(message: str, secret: str) -> None:
    """Formatted authorization values are completely redacted for every scheme."""
    record = _make_record(message)
    RedactionFilter().filter(record)
    assert secret not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_redaction_filter_mapping_authorization_does_not_mutate_input() -> None:
    """Authorization values in mapping arguments are recursively copied and redacted."""
    headers = {"Authorization": "Bearer abc123", "nested": {"items": ["safe", "xoxb-nested-secret"]}}
    record = _make_record("headers=%s", (headers,))

    RedactionFilter().filter(record)

    assert headers == {"Authorization": "Bearer abc123", "nested": {"items": ["safe", "xoxb-nested-secret"]}}
    assert "abc123" not in record.getMessage()
    assert "xoxb-nested-secret" not in record.getMessage()


def test_redaction_filter_direct_mapping_arguments() -> None:
    """Direct logging mapping arguments sanitize Authorization before formatting."""
    headers: dict[str, object] = {"Authorization": "Basic dXNlcjpwYXNz"}
    record = _make_record("authorization=%(Authorization)s", (headers,))

    RedactionFilter().filter(record)

    assert headers["Authorization"] == "Basic dXNlcjpwYXNz"
    assert "dXNlcjpwYXNz" not in record.getMessage()


def test_redaction_filter_url_query_string() -> None:
    """URL query strings are stripped; scheme+host+path are preserved."""
    record = _make_record("fetching https://api.example.com/data?token=secret&key=value")
    RedactionFilter().filter(record)
    msg = record.getMessage()
    assert "secret" not in msg
    assert "value" not in msg
    assert "https://api.example.com/data" in msg


@pytest.mark.parametrize("url", ["HTTPS://api.example.com/data?token=secret", "HtTpS://api.example.com/data?token=secret"])
def test_redaction_filter_mixed_case_https_query(url: str) -> None:
    """Mixed-case HTTPS URLs have query strings redacted."""
    record = _make_record("fetching %s", (url,))
    RedactionFilter().filter(record)
    assert "secret" not in record.getMessage()
    assert url.split("?")[0] in record.getMessage()


def test_redaction_filter_structured_uppercase_https_query() -> None:
    """URLs nested in structured arguments are copied and query-redacted."""
    payload = {"requests": [{"url": "HTTPS://api.example.com/data?token=secret"}]}
    record = _make_record("payload=%s", (payload,))

    RedactionFilter().filter(record)

    assert payload["requests"][0]["url"].endswith("token=secret")  # type: ignore[index, union-attr]
    assert "secret" not in record.getMessage()


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
