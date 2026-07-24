"""PyInstaller entry for the console worker executable."""

from __future__ import annotations

import sys

from review_prep.worker_main import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
