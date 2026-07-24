"""User settings load/save for daily review prep."""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import asdict, dataclass

from review_prep.models import DEFAULT_CL_POLICIES, ClPolicy


def _default_cl_policies() -> dict[str, str]:
    """Build default CL label → policy string map, including Unknown."""
    policies = {label: policy.value for label, policy in DEFAULT_CL_POLICIES.items()}
    policies.setdefault("Unknown", ClPolicy.SYNC_ONLY.value)
    return policies


@dataclass
class AppSettings:
    """Persisted per-user configuration for the review prep assistant.

    Attributes:
        staging_root (str): Local or UNC root for daily staging folders.
        retention_days (int | None): Days to keep staging dirs; None keeps forever.
        schedule_hour (int): Local hour for scheduled prep (0-23).
        schedule_minute (int): Local minute for scheduled prep (0-59).
        p4_client (str): Everyday Perforce client name.
        p4_exe (str): Path or name of the ``p4`` executable.
        seven_zip_exe (str): Path or name of the ``7z`` executable.
        cadet_launch_templates (dict[str, str]): Extension → Cadet launch command template.
        cl_policies (dict[str, str]): CL label → policy value (ignore/sync_only/sync_and_open).
        include_patterns (list[str]): Glob patterns for launchable files.
        exclude_patterns (list[str]): Glob patterns to exclude from launch.
        launch_concurrency (int | None): Max concurrent launches; None is uncapped.
        shotgrid_script_name (str): ShotGrid script user name (key lives in keyring).
        shotgrid_query_path (str): Path to the ShotGrid query JSON config.
    """

    staging_root: str
    retention_days: int | None
    schedule_hour: int
    schedule_minute: int
    p4_client: str
    p4_exe: str
    seven_zip_exe: str
    cadet_launch_templates: dict[str, str]
    cl_policies: dict[str, str]
    include_patterns: list[str]
    exclude_patterns: list[str]
    launch_concurrency: int | None
    shotgrid_script_name: str
    shotgrid_query_path: str

    @classmethod
    def defaults(cls) -> AppSettings:
        """Return shipped default settings.

        Returns:
            (AppSettings) Defaults with 5:00 AM schedule and forever retention.
        """
        return cls(
            staging_root="",
            retention_days=None,
            schedule_hour=5,
            schedule_minute=0,
            p4_client="",
            p4_exe="p4",
            seven_zip_exe="7z",
            cadet_launch_templates={},
            cl_policies=_default_cl_policies(),
            include_patterns=[],
            exclude_patterns=[],
            launch_concurrency=None,
            shotgrid_script_name="",
            shotgrid_query_path="configs/default_shotgrid_query.json",
        )


def save_settings(path: Path, settings: AppSettings) -> None:
    """Write settings to a JSON file.

    Args:
        path (Path): Destination settings file path.
        settings (AppSettings): Settings instance to serialize.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")


def load_settings(path: Path) -> AppSettings:
    """Load settings from a JSON file.

    Args:
        path (Path): Settings file path.

    Returns:
        (AppSettings) Deserialized settings.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return AppSettings(**data)
