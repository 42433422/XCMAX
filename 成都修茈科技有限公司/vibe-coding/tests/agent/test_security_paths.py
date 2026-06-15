"""Unit tests for :mod:`vibe_coding.agent.security.paths`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vibe_coding.agent.security.paths import (
    PathSafetyError,
    is_safe_relative,
    resolve_within_root,
    safe_relative_path,
)


@pytest.mark.parametrize(
    "good",
    [
        "a.py",
        "pkg/a.py",
        "deep/nested/path/file.txt",
        "with-dash/and_underscore/x.py",
        "中文路径/file.py",
        ".github/workflows/ci.yml",
        "./relative.py",  # leading dot tolerated, normalised away
        "trailing/slash/",
    ],
)
def test_safe_paths_accepted(good: str) -> None:
    out = safe_relative_path(good)
    assert not out.startswith("/")
    assert ".." not in out.split("/")
    assert "\\" not in out


@pytest.mark.parametrize(
    "bad,reason_substr",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("..", "parent"),
        ("../etc/passwd", "parent"),
        ("foo/../etc", "parent"),
        ("/etc/passwd", "absolute"),
        ("//host/share", "absolute"),
        ("\\\\host\\share", "absolute"),
        ("C:/Windows/system32", "drive"),
        ("c:relative", "drive"),
        ("foo\x00bar", "NUL"),
        ("~/secrets.env", "tilde"),
        ("~root/foo", "tilde"),
    ],
)
def test_unsafe_paths_rejected(bad: str, reason_substr: str) -> None:
    with pytest.raises(PathSafetyError) as exc_info:
        safe_relative_path(bad)
    assert reason_substr.lower() in exc_info.value.reason.lower()


def test_is_safe_relative_predicate() -> None:
    assert is_safe_relative("foo/bar.py")
    assert not is_safe_relative("../bad")
    assert not is_safe_relative("/abs")
    assert not is_safe_relative("")


def test_resolve_within_root_happy_path(tmp_path: Path) -> None:
    target = tmp_path / "pkg" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text("ok", encoding="utf-8")
    out = resolve_within_root(tmp_path, "pkg/a.py")
    assert out == target.resolve()


def test_resolve_within_root_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError):
        resolve_within_root(tmp_path, "../escape.txt")


def test_resolve_within_root_rejects_absolute(tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError):
        resolve_within_root(tmp_path, "/etc/passwd")


def test_resolve_within_root_allows_fresh_destination(tmp_path: Path) -> None:
    """A non-existent leaf is allowed when ``allow_existing_symlink=True``."""
    out = resolve_within_root(
        tmp_path, "new_dir/new_file.py", allow_existing_symlink=True
    )
    assert str(out).startswith(str(tmp_path.resolve()))


@pytest.mark.skipif(os.name == "nt", reason="symlink test is POSIX-only here")
def test_resolve_within_root_blocks_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    with pytest.raises(PathSafetyError):
        resolve_within_root(tmp_path, "link.txt")


def test_normalised_output_is_posix_style() -> None:
    out = safe_relative_path("foo\\bar\\baz.py")
    assert out == "foo/bar/baz.py"


def test_pathlike_input_accepted(tmp_path: Path) -> None:
    rel = Path("pkg") / "x.py"
    out = safe_relative_path(rel)
    assert out.endswith("x.py")
