"""Shared pytest fixtures for persistence-focused tests."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest


class FakeClock:
    """Deterministic mutable UTC clock for repository and lease tests."""

    def __init__(self, start: datetime | None = None) -> None:
        """Initialize at a fixed UTC instant unless a start is supplied."""
        self._now = start or datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        """Return the current fake instant."""
        return self._now

    def advance(self, *, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> None:
        """Advance the fake instant by the supplied duration."""
        self._now += timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    """Provide a deterministic clock shared by persistence test modules."""
    return FakeClock()
