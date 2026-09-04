"""Atomicity / conflict / rollback tests for :class:`PatchApplier`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vibe_coding.agent.patch import (
    FileEdit,
    Hunk,
    PatchApplier,
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
    patch = ProjectPatch(edits=[FileEdit(path="pkg/__init__.py", operation="create", contents="x")])
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
    patch = ProjectPatch(edits=[FileEdit(path="pkg/math.py", operation="modify", hunks=[hunk])])
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


def test_untrusted_patch_id_never_becomes_a_backup_path(tmp_path: Path) -> None:
    _make_project(tmp_path)
    patch = ProjectPatch(
        patch_id="../../*-attacker-controlled",
        edits=[FileEdit(path="pkg/new.py", operation="create", contents="SAFE = True\n")],
    )
    applier = PatchApplier(tmp_path)

    result = applier.apply(patch)

    assert result.applied
    backup = Path(result.backup_dir)
    assert backup.parent == applier.backup_dir
    assert patch.patch_id not in backup.name
    assert applier.rollback(patch.patch_id)
    assert not (tmp_path / "pkg" / "new.py").exists()


def test_backup_manifest_contains_only_project_relative_paths(tmp_path: Path) -> None:
    _make_project(tmp_path)
    patch = ProjectPatch(
        patch_id="relative-backup-manifest",
        edits=[FileEdit(path="pkg/delete_me.py", operation="delete")],
    )
    applier = PatchApplier(tmp_path)

    result = applier.apply(patch)

    assert result.applied
    manifest_path = Path(result.backup_dir) / "manifest.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert str(tmp_path) not in manifest_text
    assert manifest["entries"][0]["backup_file"] == "pkg/delete_me.py"
    assert applier.rollback(patch.patch_id)
    assert (tmp_path / "pkg" / "delete_me.py").is_file()


def test_rollback_rejects_tampered_manifest_project_escape(tmp_path: Path) -> None:
    _make_project(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("do not touch\n", encoding="utf-8")
    patch = ProjectPatch(
        patch_id="tampered-target",
        edits=[FileEdit(path="pkg/delete_me.py", operation="delete")],
    )
    applier = PatchApplier(tmp_path)
    result = applier.apply(patch)
    manifest_path = Path(result.backup_dir) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"][0]["path"] = f"../{outside.name}"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert not applier.rollback(patch.patch_id)
    assert outside.read_text(encoding="utf-8") == "do not touch\n"


def test_rollback_rejects_backup_symlink_escape(tmp_path: Path) -> None:
    _make_project(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-backup-source.txt"
    outside.write_text("attacker controlled\n", encoding="utf-8")
    patch = ProjectPatch(
        patch_id="tampered-backup",
        edits=[FileEdit(path="pkg/delete_me.py", operation="delete")],
    )
    applier = PatchApplier(tmp_path)
    result = applier.apply(patch)
    backup_source = Path(result.backup_dir) / "pkg" / "delete_me.py"
    backup_source.unlink()
    backup_source.symlink_to(outside)

    assert not applier.rollback(patch.patch_id)
    assert not (tmp_path / "pkg" / "delete_me.py").exists()


def test_modify_rejects_project_symlink_escape(tmp_path: Path) -> None:
    _make_project(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-project-target.py"
    outside.write_text("VALUE = 'outside'\n", encoding="utf-8")
    target = tmp_path / "pkg" / "math.py"
    target.unlink()
    target.symlink_to(outside)
    patch = ProjectPatch(
        edits=[
            FileEdit(
                path="pkg/math.py",
                operation="modify",
                hunks=[
                    Hunk(
                        anchor_before="VALUE = '",
                        old_text="outside",
                        new_text="changed",
                        anchor_after="'\n",
                    )
                ],
            )
        ]
    )

    result = PatchApplier(tmp_path).apply(patch)

    assert not result.applied
    assert "escapes root" in result.error
    assert outside.read_text(encoding="utf-8") == "VALUE = 'outside'\n"
