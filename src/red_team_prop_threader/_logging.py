"""logging filter that redacts secrets from log records without mutating caller-owned objects."""

from __future__ import annotations

import re
import logging
from urllib.parse import urlparse


__all__ = ("RedactionFilter",)

# matches all xox* slack token prefixes followed by non-whitespace
_SLACK_TOKEN_RE = re.compile(r"xox[bpars]-\S+")

# matches Authorization header values including Bearer tokens
_AUTH_HEADER_RE = re.compile(r"(Authorization\s*:\s*(?:Bearer\s+)?)\S+", re.IGNORECASE)

# matches a URL that has a query string; captures scheme+host+path separately
_URL_QUERY_RE = re.compile(r"(https?://[^\s?]+)\?\S*")

_REDACTED = "[REDACTED]"


class RedactionFilter(logging.Filter):
    """logging filter that redacts secrets from formatted log messages.

    Redacts:
    - Slack token forms (xoxb-, xoxp-, xoxa-, xoxr-, xoxs-)
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
    text = _AUTH_HEADER_RE.sub(r"\g<1>" + _REDACTED, text)
    text = _URL_QUERY_RE.sub(r"\1?" + _REDACTED, text)

    for secret in extra_secrets:
        if secret:
            text = text.replace(secret, _REDACTED)

    return text


def _strip_url_query(url: str) -> str:
    """Return *url* with the query string removed.

    Args:
        url: the URL to strip.

    Returns:
        str: the URL without query string or fragment.
    """
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl()
