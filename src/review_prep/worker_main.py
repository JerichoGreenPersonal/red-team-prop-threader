"""CLI entrypoint for scheduled (and manual) daily review prep runs."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING
import logging
from pathlib import Path
from datetime import date

from review_prep.state import StateRepo
from review_prep.settings import load_settings
from review_prep.retention import cleanup_staging
from review_prep.p4_adapter import P4Adapter
from review_prep.credentials import get_shotgrid_api_key
from review_prep.orchestrator import PrepOrchestrator
from review_prep.shotgun_adapter import ShotGridAdapter, load_shotgrid_query


if TYPE_CHECKING:
    from review_prep.settings import AppSettings
    from review_prep.orchestrator import PrepRunResult


_logger = logging.getLogger(__name__)


def app_data_dir() -> Path:
    """Return ``%LOCALAPPDATA%/ReviewPrep`` (or a pathlib home fallback).

    Returns:
        (Path) Per-user application data directory.
    """
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "ReviewPrep"


def db_path() -> Path:
    """Return the SQLite database path under the app data directory.

    Returns:
        (Path) ``.../ReviewPrep/prep.db``.
    """
    return app_data_dir() / "prep.db"


def settings_path() -> Path:
    """Return the settings JSON path under the app data directory.

    Returns:
        (Path) ``.../ReviewPrep/settings.json``.
    """
    return app_data_dir() / "settings.json"


def resolve_shotgrid_query_path(configured: str | Path, *, app_data: Path | None = None) -> Path:
    """Resolve ShotGrid query JSON path; prefer ``%LOCALAPPDATA%/ReviewPrep``.

    Absolute configured paths are used as-is. Relative paths search in order:
    1. Under ``app_data`` (default: ``%LOCALAPPDATA%/ReviewPrep``)
    2. Next to the frozen executable (packaged install)
    3. PyInstaller ``_MEIPASS`` bundle
    4. Current working directory

    Args:
        configured (str | Path): Path from settings (often ``configs/default_shotgrid_query.json``).
        app_data (Path | None): App data root override; defaults to :func:`app_data_dir`.

    Returns:
        (Path) First existing candidate, or the preferred LOCALAPPDATA path for errors.
    """
    query_path = Path(configured)
    if query_path.is_absolute():
        return query_path

    base = Path(app_data) if app_data is not None else app_data_dir()
    preferred = base / query_path
    candidates: list[Path] = [preferred]

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / query_path)

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / query_path)

    candidates.append(Path.cwd() / query_path)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return preferred


def _resolve_query_path(settings: AppSettings) -> Path:
    """Resolve ShotGrid query path from settings (LOCALAPPDATA preferred)."""
    return resolve_shotgrid_query_path(settings.shotgrid_query_path)


def wire_adapters(settings: AppSettings) -> tuple[ShotGridAdapter, P4Adapter]:
    """Build ShotGrid and P4 adapters from settings and Credential Manager.

    Args:
        settings (AppSettings): Loaded user settings.

    Returns:
        (tuple[ShotGridAdapter, P4Adapter]) Connected adapters.

    Raises:
        (RuntimeError) When credentials or required settings are missing.
        (FileNotFoundError) When the ShotGrid query file is missing.
    """
    api_key = get_shotgrid_api_key()
    if not api_key:
        raise RuntimeError("ShotGrid API key not found in Credential Manager (service=review-prep)")
    if not settings.shotgrid_script_name:
        raise RuntimeError("settings.shotgrid_script_name is empty")
    if not settings.p4_client:
        raise RuntimeError("settings.p4_client is empty")

    query_path = _resolve_query_path(settings)
    if not query_path.is_file():
        raise FileNotFoundError(f"ShotGrid query file not found: {query_path}")

    query = load_shotgrid_query(query_path)
    site_url = str(query.get("site_url") or "").strip()
    if not site_url:
        raise RuntimeError(f"site_url missing from ShotGrid query config: {query_path}")

    shotgun = ShotGridAdapter.from_query_file(site_url=site_url, script_name=settings.shotgrid_script_name, api_key=api_key, query_path=query_path)
    p4 = P4Adapter(client=settings.p4_client, p4_exe=settings.p4_exe)
    return shotgun, p4


def main(argv: list[str] | None = None) -> int:
    """Load settings, run prep orchestrator, optional retention; return exit code.

    Args:
        argv (list[str] | None): Optional CLI args. ``-h`` / ``--help`` print usage and exit 0.

    Returns:
        (int) ``0`` on success (including partial route errors); ``1`` on hard failure
        or configuration/startup errors.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"-h", "--help"}:
        print("usage: review-prep-worker [-h]")
        print("Run the scheduled daily review prep pipeline (non-interactive).")
        return 0

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    path = settings_path()
    if not path.is_file():
        _logger.error("Settings not found at %s", path)
        return 1

    try:
        settings = load_settings(path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        _logger.error("Failed to load settings from %s: %s", path, exc)
        return 1

    repo = StateRepo(db_path())
    repo.ensure_schema()

    try:
        shotgun, p4 = wire_adapters(settings)
    except (RuntimeError, FileNotFoundError, OSError) as exc:
        _logger.error("Failed to wire adapters: %s", exc)
        return 1

    try:
        orchestrator = PrepOrchestrator(settings=settings, state=repo, shotgun=shotgun, p4=p4, trigger="scheduled")
        result: PrepRunResult = orchestrator.run_worklist()
    except Exception as exc:
        _logger.exception("Worker prep run failed: %s", exc)
        return 1

    _logger.info(
        "prep run id=%s date=%s cards=%s hard_failure=%s errors=%s launchables=%s",
        result.prep_run_id,
        result.local_date,
        len(result.card_ids),
        result.hard_failure,
        len(result.errors),
        len(result.launchable_files),
    )
    for err in result.errors:
        _logger.warning("prep error: %s", err)

    if settings.staging_root:
        deleted = cleanup_staging(Path(settings.staging_root), date.today(), settings.retention_days)
        if deleted:
            _logger.info("retention deleted %s day folder(s)", len(deleted))

    return 1 if result.hard_failure else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
