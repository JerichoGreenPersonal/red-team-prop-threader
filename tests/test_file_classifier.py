from pathlib import Path

from review_prep.file_classifier import archive_kind, filter_launchable, is_recognized_dcc


def test_recognized_extensions():
    assert is_recognized_dcc(Path("a.ma"))
    assert is_recognized_dcc(Path("a.mb"))
    assert is_recognized_dcc(Path("a.ztl"))
    assert is_recognized_dcc(Path("a.spp"))
    assert not is_recognized_dcc(Path("a.png"))


def test_exclude_pattern():
    paths = [Path("hero_review.ma"), Path("hero_wip.ma")]
    out = filter_launchable(paths, include_globs=["*.ma"], exclude_globs=["*_wip.ma"])
    assert out == [Path("hero_review.ma")]


def test_archive_kind():
    assert archive_kind(Path("x.RAR")) == "rar"
    assert archive_kind(Path("x.zip")) == "zip"
    assert archive_kind(Path("x.ma")) is None
