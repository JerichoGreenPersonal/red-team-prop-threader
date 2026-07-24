from __future__ import annotations

from typing import Literal
import fnmatch
from pathlib import Path


_RECOGNIZED_DCC_EXTENSIONS = frozenset({".ma", ".mb", ".ztl", ".spp"})
_ARCHIVE_KINDS: dict[str, Literal["rar", "zip"]] = {".rar": "rar", ".zip": "zip"}


def is_recognized_dcc(path: Path) -> bool:
    return path.suffix.lower() in _RECOGNIZED_DCC_EXTENSIONS


def _matches_any(name: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in globs)


def filter_launchable(
    paths: list[Path],
    include_globs: list[str],
    exclude_globs: list[str],
) -> list[Path]:
    result: list[Path] = []
    for path in paths:
        name = path.name
        if include_globs and not _matches_any(name, include_globs):
            continue
        if exclude_globs and _matches_any(name, exclude_globs):
            continue
        result.append(path)
    return result


def archive_kind(path: Path) -> Literal["rar", "zip"] | None:
    return _ARCHIVE_KINDS.get(path.suffix.lower())
