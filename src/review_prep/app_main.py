"""Dashboard entrypoint: setup wizard, summary ack, main window."""

from __future__ import annotations

import sys
import logging

from PySide6.QtWidgets import QApplication

from review_prep.state import StateRepo
from review_prep.worker_main import db_path, app_data_dir, settings_path
from review_prep.ui.main_window import MainWindow
from review_prep.ui.summary_dialog import SummaryDialog
from review_prep.ui.settings_wizard import SettingsWizard, needs_first_run_setup


_logger = logging.getLogger(__name__)


def show_unacked_summary_if_needed(repo: StateRepo, parent: MainWindow | None = None) -> int | None:
    """Show SummaryDialog for the latest unacked run; close acks it.

    Args:
        repo (StateRepo): SQLite state repository.
        parent (MainWindow | None): Optional parent window.

    Returns:
        (int | None) Prep run id that was shown (and acked on close), or None.
    """
    run_id = repo.latest_unacked_run()
    if run_id is None:
        return None
    local_date = repo.get_prep_run_local_date(run_id)
    dialog = SummaryDialog(repo, run_id, parent=parent, local_date=local_date)
    dialog.exec()
    return run_id


def main(argv: list[str] | None = None) -> int:
    """Launch the Review Prep dashboard.

    Args:
        argv (list[str] | None): Unused CLI args (reserved).

    Returns:
        (int) Process exit code (``0`` on normal quit).
    """
    _ = argv
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    app = QApplication(sys.argv)
    app.setApplicationName("Review Prep")

    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    settings_file = settings_path()
    repo = StateRepo(db_path())
    repo.ensure_schema()

    if needs_first_run_setup(settings_file):
        wizard = SettingsWizard(settings_file, app_data=data_dir)
        if wizard.exec() != SettingsWizard.DialogCode.Accepted:
            _logger.info("Setup cancelled; exiting.")
            return 1
        if needs_first_run_setup(settings_file):
            _logger.error("Setup incomplete after wizard.")
            return 1

    window = MainWindow(repo=repo, settings_file=settings_file, app_data=data_dir)
    window.show()

    shown = show_unacked_summary_if_needed(repo, parent=window)
    if shown is not None:
        _logger.info("Acknowledged prep summary for run %s", shown)

    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
