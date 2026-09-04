"""season tokens matching ReviewPrep grouping_season / grouping_season_with_fallback."""

from __future__ import annotations

import re


__all__ = ("grouping_season", "grouping_season_with_fallback")

_JIRA_PATCH_RE = re.compile(r"\b(\d{2})\.(\d+)\.(\d+)\b")
_SEASON_TOKEN_RE = re.compile(r"\bS(\d{2})(?:\.(\d+))?\b", re.I)


def _jira_patch_tuple(label: str) -> tuple[int, int, int] | None:
    match = _JIRA_PATCH_RE.search(label or "")
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = _SEASON_TOKEN_RE.search(label or "")
    if match:
        return (int(match.group(1)), int(match.group(2) or 0), 0)
    return None


def _lowest_jira_visible(labels: list[str]) -> str | None:
    scored: list[tuple[tuple[int, int, int], str]] = []
    for label in labels:
        parsed = _jira_patch_tuple(label)
        if parsed is None:
            continue
        scored.append((parsed, label.strip()))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0])
    return scored[0][1]


def grouping_season(labels: list[str]) -> str | None:
    """Map the lowest jira version to ``S30`` / ``S30.1`` (any major)."""
    lowest = _lowest_jira_visible(labels)
    if lowest is None:
        return None
    parsed = _jira_patch_tuple(lowest)
    if parsed is None:
        return None
    major, minor, _patch = parsed
    if minor >= 1:
        return f"S{major}.1"
    return f"S{major}"


def grouping_season_with_fallback(
    jira_labels: list[str],
    *,
    tags: list[str] | None = None,
    gantt_season: str = "",
) -> str | None:
    """Jira lowest season, then patch tag, then gantt season token. do not invent a season."""
    season = grouping_season(jira_labels)
    if season:
        return season
    season = grouping_season(tags or [])
    if season:
        return season
    gantt = (gantt_season or "").strip()
    match = _SEASON_TOKEN_RE.search(gantt)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2) or 0)
        return f"S{major}.1" if minor >= 1 else f"S{major}"
    return None
