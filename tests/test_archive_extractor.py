import shutil
from pathlib import Path
import zipfile
from unittest.mock import MagicMock

import pytest

from review_prep.archive_extractor import UnsafeArchiveError, extract_archive, list_archive_entries, validate_member_path


def _make_zip(path: Path, names: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in names.items():
            zf.writestr(name, data)


def test_rejects_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    _make_zip(archive, {"../../evil.txt": b"x"})
    with pytest.raises(UnsafeArchiveError):
        list_archive_entries(archive)  # pure zipfile path listing for unit test


def test_extract_ok_with_fake_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Unit-test the path validation helper independently of real 7z
    from review_prep import archive_extractor as ae

    ae.validate_member_path(Path("ok/file.ma"), Path(tmp_path / "out"))
    with pytest.raises(UnsafeArchiveError):
        ae.validate_member_path(Path("../x.ma"), Path(tmp_path / "out"))


def test_rejects_absolute_member(tmp_path: Path) -> None:
    with pytest.raises(UnsafeArchiveError):
        validate_member_path(Path("/etc/passwd"), tmp_path / "out")


def test_list_archive_entries_ok(tmp_path: Path) -> None:
    archive = tmp_path / "ok.zip"
    _make_zip(archive, {"ok/file.ma": b"maya", "readme.txt": b"hi"})
    names = list_archive_entries(archive)
    assert names == ["ok/file.ma", "readme.txt"]


def test_extract_rejects_too_many_files(tmp_path: Path) -> None:
    archive = tmp_path / "many.zip"
    _make_zip(archive, {"a.txt": b"1", "b.txt": b"2"})
    with pytest.raises(UnsafeArchiveError, match="max_files"):
        extract_archive(archive, tmp_path / "out", Path("7z"), max_files=1, max_bytes=10_000)


def test_extract_rejects_too_many_bytes(tmp_path: Path) -> None:
    archive = tmp_path / "big.zip"
    _make_zip(archive, {"a.txt": b"abcdefghij"})
    with pytest.raises(UnsafeArchiveError, match="max_bytes"):
        extract_archive(archive, tmp_path / "out", Path("7z"), max_files=10, max_bytes=5)


def test_extract_with_mocked_7z(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "ok.zip"
    dest = tmp_path / "out"
    _make_zip(archive, {"ok/file.ma": b"maya"})

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        assert cmd[1] == "x"
        assert any(str(a).startswith("-o") for a in cmd)
        out_arg = next(str(a) for a in cmd if str(a).startswith("-o"))
        out_dir = Path(out_arg[2:])  # -o{staging}
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "ok" / "file.ma"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"maya")
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = ""
        return result

    monkeypatch.setattr("review_prep.archive_extractor.subprocess.run", fake_run)
    paths = extract_archive(archive, dest, Path("7z.exe"), max_files=10, max_bytes=10_000)
    assert len(paths) == 1
    assert paths[0].name == "file.ma"
    assert paths[0].read_bytes() == b"maya"
    assert paths[0].is_relative_to(dest)


def test_extract_ignores_preexisting_dest_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "ok.zip"
    dest = tmp_path / "out"
    dest.mkdir()
    preexisting = dest / "old.txt"
    preexisting.write_bytes(b"already-here")
    _make_zip(archive, {"new.txt": b"fresh"})

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        out_arg = next(str(a) for a in cmd if str(a).startswith("-o"))
        out_dir = Path(out_arg[2:])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "new.txt").write_bytes(b"fresh")
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = ""
        return result

    monkeypatch.setattr("review_prep.archive_extractor.subprocess.run", fake_run)
    # max_files=1 would fail if preexisting old.txt were counted
    paths = extract_archive(archive, dest, Path("7z.exe"), max_files=1, max_bytes=10_000)
    assert len(paths) == 1
    assert paths[0].name == "new.txt"
    assert preexisting.read_bytes() == b"already-here"


def test_extract_bad_7z_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "ok.zip"
    _make_zip(archive, {"ok/file.ma": b"maya"})

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        result = MagicMock()
        result.returncode = 2
        result.stderr = "broken"
        result.stdout = ""
        return result

    monkeypatch.setattr("review_prep.archive_extractor.subprocess.run", fake_run)
    with pytest.raises(UnsafeArchiveError, match="7z exited"):
        extract_archive(archive, tmp_path / "out", Path("7z"), max_files=10, max_bytes=10_000)


def _slt_listing(*members: tuple[str, int]) -> str:
    """Build a minimal ``7z l -slt`` stdout for tests."""
    parts = [
        "----------",
        "Path = sample.rar",
        "Type = Rar",
        "----------",
    ]
    for name, size in members:
        parts.extend(
            [
                f"Path = {name}",
                "Folder = -",
                f"Size = {size}",
                "Attributes = A",
                "----------",
            ]
        )
    return "\n".join(parts)


def test_rar_preflight_rejects_traversal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "bad.rar"
    archive.write_bytes(b"fake-rar")

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        assert cmd[1] == "l"
        assert "-slt" in cmd
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = _slt_listing(("../../evil.txt", 1))
        return result

    monkeypatch.setattr("review_prep.archive_extractor.subprocess.run", fake_run)
    with pytest.raises(UnsafeArchiveError, match="traversal|escapes|absolute"):
        extract_archive(archive, tmp_path / "out", Path("7z"), max_files=10, max_bytes=10_000)


def test_rar_preflight_rejects_max_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "many.rar"
    archive.write_bytes(b"fake-rar")

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        assert cmd[1] == "l"
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = _slt_listing(("a.txt", 1), ("b.txt", 1))
        return result

    monkeypatch.setattr("review_prep.archive_extractor.subprocess.run", fake_run)
    with pytest.raises(UnsafeArchiveError, match="max_files"):
        extract_archive(archive, tmp_path / "out", Path("7z"), max_files=1, max_bytes=10_000)


def test_rar_preflight_rejects_max_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "big.rar"
    archive.write_bytes(b"fake-rar")

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        assert cmd[1] == "l"
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = _slt_listing(("a.txt", 100))
        return result

    monkeypatch.setattr("review_prep.archive_extractor.subprocess.run", fake_run)
    with pytest.raises(UnsafeArchiveError, match="max_bytes"):
        extract_archive(archive, tmp_path / "out", Path("7z"), max_files=10, max_bytes=5)


@pytest.mark.integration
def test_extract_with_real_7z(tmp_path: Path) -> None:
    seven_zip = shutil.which("7z") or shutil.which("7z.exe")
    candidates = [Path(seven_zip) if seven_zip else None, Path(r"C:\Program Files\7-Zip\7z.exe"), Path(r"c:\depot\tools\bin\7z.exe")]
    exe = next((p for p in candidates if p is not None and p.is_file()), None)
    if exe is None:
        pytest.skip("7z not found")

    archive = tmp_path / "real.zip"
    dest = tmp_path / "extracted"
    _make_zip(archive, {"nested/hello.txt": b"hello-7z"})
    paths = extract_archive(archive, dest, exe, max_files=10, max_bytes=10_000)
    assert any(p.name == "hello.txt" and p.read_bytes() == b"hello-7z" for p in paths)
