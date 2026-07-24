"""Prep-run summary dialog; closing acknowledges the run."""

from __future__ import annotations

from typing import TYPE_CHECKING
from datetime import date

from PySide6.QtWidgets import QLabel, QDialog, QVBoxLayout, QPlainTextEdit, QDialogButtonBox

from review_prep.models import RouteState


if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from review_prep.state import StateRepo


def acknowledge_summary_close(repo: StateRepo, prep_run_id: int) -> None:
    """Persist summary acknowledgment for a prep run (accept or close).

    Args:
        repo (StateRepo): SQLite state repository.
        prep_run_id (int): Prep run id shown in the summary dialog.
    """
    repo.ack_summary(prep_run_id)


def format_summary_text(repo: StateRepo, prep_run_id: int, local_date: str | None = None) -> str:
    """Build a plain-text summary of routes for a prep run.

    Args:
        repo (StateRepo): SQLite state repository.
        prep_run_id (int): Prep run id to summarize.
        local_date (str | None): Local date (YYYY-MM-DD); defaults to the run's
            stored date, then today.

    Returns:
        (str) Human-readable summary lines.
    """
    day = local_date
    if day is None:
        day = repo.get_prep_run_local_date(prep_run_id)
    if day is None:
        day = date.today().isoformat()
    routes: list[dict[str, object]] = []
    for route in repo.list_routes_for_date(day):
        run_raw = route.get("prep_run_id")
        if (isinstance(run_raw, int) and run_raw == prep_run_id) or (isinstance(run_raw, str) and int(run_raw) == prep_run_id):
            routes.append(route)
    lines = [f"Prep run {prep_run_id} ({day})", ""]
    if not routes:
        lines.append(f"No route rows recorded for this run on {day}.")
        lines.append("Close this dialog to acknowledge.")
        return "\n".join(lines)

    by_state: dict[str, list[dict[str, object]]] = {}
    for route in routes:
        state = str(route.get("state") or RouteState.NOT_PREPARED.value)
        by_state.setdefault(state, []).append(route)

    for state in sorted(by_state):
        lines.append(f"{state}: {len(by_state[state])}")
    lines.append("")
    for route in routes:
        lines.append(f"  card {route.get('card_sg_id')}  {route.get('route_kind')}/{route.get('route_key')}  {route.get('state')}  {route.get('detail')}")
    lines.append("")
    lines.append("Close this dialog to acknowledge.")
    return "\n".join(lines)


class SummaryDialog(QDialog):
    """Modal summary of an unacked prep run; any close acks the run."""

    def __init__(
        self,
        repo: StateRepo,
        prep_run_id: int,
        parent: QWidget | None = None,
        *,
        local_date: str | None = None,
    ) -> None:
        """Build the summary dialog for ``prep_run_id``.

        Args:
            repo (StateRepo): State repository used for routes and ack.
            prep_run_id (int): Unacked prep run to display.
            parent (QWidget | None): Optional Qt parent.
            local_date (str | None): Prep run local date; looked up from repo when omitted.
        """
        super().__init__(parent)
        self._repo = repo
        self._prep_run_id = prep_run_id
        self._acked = False
        day = local_date if local_date is not None else repo.get_prep_run_local_date(prep_run_id)

        self.setWindowTitle(f"Prep summary — run {prep_run_id}")
        self.resize(640, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Unacknowledged prep result (run {prep_run_id})"))

        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setPlainText(format_summary_text(repo, prep_run_id, local_date=day))
        layout.addWidget(body)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)
        layout.addWidget(buttons)

        self.finished.connect(self._on_finished)

    def _on_finished(self, _result: int) -> None:
        """Ack the prep run once when the dialog finishes for any reason."""
        if self._acked:
            return
        self._acked = True
        acknowledge_summary_close(self._repo, self._prep_run_id)
