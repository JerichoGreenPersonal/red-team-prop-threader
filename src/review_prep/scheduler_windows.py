"""Windows Task Scheduler registration for daily prep and dashboard logon open."""

from __future__ import annotations

import getpass
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape


_logger = logging.getLogger(__name__)

DAILY_TASK_NAME = r"ReviewPrep\DailyPrep"
LOGON_TASK_NAME = r"ReviewPrep\OpenDashboard"


def _daily_task_xml(exe: Path, hour: int, minute: int, user: str) -> str:
    """Build Task Scheduler XML with daily trigger and StartWhenAvailable catch-up.

    Args:
        exe (Path): Absolute path to the worker executable.
        hour (int): Local hour (0-23) for the daily trigger.
        minute (int): Local minute (0-59) for the daily trigger.
        user (str): Windows account name for the task principal.

    Returns:
        (str) Task definition XML (UTF-16 will be applied when written).
    """
    start_boundary = f"2000-01-01T{hour:02d}:{minute:02d}:00"
    command = escape(str(exe))
    user_id = escape(user)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start_boundary}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user_id}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT72H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{command}</Command>
    </Exec>
  </Actions>
</Task>
"""


def register_daily_task(exe_path: str | Path, hour: int = 5, minute: int = 0) -> None:
    """Register a daily limited-rights task that runs the prep worker.

    Creates the task from Task Scheduler XML so ``StartWhenAvailable`` is true
    (catch-up after a missed scheduled time).

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
    xml_body = _daily_task_xml(exe, hour, minute, user)

    fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="review-prep-daily-")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as handle:
            handle.write(xml_body)
        cmd = ["schtasks", "/Create", "/TN", DAILY_TASK_NAME, "/XML", xml_path, "/F"]
        _logger.info("Registering daily task %s at %s for %s (StartWhenAvailable)", DAILY_TASK_NAME, start, user)
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    finally:
        try:
            os.unlink(xml_path)
        except OSError:
            _logger.debug("Could not remove temp task XML %s", xml_path, exc_info=True)


def register_logon_trigger(dashboard_exe: str | Path) -> None:
    """Register an on-logon task that opens the review prep dashboard.

    Args:
        dashboard_exe (str | Path): Absolute path to the dashboard executable.

    Raises:
        (subprocess.CalledProcessError) If ``schtasks`` exits non-zero.
    """
    exe = Path(dashboard_exe)
    user = getpass.getuser()
    # List-form argv: pass the absolute path unquoted (CreateProcess does not strip quotes).
    cmd = [
        "schtasks",
        "/Create",
        "/F",
        "/TN",
        LOGON_TASK_NAME,
        "/SC",
        "ONLOGON",
        "/RL",
        "LIMITED",
        "/TR",
        str(exe),
        "/RU",
        user,
    ]
    _logger.info("Registering logon task %s for %s", LOGON_TASK_NAME, user)
    subprocess.run(cmd, check=True, capture_output=True, text=True)
