"""Rewrite posted people labels (Requestor/Additional) to IC POC / Additional ICs / Additional stakeholders."""

from __future__ import annotations

import os
import sys
from pathlib import Path
import argparse

from red_team_prop_threader.config import Settings
from red_team_prop_threader.relabel import backfill_requestor_labels
from red_team_prop_threader.slack_gateway import SlackGateway


def main(argv: list[str] | None = None) -> int:
    """Load env, scan joined channels, and optionally apply in-place relabels.

    Args:
        argv: optional CLI arguments; defaults to sys.argv[1:].

    Returns:
        int: 0 on success, 1 when one or more channel or update errors occurred.
    """
    parser = argparse.ArgumentParser(description="Rewrite posted people labels to IC POC, Additional ICs, and Additional stakeholders.")
    parser.add_argument("--apply", action="store_true", help="chat.update matching messages. default is a dry-run.")
    parser.add_argument("--channel", action="append", default=[], metavar="ID", help="limit to a channel id. repeatable.")
    args = parser.parse_args(argv)

    _load_repo_env()
    slack = SlackGateway.from_settings(Settings.from_env())
    result = backfill_requestor_labels(slack, apply=args.apply, channel_ids=tuple(args.channel))
    mode = "apply" if args.apply else "dry-run"
    print(f"{mode}: scanned {result.scanned_channels} channel(s), {result.scanned_messages} message(s)")
    print(f"hits: {len(result.hits)}")
    for hit in result.hits:
        print(f"  {hit.channel_id} ts={hit.ts}")
    print(f"updated: {result.updated}")
    if result.errors:
        print("errors:")
        for item in result.errors:
            print(f"  {item}")
        return 1
    return 0


def _load_repo_env() -> None:
    """Load KEY=VALUE pairs from the repository-root .env into os.environ."""
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value


if __name__ == "__main__":
    sys.exit(main())
