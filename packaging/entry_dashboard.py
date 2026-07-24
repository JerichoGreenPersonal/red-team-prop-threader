"""PyInstaller entry for the windowed dashboard executable."""

from __future__ import annotations

import sys

from review_prep.app_main import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
