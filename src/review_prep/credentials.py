"""Windows Credential Manager helpers for ShotGrid script API keys."""

from __future__ import annotations

import keyring


SERVICE = "review-prep"
USER = "shotgrid-script"


def set_shotgrid_api_key(api_key: str) -> None:
    """Store the ShotGrid script API key in the system keyring.

    Args:
        api_key (str): Script user API key to persist.
    """
    keyring.set_password(SERVICE, USER, api_key)


def get_shotgrid_api_key() -> str | None:
    """Return the ShotGrid script API key from the system keyring.

    Returns:
        (str | None) Stored API key, or None if unset.
    """
    return keyring.get_password(SERVICE, USER)
