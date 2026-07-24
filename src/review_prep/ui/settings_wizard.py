"""First-run / settings wizard for credentials and local paths."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
import logging
from pathlib import Path

from PySide6.QtWidgets import QLabel, QDialog, QLineEdit, QFormLayout, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QDialogButtonBox

from review_prep.settings import AppSettings, load_settings, save_settings
from review_prep.credentials import get_shotgrid_api_key, set_shotgrid_api_key
from review_prep.worker_main import resolve_shotgrid_query_path
from review_prep.shotgun_adapter import ShotGridAdapter, load_shotgrid_query


if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


_logger = logging.getLogger(__name__)

_DEFAULT_MAYA_TEMPLATE = '{cadet_cmd} --toolset apex_r5dev --app Maya --file "{file}"'


def needs_first_run_setup(settings_file: Path) -> bool:
    """Return True when settings or ShotGrid credentials are incomplete.

    Args:
        settings_file (Path): Path to ``settings.json``.

    Returns:
        (bool) True if the setup wizard should run before the dashboard.
    """
    if not settings_file.is_file():
        return True
    try:
        settings = load_settings(settings_file)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return True
    if not settings.staging_root.strip():
        return True
    if not settings.p4_client.strip():
        return True
    if not settings.shotgrid_script_name.strip():
        return True
    return not get_shotgrid_api_key()


def _resolve_query_path(settings: AppSettings, app_data: Path) -> Path:
    """Resolve ShotGrid query path; prefer app data (LOCALAPPDATA)."""
    return resolve_shotgrid_query_path(settings.shotgrid_query_path, app_data=app_data)


def run_test_query(settings: AppSettings, *, app_data: Path, api_key: str | None = None) -> tuple[bool, str]:
    """Execute the configured ShotGrid worklist query as a connectivity check.

    Args:
        settings (AppSettings): Current (possibly unsaved) settings values.
        app_data (Path): Application data directory for relative query paths.
        api_key (str | None): Optional key override (e.g. typed in the wizard).
            When omitted, uses the key stored in Credential Manager.

    Returns:
        (tuple[bool, str]) Success flag and a short result message.
    """
    resolved_key = (api_key or "").strip() or get_shotgrid_api_key()
    if not resolved_key:
        return False, "ShotGrid API key is not stored in Credential Manager yet."
    if not settings.shotgrid_script_name.strip():
        return False, "ShotGrid script name is empty."

    query_path = _resolve_query_path(settings, app_data)
    if not query_path.is_file():
        return False, f"ShotGrid query file not found: {query_path}"

    try:
        query = load_shotgrid_query(query_path)
        site_url = str(query.get("site_url") or "").strip()
        if not site_url:
            return False, f"site_url missing from ShotGrid query config: {query_path}"
        adapter = ShotGridAdapter.from_query_file(
            site_url=site_url,
            script_name=settings.shotgrid_script_name.strip(),
            api_key=resolved_key,
            query_path=query_path,
        )
        cards = adapter.find_worklist()
    except Exception as exc:
        _logger.exception("Test query failed: %s", exc)
        return False, f"Test query failed: {exc}"

    sample = ", ".join(f"{c.code}({c.id})" for c in cards[:5])
    extra = "" if len(cards) <= 5 else f", … (+{len(cards) - 5} more)"
    return True, f"OK — {len(cards)} card(s): {sample}{extra}" if cards else "OK — 0 cards returned."


class SettingsWizard(QDialog):
    """Collect first-run settings: script key, staging, P4, Cadet, 7z."""

    def __init__(self, settings_file: Path, *, app_data: Path, parent: QWidget | None = None) -> None:
        """Build the settings form.

        Args:
            settings_file (Path): Destination ``settings.json`` path.
            app_data (Path): ``%LOCALAPPDATA%/ReviewPrep`` (or equivalent).
            parent (QWidget | None): Optional Qt parent.
        """
        super().__init__(parent)
        self._settings_file = Path(settings_file)
        self._app_data = Path(app_data)

        self.setWindowTitle("Review Prep — Setup")
        self.resize(560, 360)

        if self._settings_file.is_file():
            try:
                current = load_settings(self._settings_file)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                current = AppSettings.defaults()
        else:
            current = AppSettings.defaults()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Configure ShotGrid credentials and local paths."))

        form = QFormLayout()
        self._script_name = QLineEdit(current.shotgrid_script_name)
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        if get_shotgrid_api_key():
            self._api_key.setPlaceholderText("(key already stored — leave blank to keep)")
        else:
            self._api_key.setPlaceholderText("ShotGrid script API key")

        self._staging = QLineEdit(current.staging_root)
        self._p4_client = QLineEdit(current.p4_client)
        self._seven_zip = QLineEdit(current.seven_zip_exe or "7z")
        self._query_path = QLineEdit(current.shotgrid_query_path)

        maya_template = current.cadet_launch_templates.get(".ma") or current.cadet_launch_templates.get("ma") or _DEFAULT_MAYA_TEMPLATE
        self._cadet_template = QLineEdit(maya_template)

        form.addRow("ShotGrid script name", self._script_name)
        form.addRow("ShotGrid API key", self._api_key)
        form.addRow("Staging root", self._staging)
        form.addRow("P4 client", self._p4_client)
        form.addRow("7z path", self._seven_zip)
        form.addRow("Cadet Maya template", self._cadet_template)
        form.addRow("ShotGrid query path", self._query_path)
        layout.addLayout(form)

        test_row = QHBoxLayout()
        self._test_btn = QPushButton("Run test query")
        self._test_btn.clicked.connect(self._on_test_query)
        self._test_status = QLabel("")
        self._test_status.setWordWrap(True)
        test_row.addWidget(self._test_btn)
        test_row.addWidget(self._test_status, stretch=1)
        layout.addLayout(test_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_settings(self) -> AppSettings:
        """Assemble AppSettings from form fields (does not write disk/keyring)."""
        if self._settings_file.is_file():
            try:
                base = load_settings(self._settings_file)
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                base = AppSettings.defaults()
        else:
            base = AppSettings.defaults()

        templates = dict(base.cadet_launch_templates)
        template = self._cadet_template.text().strip() or _DEFAULT_MAYA_TEMPLATE
        templates[".ma"] = template
        templates[".mb"] = template

        return AppSettings(
            staging_root=self._staging.text().strip(),
            retention_days=base.retention_days,
            schedule_hour=base.schedule_hour,
            schedule_minute=base.schedule_minute,
            p4_client=self._p4_client.text().strip(),
            p4_exe=base.p4_exe,
            seven_zip_exe=self._seven_zip.text().strip() or "7z",
            cadet_launch_templates=templates,
            cl_policies=base.cl_policies,
            include_patterns=base.include_patterns,
            exclude_patterns=base.exclude_patterns,
            launch_concurrency=base.launch_concurrency,
            shotgrid_script_name=self._script_name.text().strip(),
            shotgrid_query_path=self._query_path.text().strip() or base.shotgrid_query_path,
        )

    def _on_test_query(self) -> None:
        """Run the ShotGrid worklist query using the typed key without persisting it."""
        settings = self._build_settings()
        typed_key = self._api_key.text().strip() or None
        ok, message = run_test_query(settings, app_data=self._app_data, api_key=typed_key)
        self._test_status.setText(message)
        if not ok:
            QMessageBox.warning(self, "Test query", message)

    def _on_save(self) -> None:
        """Validate, store API key in keyring, write settings.json, accept."""
        settings = self._build_settings()
        if not settings.shotgrid_script_name:
            QMessageBox.warning(self, "Setup", "ShotGrid script name is required.")
            return
        if not settings.staging_root:
            QMessageBox.warning(self, "Setup", "Staging root is required.")
            return
        if not settings.p4_client:
            QMessageBox.warning(self, "Setup", "P4 client is required.")
            return

        typed_key = self._api_key.text().strip()
        if typed_key:
            set_shotgrid_api_key(typed_key)
        elif not get_shotgrid_api_key():
            QMessageBox.warning(self, "Setup", "ShotGrid API key is required.")
            return

        try:
            save_settings(self._settings_file, settings)
        except OSError as exc:
            QMessageBox.critical(self, "Setup", f"Failed to save settings: {exc}")
            return
        self.accept()
