"""logging filter that redacts secrets from log records without mutating caller-owned objects."""

from __future__ import annotations

import re
from typing import Any
import logging
from collections.abc import Mapping, Sequence


__all__ = ("RedactionFilter",)

# matches slack bot/user tokens and app-level socket mode tokens
_SLACK_TOKEN_RE = re.compile(r"(?:xox[bpars]-|xapp-)\S+")

# matches quoted Authorization fields in mapping-style representations
_QUOTED_AUTH_RE = re.compile(r"""(?P<prefix>["']?Authorization["']?\s*[:=]\s*)(?P<quote>["'])(?P<value>.*?)(?P=quote)""", re.IGNORECASE)

# matches plain Authorization headers through the end of their line
_AUTH_HEADER_RE = re.compile(r"(Authorization\s*:\s*)[^\r\n]+", re.IGNORECASE)

# matches a URL that has a query string; captures scheme+host+path separately
_URL_QUERY_RE = re.compile(r"(https?://[^\s?]+)\?\S*", re.IGNORECASE)

_REDACTED = "[REDACTED]"


class RedactionFilter(logging.Filter):
    """logging filter that redacts secrets from formatted log messages.

    Redacts:
    - Slack token forms (xoxb-, xoxp-, xoxa-, xoxr-, xoxs-, xapp-)
    - Authorization header values including Bearer tokens
    - URL query strings (scheme, host, and path are preserved)
    - Any extra secrets provided at construction time

    The filter modifies ``record.msg`` to the fully-redacted formatted text and
    clears ``record.args`` to prevent double-formatting.  Caller-owned arg
    objects are never mutated.

    Args:
        extra_secrets: optional tuple of additional literal strings to redact.
        name: passed through to :class:`logging.Filter`.
    """

    def __init__(self, extra_secrets: tuple[str, ...] = (), name: str = "") -> None:
        """Initialise the filter with optional extra secrets.

        Args:
            extra_secrets: literal secret strings to redact in addition to the
                built-in patterns.
            name: logger name prefix; passed to :class:`logging.Filter`.
        """
        super().__init__(name)
        self._extra_secrets = extra_secrets

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact secrets from *record* in-place and allow every record through.

        The formatted message (``record.getMessage()``) is computed once, then
        redacted.  ``record.msg`` is replaced with the safe text and
        ``record.args`` is cleared so that the standard formatter does not
        re-apply ``%``-substitution.

        Args:
            record: the log record to redact.

        Returns:
            bool: always True (every record is passed through after redaction).
        """
        record.msg = _sanitize_value(record.msg, self._extra_secrets)
        record.args = _sanitize_value(record.args, self._extra_secrets)

        try:
            text = record.getMessage()
        except (TypeError, ValueError):
            text = str(record.msg)

        text = _redact(text, self._extra_secrets)

        record.msg = text
        record.args = None
        return True


def _redact(text: str, extra_secrets: tuple[str, ...]) -> str:
    """Apply all redaction rules to *text*.

    Args:
        text: the formatted log message text.
        extra_secrets: additional literal strings to redact.

    Returns:
        str: the redacted text.
    """
    text = _SLACK_TOKEN_RE.sub(_REDACTED, text)
    text = _QUOTED_AUTH_RE.sub(r"\g<prefix>\g<quote>" + _REDACTED + r"\g<quote>", text)
    text = _AUTH_HEADER_RE.sub(r"\g<1>" + _REDACTED, text)
    text = _URL_QUERY_RE.sub(r"\1?" + _REDACTED, text)

    for secret in extra_secrets:
        if secret:
            text = text.replace(secret, _REDACTED)

    return text


def _sanitize_value(value: Any, extra_secrets: tuple[str, ...]) -> Any:
    """Recursively copy and sanitize a structured logging value.

    Args:
        value: caller-owned value to copy and sanitize.
        extra_secrets: additional literal strings to redact.

    Returns:
        Any: a sanitized copy suitable for log formatting.
    """
    if isinstance(value, str):
        return _redact(value, extra_secrets)
    if isinstance(value, Mapping):
        return {
            key: _REDACTED if isinstance(key, str) and key.casefold() == "authorization" else _sanitize_value(item, extra_secrets)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item, extra_secrets) for item in value)
    if isinstance(value, list):
        return [_sanitize_value(item, extra_secrets) for item in value]
    if isinstance(value, set):
        return {_sanitize_value(item, extra_secrets) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_sanitize_value(item, extra_secrets) for item in value)
    if isinstance(value, Sequence):
        return tuple(_sanitize_value(item, extra_secrets) for item in value)
    return value
