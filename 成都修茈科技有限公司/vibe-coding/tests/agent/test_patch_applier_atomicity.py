"""Atomicity / conflict / rollback tests for :class:`PatchApplier`."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibe_coding.agent.patch import (
    FileEdit,
    Hunk,
    PatchApplier,
    PatchConflict,
    ProjectPatch,
)


def _make_project(root: Path) -> None:
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("VERSION = '1.0'\n", encoding="utf-8")
    (root / "pkg" / "math.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (root / "pkg" / "delete_me.py").write_text("# bye\n", encoding="utf-8")


def test_modify_applies_with_anchor_match(tmp_path: Path) -> None:
    _make_project(tmp_path)
    hunk = Hunk(
        anchor_before="def add(a, b):\n",
        old_text="    return a + b\n",
        new_text="    return (a + b) * 2\n",
        anchor_after="\n\ndef sub(a, b):\n",
    )
    patch = ProjectPatch(
        edits=[FileEdit(path="pkg/math.py", operation="modify", hunks=[hunk])],
    )
    applier = PatchApplier(tmp_path)
    result = applier.apply(patch)
    assert result.applied
    assert "(a + b) * 2" in (tmp_path / "pkg" / "math.py").read_text(encoding="utf-8")


def test_create_delete_rename_applied(tmp_path: Path) -> None:
    _make_project(tmp_path)
    patch = ProjectPatch(
        edits=[
            FileEdit(path="pkg/new.py", operation="create", contents="X = 1\n"),
            FileEdit(path="pkg/delete_me.py", operation="delete"),
            FileEdit(path="pkg/__init__.py", operation="rename", new_path="pkg/_init.py"),
        ]
    )
    applier = PatchApplier(tmp_path)
    result = applier.apply(patch)
    assert result.applied
    assert (tmp_path / "pkg" / "new.py").exists()
    assert not (tmp_path / "pkg" / "delete_me.py").exists()
    assert (tmp_path / "pkg" / "_init.py").exists()
    assert not (tmp_path / "pkg" / "__init__.py").exists()


def test_create_rejects_existing(tmp_path: Path) -> None:
    _make_project(tmp_path)
    patch = ProjectPatch(
        edits=[FileEdit(path="pkg/__init__.py", operation="create", contents="x")]
    )
    applier = PatchApplier(tmp_path)
    result = applier.apply(patch)
    assert not result.applied
    assert "already exists" in (result.error or "")


def test_dry_run_does_not_touch_disk(tmp_path: Path) -> None:
    _make_project(tmp_path)
    original = (tmp_path / "pkg" / "math.py").read_text(encoding="utf-8")
    hunk = Hunk(
        anchor_before="def add(a, b):\n",
        old_text="    return a + b\n",
        new_text="    return 0\n",
        anchor_after="\n\ndef sub(a, b):\n",
    )
    applier = PatchApplier(tmp_path)
    result = applier.apply(
        ProjectPatch(edits=[FileEdit(path="pkg/math.py", operation="modify", hunks=[hunk])]),
        dry_run=True,
    )
    assert result.applied is True
    assert result.dry_run is True
    assert (tmp_path / "pkg" / "math.py").read_text(encoding="utf-8") == original


def test_atomic_rollback_when_one_hunk_misses(tmp_path: Path) -> None:
    _make_project(tmp_path)
    good = Hunk(
        anchor_before="def add(a, b):\n",
        old_text="    return a + b\n",
        new_text="    return 99\n",
        anchor_after="\n\ndef sub(a, b):\n",
    )
    bad = Hunk(
        anchor_before="this anchor is nowhere",
        old_text="impossible to find",
        new_text="oops",
        anchor_after="also nowhere",
    )
    patch = ProjectPatch(
        edits=[
            FileEdit(path="pkg/math.py", operation="modify", hunks=[good]),
            FileEdit(path="pkg/__init__.py", operation="modify", hunks=[bad]),
        ],
    )
    applier = PatchApplier(tmp_path)
    result = applier.apply(patch)
    assert not result.applied
    assert (tmp_path / "pkg" / "math.py").read_text(encoding="utf-8").count("return a + b") == 1


def test_rollback_after_apply(tmp_path: Path) -> None:
    _make_project(tmp_path)
    hunk = Hunk(
        anchor_before="def add(a, b):\n",
        old_text="    return a + b\n",
        new_text="    return 99\n",
        anchor_after="\n\ndef sub(a, b):\n",
    )
    patch = ProjectPatch(
        edits=[FileEdit(path="pkg/math.py", operation="modify", hunks=[hunk])]
    )
    applier = PatchApplier(tmp_path)
    res = applier.apply(patch)
    assert res.applied
    assert "return 99" in (tmp_path / "pkg" / "math.py").read_text(encoding="utf-8")
    ok = applier.rollback(patch.patch_id)
    assert ok
    assert "return a + b" in (tmp_path / "pkg" / "math.py").read_text(encoding="utf-8")


def test_rejects_path_outside_root(tmp_path: Path) -> None:
    _make_project(tmp_path)
    # Now that ``FileEdit`` itself runs the safe-path check at construction,
    # the rejection happens before we even reach the applier.
    with pytest.raises(ValueError, match=r"\.\.|parent traversal|outside|escape"):
        FileEdit(path="../evil.txt", operation="create", contents="x")


def test_rejects_absolute_path(tmp_path: Path) -> None:
    _make_project(tmp_path)
    with pytest.raises(ValueError, match=r"absolute"):
        FileEdit(path="/etc/passwd", operation="create", contents="x")


def test_rejects_drive_letter_path(tmp_path: Path) -> None:
    _make_project(tmp_path)
    with pytest.raises(ValueError, match=r"drive"):
        FileEdit(path="C:windows.ini", operation="create", contents="x")


def test_rejects_nul_byte_path(tmp_path: Path) -> None:
    _make_project(tmp_path)
    with pytest.raises(ValueError, match=r"NUL"):
        FileEdit(path="foo\x00bar.py", operation="create", contents="x")


def test_fuzzy_anchor_within_tolerance(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text(
        "# top\n# new lines added later\n\ndef foo():\n    return 1\n# tail\n",
        encoding="utf-8",
    )
    hunk = Hunk(
        anchor_before="def foo():\n",
        old_text="    return 1\n",
        new_text="    return 100\n",
        anchor_after="# tail\n",
    )
    patch = ProjectPatch(edits=[FileEdit(path="x.py", operation="modify", hunks=[hunk])])
    applier = PatchApplier(tmp_path)
    result = applier.apply(patch)
    assert result.applied
    text = (tmp_path / "x.py").read_text(encoding="utf-8")
    assert "return 100" in text and "return 1\n" not in text
