"""Safety-first Perforce adapter for exact-CL sync on the everyday client."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol
import subprocess
from dataclasses import dataclass


if TYPE_CHECKING:
    from collections.abc import Sequence


_DESCRIBE_FILE_RE = re.compile(r"^\.\.\.\s+(\S+)#\d+\s+(\S+)")
_FORBIDDEN_FLAGS = frozenset({"-f", "--force"})


class P4Error(Exception):
    """Raised when a ``p4`` command fails or returns unusable output."""


@dataclass(frozen=True)
class P4FilePlan:
    """Planned sync for one depot file.

    Attributes:
        depot (str): Depot path (e.g. ``//depot/a.ma``).
        local (str): Client local filesystem path.
        action (str): Changelist action (edit/add/delete/...).
        safe (bool): False when sync would force/clobber/revert.
        skip_reason (str | None): Why unsafe, if applicable.
    """

    depot: str
    local: str
    action: str
    safe: bool
    skip_reason: str | None


@dataclass(frozen=True)
class P4SyncResult:
    """Outcome of syncing one depot file.

    Attributes:
        depot (str): Depot path.
        local (str): Client local filesystem path.
        skipped (bool): True when the file was not synced.
        skip_reason (str | None): Why skipped, if applicable.
    """

    depot: str
    local: str
    skipped: bool
    skip_reason: str | None = None


class P4CommandRunner(Protocol):
    """Runs a ``p4`` argv and returns stdout text."""

    def run(self, args: Sequence[str]) -> str:
        """Execute ``args`` and return stdout.

        Args:
            args (Sequence[str]): Full command argv including executable.

        Returns:
            (str) Command stdout.
        """
        ...


class SubprocessP4Runner:
    """Shell out to the real ``p4`` executable."""

    def run(self, args: Sequence[str]) -> str:
        """Execute ``args`` via subprocess and return stdout.

        Args:
            args (Sequence[str]): Full command argv including executable.

        Returns:
            (str) Command stdout.

        Raises:
            (P4Error) If the process exits non-zero.
        """
        completed = subprocess.run(list(args), capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise P4Error(f"p4 exited {completed.returncode}: {detail}")
        return completed.stdout or ""


class P4Adapter:
    """Everyday-client P4 adapter: preview and exact-CL sync with unsafe skips.

    Never passes force/clobber/revert flags. Open or writable-conflict files are
    marked unsafe and skipped; siblings continue.
    """

    def __init__(self, *, client: str, runner: P4CommandRunner | None = None, p4_exe: str = "p4") -> None:
        """Initialize adapter for one Perforce client.

        Args:
            client (str): Everyday client name (``p4 -c``).
            runner (P4CommandRunner | None): Command runner; defaults to subprocess.
            p4_exe (str): ``p4`` executable path or name.
        """
        if not client:
            raise ValueError("client is required")
        self._client = client
        self._p4_exe = p4_exe
        self._runner: P4CommandRunner = runner if runner is not None else SubprocessP4Runner()

    def _run(self, *p4_args: str) -> str:
        """Run ``p4 -c CLIENT ...`` refusing unsafe flags."""
        if any(arg in _FORBIDDEN_FLAGS for arg in p4_args):
            raise P4Error(f"refusing unsafe p4 flags in {p4_args!r}")
        return self._runner.run([self._p4_exe, "-c", self._client, *p4_args])

    def describe_cl(self, cl: int) -> list[tuple[str, str]]:
        """List depot files and actions in a submitted changelist.

        Args:
            cl (int): Changelist number.

        Returns:
            (list[tuple[str, str]]) Pairs of ``(depot, action)``.
        """
        stdout = self._run("describe", "-s", str(cl))
        files: list[tuple[str, str]] = []
        for line in stdout.splitlines():
            match = _DESCRIBE_FILE_RE.match(line.strip())
            if match:
                files.append((match.group(1), match.group(2)))
        return files

    def _where_local(self, depot: str) -> str:
        """Resolve depot path to local client path via ``p4 where``."""
        stdout = self._run("where", depot)
        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("-"):
                continue
            parts = line.split(None, 2)
            if len(parts) >= 3 and parts[0] == depot:
                return parts[2]
        raise P4Error(f"p4 where did not resolve {depot}")

    def _is_opened(self, depot: str) -> bool:
        """Return True if the depot file is open on this client."""
        return bool(self._run("opened", depot).strip())

    def _has_writable_conflict(self, depot: str, cl: int) -> bool:
        """Detect writable local conflict via dry-run ``sync -n`` (never clobber)."""
        dry = self._run("sync", "-n", f"{depot}@{cl}")
        lowered = dry.lower()
        return "can't clobber" in lowered or "cannot clobber" in lowered

    def preview_sync(self, cl: int) -> list[P4FilePlan]:
        """Build a safety plan for exact-CL sync.

        Args:
            cl (int): Changelist number.

        Returns:
            (list[P4FilePlan]) Per-file plan with ``safe`` / ``skip_reason``.
        """
        plans: list[P4FilePlan] = []
        for depot, action in self.describe_cl(cl):
            local = self._where_local(depot)
            if self._is_opened(depot):
                plans.append(P4FilePlan(depot=depot, local=local, action=action, safe=False, skip_reason="open"))
                continue
            if self._has_writable_conflict(depot, cl):
                plans.append(P4FilePlan(depot=depot, local=local, action=action, safe=False, skip_reason="writable_conflict"))
                continue
            plans.append(P4FilePlan(depot=depot, local=local, action=action, safe=True, skip_reason=None))
        return plans

    def sync_cl(self, cl: int) -> list[P4SyncResult]:
        """Sync submitted files at exact CL revision; skip unsafe files only.

        Args:
            cl (int): Changelist number.

        Returns:
            (list[P4SyncResult]) Per-file sync outcomes.
        """
        results: list[P4SyncResult] = []
        for plan in self.preview_sync(cl):
            if not plan.safe:
                results.append(P4SyncResult(depot=plan.depot, local=plan.local, skipped=True, skip_reason=plan.skip_reason))
                continue
            # Exact-CL sync only — never -f / clobber / revert.
            self._run("sync", f"{plan.depot}@{cl}")
            results.append(P4SyncResult(depot=plan.depot, local=plan.local, skipped=False, skip_reason=None))
        return results
