"""Main dashboard window: card table, Prepare, Open Again, Settings."""

from __future__ import annotations

from typing import TYPE_CHECKING
import logging
from pathlib import Path
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QTableWidget, QTableWidgetItem

from review_prep.models import RouteState
from review_prep.settings import load_settings
from review_prep.worker_main import wire_adapters
from review_prep.launch_coordinator import LaunchCoordinator
from review_prep.ui.settings_wizard import SettingsWizard


if TYPE_CHECKING:
    from review_prep.state import StateRepo
    from review_prep.settings import AppSettings
    from review_prep.shotgun_adapter import Card


_logger = logging.getLogger(__name__)

_COL_ID = 0
_COL_CODE = 1
_COL_STATUS = 2


def aggregate_card_status(routes: list[dict[str, object]]) -> str:
    """Derive a single status string from a card's route rows.

    Args:
        routes (list[dict[str, object]]): Route rows for one card.

    Returns:
        (str) Worst/most informative status, or ``not_prepared`` when empty.
    """
    if not routes:
        return RouteState.NOT_PREPARED.value

    priority = [
        RouteState.FAILED.value,
        RouteState.PARTIAL.value,
        RouteState.READY_TO_LAUNCH.value,
        RouteState.LAUNCHED.value,
        RouteState.SYNCED_ONLY.value,
        RouteState.SKIPPED.value,
        RouteState.SYNCING.value,
        RouteState.EXTRACTING.value,
        RouteState.DOWNLOADING.value,
        RouteState.QUEUED.value,
        RouteState.NOT_PREPARED.value,
    ]
    states = {str(r.get("state") or "") for r in routes}
    for state in priority:
        if state in states:
            return state
    return sorted(states)[0] if states else RouteState.NOT_PREPARED.value


