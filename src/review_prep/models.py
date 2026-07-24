from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RouteState(str, Enum):
    NOT_PREPARED = "not_prepared"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    SYNCING = "syncing"
    READY_TO_LAUNCH = "ready_to_launch"
    SYNCED_ONLY = "synced_only"
    LAUNCHED = "launched"
    SKIPPED = "skipped"
    PARTIAL = "partial"
    FAILED = "failed"


class ClPolicy(str, Enum):
    IGNORE = "ignore"
    SYNC_ONLY = "sync_only"
    SYNC_AND_OPEN = "sync_and_open"


class DeliveryRouteKind(str, Enum):
    ATTACHMENT_ARCHIVE = "attachment_archive"
    ATTACHMENT_LOOSE = "attachment_loose"
    P4_CL = "p4_cl"


DEFAULT_CL_POLICIES: dict[str, ClPolicy] = {
    "Source Art": ClPolicy.SYNC_ONLY,
    "Preflight": ClPolicy.SYNC_ONLY,
    "WIP": ClPolicy.SYNC_AND_OPEN,
}


@dataclass(frozen=True)
class ParsedCl:
    label: str
    number: int
    raw: str

    @property
    def policy_key(self) -> str:
        return self.label if self.label in DEFAULT_CL_POLICIES else "Unknown"
