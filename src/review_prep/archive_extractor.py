"""Safe archive extraction via 7-Zip with path and size limits."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


class UnsafeArchiveError(Exception):
    """Raised when an archive member path is unsafe, limits are exceeded, or 7z fails."""


def validate_member_path(member: Path, dest: Path) -> Path:
    """Ensure a member path stays under ``dest`` (no absolute paths or ``..``).

    Args:
        member (Path): Archive member path (relative).
        dest (Path): Intended extract root.

    Returns:
        (Path) Resolved path under ``dest``.

    Raises:
        (UnsafeArchiveError) If the member escapes ``dest``.
    """
    member = Path(member)
    dest = Path(dest)

    if member.is_absolute():
        raise UnsafeArchiveError(f"absolute member path rejected: {member}")

    if any(part == ".." for part in member.parts):
        raise UnsafeArchiveError(f"path traversal rejected: {member}")

    # Catch drive-like or rooted strings zip members may use (e.g. "/etc/passwd")
    as_posix = member.as_posix()
    if as_posix.startswith("/") or (len(as_posix) >= 2 and as_posix[1] == ":"):
        raise UnsafeArchiveError(f"absolute member path rejected: {member}")

    dest_resolved = dest.resolve()
    target = (dest_resolved / member).resolve()
    try:
        target.relative_to(dest_resolved)
    except ValueError as exc:
        raise UnsafeArchiveError(f"member escapes destination: {member}") from exc
    return target


def list_archive_entries(archive: Path) -> list[str]:
    """List zip members and reject unsafe paths.

    Uses ``zipfile`` so unit tests do not need a real 7-Zip install.

    Args:
        archive (Path): Path to a ``.zip`` archive.

    Returns:
        (list[str]) Safe member names (directories omitted).

    Raises:
        (UnsafeArchiveError) If any member path is absolute or traverses parents.
        (zipfile.BadZipFile) If the file is not a valid zip.
    """
    archive = Path(archive)
    # Synthetic dest for path validation only
    dest = Path.cwd()
    names: list[str] = []
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/") or info.is_dir():
                continue
            validate_member_path(Path(name), dest)
            names.append(name)
    return names


def _validate_zip_limits(archive: Path, dest: Path, max_files: int, max_bytes: int) -> None:
    """Pre-check zip member paths, file count, and uncompressed size."""
    with zipfile.ZipFile(archive, "r") as zf:
        files = [info for info in zf.infolist() if not (info.is_dir() or info.filename.endswith("/"))]
        if len(files) > max_files:
            raise UnsafeArchiveError(f"archive exceeds max_files ({len(files)} > {max_files})")
        total_bytes = sum(info.file_size for info in files)
        if total_bytes > max_bytes:
            raise UnsafeArchiveError(f"archive exceeds max_bytes ({total_bytes} > {max_bytes})")
        for info in files:
            validate_member_path(Path(info.filename), dest)


def _parse_7z_slt(stdout: str) -> list[tuple[str, int | None]]:
    """Parse ``7z l -slt`` output into ``(path, size)`` pairs for file members.

    Args:
        stdout (str): Technical listing output from ``7z l -slt``.

    Returns:
        (list[tuple[str, int | None]]) File member paths and sizes (``None`` if Size absent).
    """
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in stdout.splitlines():
        line = raw.strip()
        if line == "----------":
            if current:
                blocks.append(current)
                current = {}
            continue
        if " = " not in line:
            continue
        key, _, value = line.partition(" = ")
        current[key.strip()] = value.strip()
    if current:
        blocks.append(current)

    members: list[tuple[str, int | None]] = []
    for block in blocks:
        path = block.get("Path")
        if not path:
            continue
        # Archive container header has Type (zip/rar/7z/...); skip it.
        if "Type" in block and block.get("Folder") is None and "Size" not in block:
            continue
        if block.get("Folder", "-").startswith("+"):
            continue
        attrs = block.get("Attributes", "")
        if attrs.upper().startswith("D"):
            continue
        if path.endswith("/") or path.endswith("\\"):
            continue
        size_raw = block.get("Size")
        size: int | None
        if size_raw is None or size_raw == "":
            size = None
        else:
            try:
                size = int(size_raw)
            except ValueError:
                size = None
        members.append((path, size))
    return members


def _validate_7z_listing(archive: Path, dest: Path, seven_zip: Path, max_files: int, max_bytes: int) -> None:
    """Pre-check non-zip archives via ``7z l -slt`` before extract."""
    completed = subprocess.run(
        [str(seven_zip), "l", "-slt", str(archive)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise UnsafeArchiveError(f"7z list exited {completed.returncode}: {detail}")

    members = _parse_7z_slt(completed.stdout or "")
    if len(members) > max_files:
        raise UnsafeArchiveError(f"archive exceeds max_files ({len(members)} > {max_files})")

    total_bytes = sum(size for _, size in members if size is not None)
    if total_bytes > max_bytes:
        raise UnsafeArchiveError(f"archive exceeds max_bytes ({total_bytes} > {max_bytes})")

    for name, _ in members:
        validate_member_path(Path(name), dest)


def _collect_extracted(root: Path, dest: Path, max_files: int, max_bytes: int) -> list[Path]:
    """Walk extract root, validate paths relative to ``dest``, and enforce limits.

    Args:
        root (Path): Directory that was written by this extract (e.g. temp staging).
        dest (Path): Final destination root used for path-escape checks.
        max_files (int): Maximum number of extracted files.
        max_bytes (int): Maximum total uncompressed bytes.

    Returns:
        (list[Path]) Extracted file paths under ``root``.
    """
    root_resolved = root.resolve()
    dest_resolved = dest.resolve()
    extracted: list[Path] = []
    total_bytes = 0
    for path in sorted(root_resolved.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root_resolved)
        try:
            (dest_resolved / rel).resolve().relative_to(dest_resolved)
        except ValueError as exc:
            raise UnsafeArchiveError(f"extracted path escapes destination: {rel}") from exc
        extracted.append(path)
        total_bytes += path.stat().st_size
        if len(extracted) > max_files:
            raise UnsafeArchiveError(f"extracted file count exceeds max_files ({max_files})")
        if total_bytes > max_bytes:
            raise UnsafeArchiveError(f"extracted size exceeds max_bytes ({max_bytes})")
    return extracted


def _move_extracted(staged: list[Path], staging_root: Path, dest: Path) -> list[Path]:
    """Move staged files into ``dest``, preserving relative layout."""
    staging_resolved = staging_root.resolve()
    moved: list[Path] = []
    for path in staged:
        rel = path.relative_to(staging_resolved)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        moved.append(target)
    return moved


def extract_archive(archive: Path, dest: Path, seven_zip: Path, max_files: int, max_bytes: int) -> list[Path]:
    """Extract an archive with 7-Zip after path and size checks.

    Args:
        archive (Path): Archive file (``.zip`` / ``.rar``).
        dest (Path): Destination directory (created if missing).
        seven_zip (Path): Path to ``7z`` / ``7z.exe``.
        max_files (int): Maximum number of extracted files.
        max_bytes (int): Maximum total uncompressed bytes.

    Returns:
        (list[Path]) Paths of extracted files under ``dest``.

    Raises:
        (UnsafeArchiveError) On traversal, absolute paths, limit breach, or non-zero 7z exit.
    """
    archive = Path(archive)
    dest = Path(dest)
    seven_zip = Path(seven_zip)

    if not archive.is_file():
        raise UnsafeArchiveError(f"archive not found: {archive}")

    dest.mkdir(parents=True, exist_ok=True)

    if archive.suffix.lower() == ".zip":
        _validate_zip_limits(archive, dest, max_files, max_bytes)
    else:
        _validate_7z_listing(archive, dest, seven_zip, max_files, max_bytes)

    with tempfile.TemporaryDirectory(dir=dest, prefix=".extract-") as staging:
        staging_path = Path(staging)
        completed = subprocess.run(
            [str(seven_zip), "x", str(archive), f"-o{staging_path}", "-y"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise UnsafeArchiveError(f"7z exited {completed.returncode}: {detail}")

        staged = _collect_extracted(staging_path, dest, max_files, max_bytes)
        return _move_extracted(staged, staging_path, dest)
