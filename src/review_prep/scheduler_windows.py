"""Windows Task Scheduler registration for daily prep and dashboard logon open."""

from __future__ import annotations

import getpass
import logging
from pathlib import Path
import subprocess


_logger = logging.getLogger(__name__)

DAILY_TASK_NAME = r"ReviewPrep\DailyPrep"
LOGON_TASK_NAME = r"ReviewPrep\OpenDashboard"


def register_daily_task(exe_path: str | Path, hour: int = 5, minute: int = 0) -> None:
    """Register a daily limited-rights task that runs the prep worker.

    Uses ``schtasks /Create``. Catch-up after a missed wake depends on Task
    Scheduler defaults for CLI-created tasks; set ``StartWhenAvailable`` via an
    exported/imported XML task definition if missed-run catch-up is required.

    Args:
        exe_path (str | Path): Absolute path to ``review-prep-worker`` executable.
        hour (int): Local hour (0-23) for the daily trigger.
        minute (int): Local minute (0-59) for the daily trigger.

    Raises:
        (subprocess.CalledProcessError) If ``schtasks`` exits non-zero.
        (ValueError) If hour/minute are out of range.
    """
    if not 0 <= hour <= 23:
        raise ValueError(f"hour must be 0-23, got {hour}")
    if not 0 <= minute <= 59:
        raise ValueError(f"minute must be 0-59, got {minute}")

    exe = Path(exe_path)
    start = f"{hour:02d}:{minute:02d}"
    user = getpass.getuser()
    cmd = ["schtasks", "/Create", "/F", "/TN", DAILY_TASK_NAME, "/SC", "DAILY", "/ST", start, "/RL", "LIMITED", "/TR", f'"{exe}"', "/RU", user]
    _logger.info("Registering daily task %s at %s for %s", DAILY_TASK_NAME, start, user)
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def register_logon_trigger(dashboard_exe: str | Path) -> None:
    """Register an on-logon task that opens the review prep dashboard.

    Args:
        dashboard_exe (str | Path): Absolute path to the dashboard executable.

    Raises:
        (subprocess.CalledProcessError) If ``schtasks`` exits non-zero.
    """
    exe = Path(dashboard_exe)
    user = getpass.getuser()
    cmd = ["schtasks", "/Create", "/F", "/TN", LOGON_TASK_NAME, "/SC", "ONLOGON", "/RL", "LIMITED", "/TR", f'"{exe}"', "/RU", user]
    _logger.info("Registering logon task %s for %s", LOGON_TASK_NAME, user)
    subprocess.run(cmd, check=True, capture_output=True, text=True)
