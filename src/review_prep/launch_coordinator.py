"""Cadet launch coordinator with exactly-once daily launch leases."""

from __future__ import annotations

import json
import shlex
from typing import TYPE_CHECKING
import logging
from pathlib import Path
import subprocess
from dataclasses import field, dataclass

from review_prep.models import RouteState


if TYPE_CHECKING:
    from review_prep.state import StateRepo
    from review_prep.settings import AppSettings


_logger = logging.getLogger(__name__)

_CADET_MISSING_PROMPT = "Cadet is not running; enter apex_r5dev then use Open Again"
_CADET_PROCESS_NAMES = ("Cadet.SystemTray", "Cadet.Service")
_DEFAULT_CADET_CMD = "cadet"
_DEFAULT_TEMPLATE = '{cadet_cmd} --toolset apex_r5dev --app Maya --file "{file}"'

# Windows: detach child so launches survive the parent process.
_DETACHED_FLAGS = 0
if hasattr(subprocess, "DETACHED_PROCESS"):
    _DETACHED_FLAGS |= subprocess.DETACHED_PROCESS
if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
    _DETACHED_FLAGS |= subprocess.CREATE_NEW_PROCESS_GROUP


@dataclass
class LaunchReport:
    """Outcome of a launch_eligible or open_again pass.

    Attributes:
        local_date (str): Local calendar date associated with the report.
        launched (list[str]): File keys successfully handed to Cadet.
        skipped_leased (list[str]): File keys skipped because a lease was already held.
        blocked_cadet (bool): True when Cadet was not running (no successful leases taken).
        messages (list[str]): User-facing prompts and notices.
        errors (list[str]): Per-file launch errors.
    """

    local_date: str
    launched: list[str] = field(default_factory=list)
    skipped_leased: list[str] = field(default_factory=list)
    blocked_cadet: bool = False
    messages: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class LaunchCoordinator:
    """Open prepared DCC files through Cadet with exactly-once daily leases.

    ``launch_eligible`` consumes a lease per file for the local day.
    ``open_again`` bypasses leases and re-opens launchables from the manifest.
    """

    def __init__(self, *, settings: AppSettings, state: StateRepo) -> None:
        """Initialize with settings and state repository.

        Args:
            settings (AppSettings): User settings including Cadet launch templates.
            state (StateRepo): SQLite manifest for routes and launch leases.
        """
        self._settings = settings
        self._state = state

    def cadet_available(self) -> bool:
        """Return True when a Cadet SystemTray or Service process is running.

        Returns:
            (bool) True if Cadet.SystemTray or Cadet.Service appears in the process list.
        """
        try:
            completed = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, check=False)
        except OSError as exc:
            _logger.warning("Unable to query process list for Cadet: %s", exc)
            return False
        stdout = completed.stdout or ""
        return any(name in stdout for name in _CADET_PROCESS_NAMES)

    def launch_eligible(self, local_date: str) -> LaunchReport:
        """Launch READY_TO_LAUNCH files for ``local_date`` exactly once each.

        If Cadet is not running, logs a prompt, sets ``blocked_cadet``, and does
        not record successful leases.

        Args:
            local_date (str): Local calendar date (YYYY-MM-DD).

        Returns:
            (LaunchReport) Launch outcomes for the day.
        """
        report = LaunchReport(local_date=local_date)
        if not self.cadet_available():
            _logger.warning("%s", _CADET_MISSING_PROMPT)
            report.blocked_cadet = True
            report.messages.append(_CADET_MISSING_PROMPT)
            return report

        files = _launchables_from_routes(self._state.list_routes_for_date(local_date))
        for path in files:
            self._launch_with_lease(path, local_date, report)
        return report

    def open_again(self, card_ids: list[int]) -> LaunchReport:
        """Re-open launchable files for selected cards, bypassing daily leases.

        Performs no ShotGrid refresh, download, extract, or P4 sync.

        Args:
            card_ids (list[int]): ShotGrid card entity ids to re-open.

        Returns:
            (LaunchReport) Launch outcomes (``local_date`` empty; leases unused).
        """
        report = LaunchReport(local_date="")
        if not self.cadet_available():
            _logger.warning("%s", _CADET_MISSING_PROMPT)
            report.blocked_cadet = True
            report.messages.append(_CADET_MISSING_PROMPT)
            return report

        paths: list[Path] = []
        for card_id in card_ids:
            paths.extend(_launchables_from_routes(self._state.get_routes_for_card(card_id)))

        for path in _unique_paths(paths):
            self._launch_without_lease(path, report)
        return report

    def _launch_with_lease(self, path: Path, local_date: str, report: LaunchReport) -> None:
        """Claim a daily lease then launch; skip when the lease is already held."""
        file_key = _file_key(path)
        if not self._state.record_launch_lease(file_key, local_date):
            report.skipped_leased.append(file_key)
            _logger.info("Skipping already-leased file: %s", file_key)
            return
        try:
            self._popen_cadet(path)
        except (OSError, ValueError) as exc:
            msg = f"launch failed for {file_key}: {exc}"
            _logger.error("%s", msg)
            report.errors.append(msg)
            return
        report.launched.append(file_key)

    def _launch_without_lease(self, path: Path, report: LaunchReport) -> None:
        """Launch a file without recording a lease (Open Again)."""
        file_key = _file_key(path)
        try:
            self._popen_cadet(path)
        except (OSError, ValueError) as exc:
            msg = f"launch failed for {file_key}: {exc}"
            _logger.error("%s", msg)
            report.errors.append(msg)
            return
        report.launched.append(file_key)

    def _popen_cadet(self, path: Path) -> None:
        """Format the Cadet template for ``path`` and start a detached process."""
        argv = self._build_argv(path)
        _logger.info("Launching via Cadet: %s", argv)
        if _DETACHED_FLAGS:
            subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, creationflags=_DETACHED_FLAGS
            )
        else:
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)

    def _build_argv(self, path: Path) -> list[str]:
        """Resolve extension template and return argv for Popen."""
        ext = path.suffix.lower()
        templates = self._settings.cadet_launch_templates or {}
        template = templates.get(ext) or templates.get(ext.lstrip(".")) or _DEFAULT_TEMPLATE
        cadet_cmd = templates.get("cadet_cmd") or templates.get("_cadet_cmd") or _DEFAULT_CADET_CMD
        try:
            formatted = template.format(file=str(path), cadet_cmd=cadet_cmd)
        except KeyError as exc:
            raise ValueError(f"invalid Cadet launch template for {ext}: missing {exc}") from exc
        argv = shlex.split(formatted, posix=False)
        if not argv:
            raise ValueError(f"empty Cadet launch command for {path}")
        return argv


def _file_key(path: Path) -> str:
    """Stable lease key for a filesystem path."""
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _unique_paths(paths: list[Path]) -> list[Path]:
    """Preserve order while dropping duplicate file keys."""
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = _file_key(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _launchables_from_routes(routes: list[dict[str, object]]) -> list[Path]:
    """Extract launchable Paths from READY_TO_LAUNCH route detail JSON."""
    paths: list[Path] = []
    for route in routes:
        if route.get("state") != RouteState.READY_TO_LAUNCH.value:
            continue
        detail_raw = route.get("detail")
        if not isinstance(detail_raw, str):
            continue
        try:
            detail = json.loads(detail_raw)
        except json.JSONDecodeError:
            continue
        launchable = detail.get("launchable") if isinstance(detail, dict) else None
        if not isinstance(launchable, list):
            continue
        for item in launchable:
            if isinstance(item, str) and item:
                paths.append(Path(item))
    return _unique_paths(paths)
