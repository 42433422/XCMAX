from __future__ import annotations

from pathlib import Path

import pytest

from modstore_server.infrastructure import library_paths


def test_mod_dir_rejects_traversal_and_invalid_ids(monkeypatch, tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(library_paths, "lib", lambda: library)

    for mod_id in ("..", "../outside", "/tmp/outside", "bad/id", "bad\\id"):
        with pytest.raises(ValueError, match="非法 mod id"):
            library_paths.mod_dir(mod_id)


def test_mod_dir_rejects_symlink_escape(monkeypatch, tmp_path: Path) -> None:
    library = tmp_path / "library"
    outside = tmp_path / "outside"
    library.mkdir()
    outside.mkdir()
    (library / "linked-mod").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(library_paths, "lib", lambda: library)

    with pytest.raises(ValueError, match="非法 mod id"):
        library_paths.mod_dir("linked-mod")


def test_mod_dir_accepts_valid_directory(monkeypatch, tmp_path: Path) -> None:
    library = tmp_path / "library"
    expected = library / "valid.mod-1"
    expected.mkdir(parents=True)
    monkeypatch.setattr(library_paths, "lib", lambda: library)

    assert library_paths.mod_dir("valid.mod-1") == expected.resolve()


def test_mod_dir_rejects_regular_file(monkeypatch, tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    (library / "not-a-mod").write_text("x", encoding="utf-8")
    monkeypatch.setattr(library_paths, "lib", lambda: library)

    with pytest.raises(FileNotFoundError, match="Mod 不存在"):
        library_paths.mod_dir("not-a-mod")
