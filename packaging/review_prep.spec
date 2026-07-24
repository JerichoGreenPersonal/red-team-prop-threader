# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: review-prep-worker.exe (console) + review-prep.exe (windowed)."""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# SPECPATH is the directory containing this .spec (PyInstaller convention).
SPECDIR = Path(SPECPATH).resolve()
ROOT = SPECDIR.parent
SRC = str(ROOT / "src")

block_cipher = None

# PySide6 (and plugins) for the dashboard; worker Analysis stays leaner without collect_all.
pyside_datas, pyside_binaries, pyside_hiddenimports = collect_all("PySide6")

_common_hidden = [
    "keyring.backends.Windows",
    "keyring.backends.null",
    "shotgun_api3",
    "review_prep",
    "review_prep.worker_main",
    "review_prep.app_main",
    "review_prep.scheduler_windows",
    "review_prep.ui.main_window",
    "review_prep.ui.settings_wizard",
    "review_prep.ui.summary_dialog",
]

# --- Worker (console, onefile) -------------------------------------------------
worker_a = Analysis(
    [str(SPECDIR / "entry_worker.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=_common_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PySide6.QtWidgets", "PySide6.QtCore", "PySide6.QtGui"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
worker_pyz = PYZ(worker_a.pure, worker_a.zipped_data, cipher=block_cipher)
worker_exe = EXE(
    worker_pyz,
    worker_a.scripts,
    worker_a.binaries,
    worker_a.zipfiles,
    worker_a.datas,
    [],
    name="review-prep-worker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# --- Dashboard (windowed, onefile) ---------------------------------------------
dash_a = Analysis(
    [str(SPECDIR / "entry_dashboard.py")],
    pathex=[SRC],
    binaries=pyside_binaries,
    datas=pyside_datas,
    hiddenimports=_common_hidden + list(pyside_hiddenimports),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
dash_pyz = PYZ(dash_a.pure, dash_a.zipped_data, cipher=block_cipher)
dash_exe = EXE(
    dash_pyz,
    dash_a.scripts,
    dash_a.binaries,
    dash_a.zipfiles,
    dash_a.datas,
    [],
    name="review-prep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
