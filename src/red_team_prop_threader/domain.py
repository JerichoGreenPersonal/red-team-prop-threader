"""immutable domain types for the prop-threader application."""

from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass


__all__ = ("DedupePeopleResult", "ImportResult", "ImportedAsset", "OperationKind", "PersonEntry", "PersonRole", "PersonSelection", "SupportingLink")


@dataclass(frozen=True, slots=True)
class SupportingLink:
    """immutable supporting link with a human-readable label and URL."""

    label: str
    url: str


@dataclass(frozen=True, slots=True)
class ImportedAsset:
    """immutable record for a single asset imported from ShotGrid."""

    entity_id: int
    name: str
    url: str
    source_index: int


@dataclass(frozen=True, slots=True)
class ImportResult:
    """immutable result of an asset import batch."""

    assets: tuple[ImportedAsset, ...]
    duplicate_count: int


class OperationKind(StrEnum):
    """discrete kinds of operations in a prop-request workflow."""

    POST_SUMMARY = "post_summary"
    POST_ASSET = "post_asset"
    INDEX_ASSET = "index_asset"
    INDEX_PRIMARY_ASSET = "index_primary_asset"
    RETIRE_PRIOR_LATEST = "retire_prior_latest"
    FINALIZE_SUMMARY = "finalize_summary"


class PersonRole(StrEnum):
    """role a person holds within a prop-request selection."""

    ANIMATOR = "animator"
    ADDITIONAL = "additional"


@dataclass(frozen=True, slots=True)
class PersonEntry:
    """immutable person entry identified by Slack user ID and role."""

    slack_user_id: str
    role: PersonRole


@dataclass(frozen=True, slots=True)
class PersonSelection:
    """immutable ordered collection of person entries."""

    people: tuple[PersonEntry, ...]


@dataclass(frozen=True, slots=True)
class DedupePeopleResult:
    """immutable result of deduplicating group-level and asset-level person selections."""

    group: PersonSelection
    asset: PersonSelection
