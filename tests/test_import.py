"""Smoke test: verify the package imports cleanly."""

import red_team_prop_threader


def test_package_importable() -> None:
    """Package should import and expose its __name__."""
    assert red_team_prop_threader.__name__ == "red_team_prop_threader"
