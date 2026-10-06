"""tests for mapping Request Form people to Slack users."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from red_team_prop_threader.people import PeopleResolver, normalize_person_name
from red_team_prop_threader._errors import PermissionDeniedError
from red_team_prop_threader.cl_jobs import MintGroupPerson


USERS = (
    {"id": "U1", "real_name": "Jared Bosse", "profile": {"display_name": "jbosse"}},
    {"id": "U2", "real_name": "Ryan Lastimosa", "profile": {}},
    {"id": "U3", "real_name": "Ryan Lastimosa", "profile": {}},
    {"id": "U4", "real_name": "José Núñez", "profile": {}},
    {"id": "U5", "real_name": "Gone Person", "deleted": True, "profile": {}},
    {"id": "B1", "real_name": "Jared Bosse", "is_bot": True, "profile": {}},
)


def _slack(email_result: object = None, *, email_error: Exception | None = None) -> MagicMock:
    slack = MagicMock()
    slack.list_users.return_value = USERS
    if email_error is not None:
        slack.lookup_user_by_email.side_effect = email_error
    else:
        slack.lookup_user_by_email.return_value = email_result
    return slack


def test_normalize_person_name() -> None:
    """Accents, case, and spacing do not affect matching."""
    assert normalize_person_name("  José   NÚÑEZ ") == "jose nunez"


def test_name_match_unique_and_ambiguous() -> None:
    """Only a single non-deleted, non-bot user with that name is tagged."""
    slack = _slack(email_error=PermissionDeniedError("missing_scope"))
    resolver = PeopleResolver(slack, team_id="T0297NTAU")
    jared = resolver.resolve(MintGroupPerson("Jared Bosse", "jbosse@ea.com"))
    assert (jared.user_id, jared.method) == ("U1", "name")
    assert resolver.resolve(MintGroupPerson("Ryan Lastimosa", "rlastimosa@respawn.com")).user_id == ""
    assert resolver.resolve(MintGroupPerson("Jose Nunez", "jn@respawn.com")).user_id == "U4"
    assert resolver.resolve(MintGroupPerson("Gone Person", "g@respawn.com")).user_id == ""
    slack.list_users.assert_called_once_with(team_id="T0297NTAU")
    assert slack.lookup_user_by_email.call_count == 1


def test_email_lookup_wins_when_scope_present() -> None:
    """With users:read.email, the email lookup resolves even ambiguous names."""
    slack = _slack(email_result="U9")
    person = PeopleResolver(slack, team_id="T0297NTAU").resolve(MintGroupPerson("Ryan Lastimosa", "rlastimosa@respawn.com"))
    assert (person.user_id, person.method) == ("U9", "email")


def test_email_miss_falls_back_to_name() -> None:
    """An email with no Slack user falls back to the name match."""
    slack = _slack(email_result=None)
    person = PeopleResolver(slack, team_id="T0297NTAU").resolve(MintGroupPerson("Jared Bosse", "x@ea.com"))
    assert (person.user_id, person.method) == ("U1", "name")


def test_gateway_list_users_paginates() -> None:
    """users.list follows next_cursor and always passes team_id."""
    from red_team_prop_threader.slack_gateway import SlackGateway

    client = MagicMock()
    client.users_list.side_effect = [
        {"ok": True, "members": [{"id": "U1"}], "response_metadata": {"next_cursor": "c2"}},
        {"ok": True, "members": [{"id": "U2"}], "response_metadata": {"next_cursor": ""}},
    ]
    users = SlackGateway(client).list_users(team_id="T0297NTAU")
    assert [u["id"] for u in users] == ["U1", "U2"]
    assert client.users_list.call_args_list[1].kwargs == {"team_id": "T0297NTAU", "limit": 200, "cursor": "c2"}


def test_gateway_lookup_user_by_email() -> None:
    """users.lookupByEmail returns the id, or None when Slack has no such user."""
    from slack_sdk.errors import SlackApiError

    from red_team_prop_threader.slack_gateway import SlackGateway

    client = MagicMock()
    client.users_lookupByEmail.return_value = {"ok": True, "user": {"id": "U7"}}
    assert SlackGateway(client).lookup_user_by_email("a@respawn.com") == "U7"
    client.users_lookupByEmail.side_effect = SlackApiError("nope", {"ok": False, "error": "users_not_found"})
    assert SlackGateway(client).lookup_user_by_email("b@respawn.com") is None
    client.users_lookupByEmail.side_effect = SlackApiError("nope", {"ok": False, "error": "missing_scope"})
    with pytest.raises(PermissionDeniedError):
        SlackGateway(client).lookup_user_by_email("c@respawn.com")


@pytest.mark.parametrize(("value", "expected"), [("", "T0297NTAU"), ("T039ZEK3W", "T039ZEK3W")])
def test_settings_team_id(monkeypatch: pytest.MonkeyPatch, value: str, expected: str) -> None:
    """SLACK_PEOPLE_TEAM_ID defaults to the Respawn workspace."""
    from red_team_prop_threader.config import Settings

    for key in ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN", "SHOTGRID_SCRIPT_NAME", "SHOTGRID_SCRIPT_KEY"):
        monkeypatch.setenv(key, "x")
    monkeypatch.setenv("SLACK_PEOPLE_TEAM_ID", value)
    assert Settings.from_env().slack_people_team_id == expected
