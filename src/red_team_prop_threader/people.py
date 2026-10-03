"""map Request Form people (name + email) to Slack user ids."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol
import logging
from dataclasses import dataclass
import unicodedata

from red_team_prop_threader._errors import PermissionDeniedError


if TYPE_CHECKING:
    from red_team_prop_threader.cl_jobs import MintGroupPerson


__all__ = ("PeopleGateway", "PeopleResolver", "ResolvedPerson", "normalize_person_name")

_LOG = logging.getLogger(__name__)


class PeopleGateway(Protocol):
    """slack methods the resolver needs."""

    def list_users(self, *, team_id: str) -> tuple[dict[str, Any], ...]:
        """Return users.list for one workspace."""

    def lookup_user_by_email(self, email: str) -> str | None:
        """Return users.lookupByEmail's user id."""


@dataclass(frozen=True, slots=True)
class ResolvedPerson:
    """one sheet person and the Slack id it maps to ("" when not tagged)."""

    name: str
    email: str
    user_id: str
    method: str


def normalize_person_name(text: str) -> str:
    """Lowercase, strip accents, and collapse whitespace.

    Args:
        text: display or real name.

    Returns:
        str: comparison key.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.lower().split())


class PeopleResolver:
    """email lookup when the scope exists, else unique exact name match."""

    def __init__(self, slack: PeopleGateway, *, team_id: str) -> None:
        """Initialize with a gateway and the workspace id used for users.list.

        Args:
            slack: gateway exposing users.list and users.lookupByEmail.
            team_id: workspace id for users.list on Enterprise Grid.
        """
        self._slack = slack
        self._team_id = team_id
        self._email_enabled = True
        self._by_name: dict[str, set[str]] | None = None

    def _name_index(self) -> dict[str, set[str]]:
        if self._by_name is None:
            index: dict[str, set[str]] = {}
            for user in self._slack.list_users(team_id=self._team_id):
                if user.get("deleted") or user.get("is_bot"):
                    continue
                user_id = str(user.get("id") or "")
                profile = user.get("profile") if isinstance(user.get("profile"), dict) else {}
                names = {str(user.get("real_name") or ""), str(profile.get("real_name") or ""), str(profile.get("display_name") or "")}
                for name in names:
                    key = normalize_person_name(name)
                    if key and user_id:
                        index.setdefault(key, set()).add(user_id)
            self._by_name = index
        return self._by_name

    def resolve(self, person: MintGroupPerson) -> ResolvedPerson:
        """Return the Slack id for one person, or an untagged result.

        Args:
            person: sheet person chip.

        Returns:
            ResolvedPerson: user id and method, or empty id when not tagged.
        """
        if self._email_enabled and person.email:
            try:
                user_id = self._slack.lookup_user_by_email(person.email)
            except PermissionDeniedError:
                _LOG.info("users:read.email not granted; matching people by name")
                self._email_enabled = False
            else:
                if user_id:
                    return ResolvedPerson(person.name, person.email, user_id, "email")
        matches = self._name_index().get(normalize_person_name(person.name), set())
        if len(matches) == 1:
            return ResolvedPerson(person.name, person.email, next(iter(matches)), "name")
        return ResolvedPerson(person.name, person.email, "", "")
