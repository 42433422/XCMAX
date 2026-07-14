from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.workspace import resolve_existing_file_under_root


def test_resolve_existing_file_under_root_matches_directory_entries(tmp_path: Path) -> None:
    target = tmp_path / "outputs" / "data.json"
    target.parent.mkdir()
    target.write_text("{}", encoding="utf-8")

    assert resolve_existing_file_under_root(tmp_path, "outputs/data.json") == target
    assert resolve_existing_file_under_root(tmp_path, "outputs\\data.json") == target


@pytest.mark.parametrize("relative", ["", "/etc/passwd", "../secret", "a/../secret", "C:/x"])
def test_resolve_existing_file_under_root_rejects_untrusted_shapes(
    tmp_path: Path, relative: str
) -> None:
    with pytest.raises(ValueError):
        resolve_existing_file_under_root(tmp_path, relative)


def test_resolve_existing_file_under_root_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)

    with pytest.raises(FileNotFoundError):
        resolve_existing_file_under_root(tmp_path, link.name)


def test_resolve_existing_file_under_root_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_existing_file_under_root(tmp_path, "missing.txt")