class MainWindow(QMainWindow):
    """Plain functional dashboard for the daily review prep queue."""

    def __init__(self, *, repo: StateRepo, settings_file: Path, app_data: Path, parent: QWidget | None = None) -> None:
        """Create the main window.

        Args:
            repo (StateRepo): SQLite manifest.
            settings_file (Path): Path to ``settings.json``.
            app_data (Path): Application data directory.
            parent (QWidget | None): Optional Qt parent.
        """
        super().__init__(parent)
        self._repo = repo
        self._settings_file = Path(settings_file)
        self._app_data = Path(app_data)
        self._cards: list[Card] = []

        self.setWindowTitle("Review Prep")
        self.resize(800, 480)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._status = QLabel("Ready")
        layout.addWidget(self._status)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Card ID", "Code", "Status"])
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._table)

        buttons = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._prepare_btn = QPushButton("Prepare")
        self._open_again_btn = QPushButton("Open Again")
        self._settings_btn = QPushButton("Settings")
        self._refresh_btn.clicked.connect(self.refresh_cards)
        self._prepare_btn.clicked.connect(self._on_prepare)
        self._open_again_btn.clicked.connect(self._on_open_again)
        self._settings_btn.clicked.connect(self._on_settings)
        buttons.addWidget(self._refresh_btn)
        buttons.addWidget(self._prepare_btn)
        buttons.addWidget(self._open_again_btn)
        buttons.addWidget(self._settings_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.refresh_cards()

    def _load_settings(self) -> AppSettings:
        """Load settings from disk.

        Returns:
            (AppSettings) Current settings.

        Raises:
            (OSError, ValueError, TypeError, KeyError): When load fails.
        """
        return load_settings(self._settings_file)

    def selected_card_ids(self) -> list[int]:
        """Return ShotGrid ids for selected table rows.

        Returns:
            (list[int]) Selected card entity ids (unique, row order).
        """
        ids: list[int] = []
        seen: set[int] = set()
        for index in self._table.selectionModel().selectedRows():
            item = self._table.item(index.row(), _COL_ID)
            if item is None:
                continue
            card_id = int(item.data(Qt.ItemDataRole.UserRole))
            if card_id in seen:
                continue
            seen.add(card_id)
            ids.append(card_id)
        return ids

    def refresh_cards(self) -> None:
        """Reload the card table from ShotGrid worklist (fallback: today's routes)."""
        self._cards = []
        error: str | None = None
        try:
            settings = self._load_settings()
            shotgun, _p4 = wire_adapters(settings)
            self._cards = shotgun.find_worklist()
        except Exception as exc:
            _logger.warning("Live worklist refresh failed: %s", exc)
            error = str(exc)
            self._cards = self._cards_from_routes()

        self._table.setRowCount(0)
        for card in self._cards:
            routes = self._repo.get_routes_for_card(card.id)
            status = aggregate_card_status(routes)
            row = self._table.rowCount()
            self._table.insertRow(row)
            id_item = QTableWidgetItem(str(card.id))
            id_item.setData(Qt.ItemDataRole.UserRole, card.id)
            self._table.setItem(row, _COL_ID, id_item)
            self._table.setItem(row, _COL_CODE, QTableWidgetItem(card.code))
            self._table.setItem(row, _COL_STATUS, QTableWidgetItem(status))

        if error:
            self._status.setText(f"Worklist offline ({error}); showing {len(self._cards)} card(s) from manifest.")
        else:
            self._status.setText(f"{len(self._cards)} card(s) from worklist.")

    def _cards_from_routes(self) -> list[Card]:
        """Build minimal Card stubs from today's route rows when ShotGrid is down."""
        from review_prep.shotgun_adapter import Card

        day = date.today().isoformat()
        routes = self._repo.list_routes_for_date(day)
        by_id: dict[int, Card] = {}
        for route in routes:
            card_raw = route.get("card_sg_id")
            if isinstance(card_raw, bool) or not isinstance(card_raw, int):
                continue
            card_id = card_raw
            if card_id not in by_id:
                by_id[card_id] = Card(id=card_id, code=f"card_{card_id}", thumbnail_url=None)
        return list(by_id.values())

    def _on_prepare(self) -> None:
        """Run manual Prepare for selected cards (same pipeline as scheduled)."""
        card_ids = self.selected_card_ids()
        if not card_ids:
            QMessageBox.information(self, "Prepare", "Select one or more cards first.")
            return
        try:
            settings = self._load_settings()
            shotgun, p4 = wire_adapters(settings)
            from review_prep.orchestrator import PrepOrchestrator

            orch = PrepOrchestrator(settings=settings, state=self._repo, shotgun=shotgun, p4=p4, trigger="manual")
            result = orch.prepare_cards(card_ids)
        except Exception as exc:
            _logger.exception("Prepare failed: %s", exc)
            QMessageBox.critical(self, "Prepare", f"Prepare failed: {exc}")
            return

        msg = f"Prep run {result.prep_run_id}: {len(result.card_ids)} card(s), {len(result.launchable_files)} launchable(s), {len(result.errors)} error(s)."
        if result.hard_failure:
            QMessageBox.warning(self, "Prepare", msg)
        else:
            QMessageBox.information(self, "Prepare", msg)

        # After a successful Prepare, attempt Cadet auto-launch for today.
        if not result.hard_failure and result.launchable_files:
            from review_prep.launch_coordinator import run_dashboard_auto_launch

            launch_report = run_dashboard_auto_launch(
                repo=self._repo,
                settings_file=self._settings_file,
                local_date=date.today(),
            )
            if launch_report is not None and launch_report.blocked_cadet:
                _logger.warning("Prepare finished but Cadet auto-launch blocked: %s", "; ".join(launch_report.messages))

        self.refresh_cards()

    def _on_open_again(self) -> None:
        """Re-open launchables for selected cards via Cadet (bypass leases)."""
        card_ids = self.selected_card_ids()
        if not card_ids:
            QMessageBox.information(self, "Open Again", "Select one or more cards first.")
            return
        try:
            settings = self._load_settings()
            coordinator = LaunchCoordinator(settings=settings, state=self._repo)
            report = coordinator.open_again(card_ids)
        except Exception as exc:
            _logger.exception("Open Again failed: %s", exc)
            QMessageBox.critical(self, "Open Again", f"Open Again failed: {exc}")
            return

        parts = [f"Launched {len(report.launched)} file(s)."]
        if report.blocked_cadet:
            parts.extend(report.messages or ["Cadet is not running."])
        if report.errors:
            parts.append("; ".join(report.errors[:5]))
        QMessageBox.information(self, "Open Again", "\n".join(parts))
        self.refresh_cards()

    def _on_settings(self) -> None:
        """Open the settings wizard and refresh after a successful save."""
        wizard = SettingsWizard(self._settings_file, app_data=self._app_data, parent=self)
        if wizard.exec():
            self.refresh_cards()
