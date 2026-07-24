"""Fake Perforce command runner for unit tests."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class FakeP4:
    """Injects ``p4`` command results for :class:`~review_prep.p4_adapter.P4Adapter`.

    Attributes:
        synced (list[str]): Depot specs passed to non-dry-run ``sync`` calls.
    """

    def __init__(
        self,
        *,
        describe: Mapping[int, Sequence[str]] | None = None,
        opened: set[str] | frozenset[str] | None = None,
        map: Mapping[str, str] | None = None,  # noqa: A002 — brief API uses map=
        writable: set[str] | frozenset[str] | None = None,
    ) -> None:
        """Configure injected describe/opened/where/writable responses.

        Args:
            describe (Mapping[int, Sequence[str]] | None): CL → depot paths.
            opened (set[str] | frozenset[str] | None): Depot paths open on the client.
            map (Mapping[str, str] | None): Depot → local path for ``where``.
            writable (set[str] | frozenset[str] | None): Depot paths with writable conflicts.
        """
        self._describe = {int(cl): list(files) for cl, files in (describe or {}).items()}
        self._opened = set(opened or ())
        self._map = dict(map or {})
        self._writable = set(writable or ())
        self.synced: list[str] = []

    def run(self, args: Sequence[str]) -> str:
        """Interpret a ``p4 -c CLIENT ...`` argv and return synthetic stdout.

        Args:
            args (Sequence[str]): Full argv including executable.

        Returns:
            (str) Synthetic command stdout.

        Raises:
            (ValueError) If the command is unsupported or data is missing.
        """
        tokens = _strip_p4_prefix(list(args))
        if not tokens:
            raise ValueError("empty p4 command")

        cmd = tokens[0]
        rest = tokens[1:]

        if cmd == "describe":
            return self._cmd_describe(rest)
        if cmd == "where":
            return self._cmd_where(rest)
        if cmd == "opened":
            return self._cmd_opened(rest)
        if cmd == "sync":
            return self._cmd_sync(rest)
        raise ValueError(f"unsupported fake p4 command: {cmd}")

    def _cmd_describe(self, rest: list[str]) -> str:
        # describe -s CL
        cl_token = rest[-1]
        cl = int(cl_token)
        files = self._describe.get(cl)
        if files is None:
            raise ValueError(f"no describe data for CL {cl}")
        lines = [f"Change {cl} by user@client on 2026/01/01 00:00:00", "", "\tdescription", "", "Affected files ...", ""]
        for depot in files:
            lines.append(f"... {depot}#1 edit")
        return "\n".join(lines) + "\n"

    def _cmd_where(self, rest: list[str]) -> str:
        depot = rest[0]
        local = self._map.get(depot)
        if local is None:
            raise ValueError(f"no where mapping for {depot}")
        client_path = f"//client/{depot.lstrip('/')}"
        return f"{depot} {client_path} {local}\n"

    def _cmd_opened(self, rest: list[str]) -> str:
        depot = rest[0] if rest else ""
        if depot in self._opened:
            return f"{depot}#1 - edit default change (text)\n"
        return ""

    def _cmd_sync(self, rest: list[str]) -> str:
        dry_run = "-n" in rest
        specs = [t for t in rest if not t.startswith("-")]
        if not specs:
            raise ValueError("sync requires a file spec")
        spec = specs[0]
        depot = spec.split("@", 1)[0].split("#", 1)[0]
        local = self._map.get(depot, depot)

        if dry_run:
            if depot in self._writable:
                return f"{local} - can't clobber writable file {local}\n"
            return f"{spec} - updating\n"

        if depot in self._opened:
            raise ValueError(f"refusing sync of open file {depot}")
        if depot in self._writable:
            raise ValueError(f"refusing sync of writable conflict {depot}")
        self.synced.append(spec)
        return f"{spec} - refreshed\n"


def _strip_p4_prefix(args: list[str]) -> list[str]:
    """Drop executable and ``-c CLIENT`` from argv."""
    tokens = list(args)
    if tokens:
        tokens = tokens[1:]
    if len(tokens) >= 2 and tokens[0] == "-c":
        tokens = tokens[2:]
    return tokens
