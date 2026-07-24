"""Smoke: print ShotGrid worklist card ids (requires Credential Manager key).

Fails gracefully when the script API key is missing or the query filters are still a stub.
Does not invent production layout_3 filters — fill configs/default_shotgrid_query.json after a live session.
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Load settings/credentials/query and print worklist card ids.

    Returns:
        (int) Process exit code (0 on success or graceful skip).
    """
    # Ensure src is importable when run as a loose script.
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from review_prep.settings import AppSettings, load_settings
    from review_prep.credentials import get_shotgrid_api_key
    from review_prep.shotgun_adapter import ShotGridAdapter, load_shotgrid_query

    settings_path = ROOT / "configs" / "settings.json"
    if settings_path.is_file():
        settings = load_settings(settings_path)
    else:
        settings = AppSettings.defaults()
        print(f"No {settings_path.name}; using AppSettings.defaults()")

    api_key = get_shotgrid_api_key()
    if not api_key:
        print("No ShotGrid API key in Credential Manager (service=review-prep, user=shotgrid-script). Skipping.")
        return 0

    if not settings.shotgrid_script_name:
        print("settings.shotgrid_script_name is empty. Skipping.")
        return 0

    query_path = Path(settings.shotgrid_query_path)
    if not query_path.is_absolute():
        query_path = ROOT / query_path
    if not query_path.is_file():
        print(f"Query file not found: {query_path}. Skipping.")
        return 0

    query = load_shotgrid_query(query_path)
    site_url = str(query.get("site_url") or "https://respawn.shotgunstudio.com")
    filters = query.get("filters") or []
    if not filters:
        print("Query filters are still empty (layout_3 human checkpoint pending). Will still call find(); expect empty or broad results.")

    try:
        adapter = ShotGridAdapter.connect(site_url=site_url, script_name=settings.shotgrid_script_name, api_key=api_key, query=query)
        cards = adapter.find_worklist()
    except Exception as exc:
        print(f"ShotGrid worklist failed: {exc}")
        return 1

    print(f"Worklist count: {len(cards)}")
    for card in cards:
        print(f"{card.id}\t{card.code}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
