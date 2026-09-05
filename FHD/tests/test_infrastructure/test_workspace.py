from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.workspace import (
    allocate_generated_workspace_file,
    resolve_existing_file_under_root,
    resolve_safe_workspace_relpath,
    traditional_resolve_path,
)


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


@pytest.mark.parametrize(
    ("kind", "parent", "prefix", "suffix"),
    [
        ("attendance-upload-xlsx", "uploads", "attendance-upload-", ".xlsx"),
        ("attendance-output", "424", "attendance-output-", ".xlsx"),
        ("attendance-export", "attendance_exports", "attendance-export-", ".xlsx"),
    ],
)
def test_allocate_generated_workspace_file_uses_server_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    parent: str,
    prefix: str,
    suffix: str,
) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    first = allocate_generated_workspace_file(kind)
    second = allocate_generated_workspace_file(kind)

    assert first.parent == tmp_path / parent
    assert first.name.startswith(prefix)
    assert first.suffix == suffix
    assert second != first


def test_allocate_generated_workspace_file_rejects_unknown_kind(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    with pytest.raises(ValueError, match="unsupported workspace file kind"):
        allocate_generated_workspace_file("../../caller-selected")


@pytest.mark.parametrize("resolver", [resolve_safe_workspace_relpath, traditional_resolve_path])
def test_workspace_resolvers_reject_normalized_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resolver
) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    with pytest.raises(Exception, match="invalid path"):
        resolver("nested/../../outside.txt")
