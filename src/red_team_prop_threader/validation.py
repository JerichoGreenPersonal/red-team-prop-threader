"""validation helpers for prop-threader user input and domain rules."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from red_team_prop_threader.domain import PersonRole, SupportingLink, PersonSelection, DedupePeopleResult
from red_team_prop_threader._errors import ValidationError


if TYPE_CHECKING:
    from collections.abc import Iterable

    from red_team_prop_threader.domain import PersonEntry


__all__ = ("dedupe_links", "dedupe_people", "infer_group_title", "normalize_group_title", "parse_supporting_links", "validate_channel_members")

# matches "Label: URL" where label is nonempty and URL is non-whitespace
_LINK_LINE_RE = re.compile(r"^(?P<label>.+?):\s+(?P<url>\S+)\s*$")

# matches S<digits> season tokens case-insensitively
_SEASON_RE = re.compile(r"S(\d+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# link parsing
# ---------------------------------------------------------------------------


def parse_supporting_links(text: str) -> tuple[SupportingLink, ...]:
    """Parse a multiline block of ``Label: https://...`` supporting-link entries.

    Blank lines and lines containing only whitespace are skipped.  Every
    non-blank line must strictly match the ``Label: URL`` format.

    Args:
        text: raw multiline text from user input.  May be blank.

    Returns:
        tuple[SupportingLink, ...]: parsed links in input order.

    Raises:
        ValidationError: if any non-blank line is malformed, has an empty
            label, or uses a non-HTTPS or relative URL.  The error message
            identifies the physical line number but never echoes query-string
            values.
    """
    results: list[SupportingLink] = []
    for line_num, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        match = _LINK_LINE_RE.match(line)
        if not match:
            raise ValidationError(f"line {line_num}: expected 'Label: https://...' format")
        label = match.group("label").strip()
        url = match.group("url")
        if not label:
            raise ValidationError(f"line {line_num}: label must not be empty")
        _validate_link_url(url, line_num)
        results.append(SupportingLink(label, url))
    return tuple(results)


def _validate_link_url(url: str, line_num: int) -> None:
    """Validate that *url* is an absolute HTTPS URL with a host.

    Args:
        url: the URL string to validate.
        line_num: 1-based line number used in error messages.

    Raises:
        ValidationError: if the URL is not absolute HTTPS or lacks a host.
            Query-string values are never included in the error message.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValidationError(f"line {line_num}: URL must be absolute HTTPS (https://...)")
    if not parsed.netloc:
        raise ValidationError(f"line {line_num}: URL must include a host")


# ---------------------------------------------------------------------------
# link deduplication
# ---------------------------------------------------------------------------


def dedupe_links(group_links: tuple[SupportingLink, ...], asset_links: tuple[SupportingLink, ...]) -> tuple[SupportingLink, ...]:
    """Deduplicate supporting links by normalised URL across group and asset levels.

    When a group entry and an asset entry share the same normalised URL, the
    asset entry (including its label) takes precedence.  Non-overlapping entries
    are preserved in stable order (group first, then asset).

    Args:
        group_links: group-level supporting links.
        asset_links: asset-level supporting links.

    Returns:
        tuple[SupportingLink, ...]: deduplicated links in stable order.
    """
    asset_by_norm: dict[str, SupportingLink] = {_norm_url(link.url): link for link in asset_links}

    results: list[SupportingLink] = []
    for link in group_links:
        norm = _norm_url(link.url)
        if norm not in asset_by_norm:
            results.append(link)

    results.extend(asset_links)
    return tuple(results)


def _norm_url(url: str) -> str:
    """Normalise a URL for deduplication comparison.

    Lowercases scheme and host; removes an insignificant trailing slash from
    the path.  Query strings and fragments are excluded from the key.

    Args:
        url: the URL to normalise.

    Returns:
        str: the normalised URL key.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    return f"{scheme}://{host}{port}{path}"


# ---------------------------------------------------------------------------
# people deduplication
# ---------------------------------------------------------------------------


def dedupe_people(group_selection: PersonSelection, asset_selection: PersonSelection) -> DedupePeopleResult:
    """Deduplicate person entries across group and asset selections by Slack user ID.

    Precedence rules:

    - Asset-specific entries take precedence over group entries for the same user.
    - Within a single selection, :attr:`PersonRole.ANIMATOR` takes precedence
      over :attr:`PersonRole.ADDITIONAL` for the same user.
    - Stable input order is preserved for additional-people entries.

    Args:
        group_selection: group-level person selection.
        asset_selection: asset-level person selection.

    Returns:
        DedupePeopleResult: cleaned group and asset selections.
    """
    clean_asset = _dedup_selection(asset_selection)
    asset_ids = {e.slack_user_id for e in clean_asset.people}
    group_filtered = PersonSelection(tuple(e for e in group_selection.people if e.slack_user_id not in asset_ids))
    clean_group = _dedup_selection(group_filtered)
    return DedupePeopleResult(group=clean_group, asset=clean_asset)


def _dedup_selection(selection: PersonSelection) -> PersonSelection:
    """Deduplicate entries within a single PersonSelection.

    ANIMATOR takes precedence over ADDITIONAL for the same Slack user ID.
    Stable order is preserved using first-seen position.

    Args:
        selection: the selection to deduplicate.

    Returns:
        PersonSelection: deduplicated selection in stable order.
    """
    seen: dict[str, PersonEntry] = {}
    for entry in selection.people:
        if entry.slack_user_id not in seen or (entry.role == PersonRole.ANIMATOR and seen[entry.slack_user_id].role == PersonRole.ADDITIONAL):
            seen[entry.slack_user_id] = entry
    return PersonSelection(tuple(seen.values()))


# ---------------------------------------------------------------------------
# group title helpers
# ---------------------------------------------------------------------------


def normalize_group_title(value: str) -> str:
    """Normalise a group title to canonical uppercase form.

    Strips surrounding whitespace, collapses repeated internal whitespace to a
    single space, converts to uppercase, and removes one optional trailing
    colon.

    Args:
        value: raw group title string.

    Returns:
        str: normalised uppercase title without a trailing colon.
    """
    text = re.sub(r"\s+", " ", value.strip()).strip().upper()
    if text.endswith(":"):
        text = text[:-1].rstrip()
    return text


def infer_group_title(assets: Iterable[str]) -> str:
    """Infer a canonical group title from asset names by finding a common season token.

    Finds ``S<number>`` tokens (case-insensitive) in each asset name.  Returns
    the canonical title only when every asset contains exactly one unique season
    number and all share the same number.

    Args:
        assets: iterable of asset name strings.

    Returns:
        str: ``"SEASON <N> PROP REQUEST THREADS:"`` when a single common season
            is found, otherwise an empty string.
    """
    asset_list = list(assets)
    if not asset_list:
        return ""

    common: str | None = None
    for name in asset_list:
        tokens = _SEASON_RE.findall(name)
        unique = set(tokens)
        if len(unique) != 1:
            return ""
        season = next(iter(unique))
        if common is None:
            common = season
        elif season != common:
            return ""

    return f"SEASON {common} PROP REQUEST THREADS:" if common is not None else ""


# ---------------------------------------------------------------------------
# channel member validation
# ---------------------------------------------------------------------------


def validate_channel_members(selected_ids: set[str], member_ids: set[str]) -> set[str]:
    """Return selected Slack IDs that are absent from a channel member collection.

    Args:
        selected_ids: Slack user IDs selected for an operation.
        member_ids: Slack user IDs that are members of the target channel.

    Returns:
        set[str]: IDs in *selected_ids* that are not in *member_ids*.
    """
    return selected_ids - member_ids
