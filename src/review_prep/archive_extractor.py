"""Safe archive extraction via 7-Zip with path and size limits."""

from __future__ import annotations

from pathlib import Path
import zipfile
import subprocess


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


def _collect_extracted(dest: Path, max_files: int, max_bytes: int) -> list[Path]:
    """Walk extract root, validate paths, and enforce limits."""
    dest_resolved = dest.resolve()
    extracted: list[Path] = []
    total_bytes = 0
    for path in sorted(dest_resolved.rglob("*")):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(dest_resolved)
        except ValueError as exc:
            raise UnsafeArchiveError(f"extracted path escapes destination: {path}") from exc
        extracted.append(path)
        total_bytes += path.stat().st_size
        if len(extracted) > max_files:
            raise UnsafeArchiveError(f"extracted file count exceeds max_files ({max_files})")
        if total_bytes > max_bytes:
            raise UnsafeArchiveError(f"extracted size exceeds max_bytes ({max_bytes})")
    return extracted


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

    completed = subprocess.run([str(seven_zip), "x", str(archive), f"-o{dest}", "-y"], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise UnsafeArchiveError(f"7z exited {completed.returncode}: {detail}")

    return _collect_extracted(dest, max_files, max_bytes)
