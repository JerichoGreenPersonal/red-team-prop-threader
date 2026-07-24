"""immutable application settings loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import field, dataclass
from urllib.parse import urlparse

from red_team_prop_threader._errors import ConfigurationError


__all__ = ("Settings",)

_REQUIRED_SHOTGRID_HOST = "respawn.shotgunstudio.com"
_DEFAULT_SHOTGRID_URL = "https://respawn.shotgunstudio.com"


@dataclass(frozen=True, slots=True)
class Settings:
    """immutable application settings.

    Load via :meth:`from_env`.  Secret fields are excluded from repr.
    """

    slack_bot_token: str = field(repr=False)
    slack_signing_secret: str = field(repr=False)
    slack_app_token: str = field(repr=False)
    shotgrid_script_name: str
    shotgrid_script_key: str = field(repr=False)
    shotgrid_url: str
    slack_public_base_url: str
    shotgrid_test_page_id: int
    database_url: str
    test_postgres_url: str | None
    canvas_timezone: str
    web_host: str
    web_port: int
    worker_poll_seconds: int
    tunnel_command: str | None
    tunnel_health_url: str | None

    @classmethod
    def from_env(cls) -> Settings:
        """Load and validate settings from the current environment.

        Returns:
            Settings: a fully-validated, immutable settings object.

        Raises:
            ConfigurationError: if any required setting is absent, empty, or invalid.
        """
        slack_bot_token = _require_nonempty("SLACK_BOT_TOKEN")
        slack_signing_secret = _require_nonempty("SLACK_SIGNING_SECRET")
        slack_app_token = _require_nonempty("SLACK_APP_TOKEN")
        shotgrid_script_name = _require_nonempty("SHOTGRID_SCRIPT_NAME")
        shotgrid_script_key = _require_nonempty("SHOTGRID_SCRIPT_KEY")

        shotgrid_url = _parse_shotgrid_url(os.environ.get("SHOTGRID_URL", _DEFAULT_SHOTGRID_URL))
        slack_public_base_url = os.environ.get("SLACK_PUBLIC_BASE_URL", "https://prop-threader-dev.example.invalid")
        shotgrid_test_page_id = _parse_positive_int("SHOTGRID_TEST_PAGE_ID", os.environ.get("SHOTGRID_TEST_PAGE_ID", "23280"))
        database_url = os.environ.get("DATABASE_URL", "sqlite:///local/prop-threader.db")
        test_postgres_url = _optional_str("TEST_POSTGRES_URL")
        canvas_timezone = os.environ.get("CANVAS_TIMEZONE", "America/Los_Angeles")
        web_host = os.environ.get("WEB_HOST", "127.0.0.1")
        web_port = _parse_bounded_int("WEB_PORT", os.environ.get("WEB_PORT", "3000"), min_val=1, max_val=65535)
        worker_poll_seconds = _parse_positive_int("WORKER_POLL_SECONDS", os.environ.get("WORKER_POLL_SECONDS", "2"))
        tunnel_command = _optional_str("TUNNEL_COMMAND")
        tunnel_health_url = _optional_str("TUNNEL_HEALTH_URL")

        return cls(
            slack_bot_token=slack_bot_token,
            slack_signing_secret=slack_signing_secret,
            slack_app_token=slack_app_token,
            shotgrid_script_name=shotgrid_script_name,
            shotgrid_script_key=shotgrid_script_key,
            shotgrid_url=shotgrid_url,
            slack_public_base_url=slack_public_base_url,
            shotgrid_test_page_id=shotgrid_test_page_id,
            database_url=database_url,
            test_postgres_url=test_postgres_url,
            canvas_timezone=canvas_timezone,
            web_host=web_host,
            web_port=web_port,
            worker_poll_seconds=worker_poll_seconds,
            tunnel_command=tunnel_command,
            tunnel_health_url=tunnel_health_url,
        )


def _require_nonempty(key: str) -> str:
    """Return the value of a required nonempty environment variable.

    Args:
        key: the environment variable name.

    Returns:
        str: the non-empty stripped value.

    Raises:
        ConfigurationError: if the variable is absent or blank.
    """
    val = os.environ.get(key, "")
    stripped = val.strip()
    if not stripped:
        raise ConfigurationError(f"{key} is required and must not be empty")
    return stripped


def _optional_str(key: str) -> str | None:
    """Return an optional environment variable value, or None if absent/empty.

    Args:
        key: the environment variable name.

    Returns:
        str | None: the value if present and non-empty, otherwise None.
    """
    val = os.environ.get(key, "")
    return val if val.strip() else None


def _parse_shotgrid_url(raw: str) -> str:
    """Parse and validate the ShotGrid base URL.

    Args:
        raw: the raw URL string from the environment.

    Returns:
        str: the normalized URL without a trailing slash.

    Raises:
        ConfigurationError: if the URL is not HTTPS or does not use the required host.
    """
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ConfigurationError(f"SHOTGRID_URL must use HTTPS (got scheme {parsed.scheme!r})")
    if parsed.hostname != _REQUIRED_SHOTGRID_HOST:
        raise ConfigurationError("SHOTGRID_URL must have host respawn.shotgunstudio.com")
    return raw.rstrip("/")


def _parse_bounded_int(key: str, raw: str, *, min_val: int | None = None, max_val: int | None = None) -> int:
    """Parse an integer environment variable with optional bounds.

    Args:
        key: the environment variable name, used in error messages.
        raw: the raw string value to parse.
        min_val: optional inclusive lower bound.
        max_val: optional inclusive upper bound.

    Returns:
        int: the parsed integer.

    Raises:
        ConfigurationError: if the value is not a valid integer or is out of range.
    """
    if not raw or not raw.isascii() or not raw.isdecimal():
        raise ConfigurationError(f"{key} must use ASCII decimal digits")
    val = int(raw)
    if min_val is not None and val < min_val:
        raise ConfigurationError(f"{key} must be >= {min_val}")
    if max_val is not None and val > max_val:
        raise ConfigurationError(f"{key} must be <= {max_val}")
    return val


def _parse_positive_int(key: str, raw: str) -> int:
    """Parse a strictly positive integer environment variable.

    Args:
        key: the environment variable name.
        raw: the raw string value.

    Returns:
        int: the parsed positive integer.

    Raises:
        ConfigurationError: if the value is not a positive integer.
    """
    return _parse_bounded_int(key, raw, min_val=1)
