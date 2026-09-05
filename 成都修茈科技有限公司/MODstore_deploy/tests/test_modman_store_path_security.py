from __future__ import annotations

import json
from pathlib import Path

import pytest

from modman.store import find_mod_dir_by_manifest_id, remove_mod


def _write_mod(path: Path, mod_id: str) -> None:
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "id": mod_id,
                "name": "Security test mod",
                "version": "1.0.0",
                "entry": {"backend": "backend/main.py"},
            }
        ),
        encoding="utf-8",
    )


def test_find_mod_selects_enumerated_manifest_id(tmp_path: Path) -> None:
    library = tmp_path / "library"
    expected = library / "legacy-folder-name"
    _write_mod(expected, "safe-mod")

    assert find_mod_dir_by_manifest_id(library, "safe-mod") == expected.resolve()


def test_find_mod_does_not_fallback_to_manifestless_input_path(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "untrusted-name").mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        find_mod_dir_by_manifest_id(library, "untrusted-name")


def test_remove_mod_rejects_symlink_escape(tmp_path: Path) -> None:
    library = tmp_path / "library"
    outside = tmp_path / "outside"
    library.mkdir()
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    (library / "linked-mod").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="非法路径"):
        remove_mod(library, "linked-mod")
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_remove_mod_deletes_only_matching_real_child(tmp_path: Path) -> None:
    library = tmp_path / "library"
    target = library / "target-mod"
    _write_mod(target, "target-mod")

    remove_mod(library, "target-mod")

    assert not target.exists()
