from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException

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


@pytest.mark.parametrize(
    "relative", ["reports/report%20one.csv", "reports\\report one.csv", "/reports/report one.csv"]
)
def test_default_workspace_resolver_keeps_url_path_contract(tmp_path: Path, monkeypatch, relative):
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))

    assert resolve_safe_workspace_relpath(relative) == tmp_path / "reports/report one.csv"


@pytest.mark.parametrize(
    "relative", ["", "../outside", "nested/../../file", "/etc/passwd", "bad\x00name"]
)
def test_explicit_workspace_root_rejects_non_relative_paths(tmp_path: Path, relative):
    with pytest.raises(HTTPException, match="invalid path|missing path"):
        resolve_safe_workspace_relpath(relative, base=tmp_path)


@pytest.mark.parametrize("filesystem_root", [False, True])
def test_workspace_resolver_preserves_root_and_child_identity(
    tmp_path: Path, monkeypatch, filesystem_root
):
    root = Path(tmp_path.anchor) if filesystem_root else tmp_path
    monkeypatch.setenv("WORKSPACE_ROOT", str(root))

    assert resolve_safe_workspace_relpath(".") == root
    assert resolve_safe_workspace_relpath(".", base=root) == root
    relative = (tmp_path / "result.csv").relative_to(root).as_posix()
    assert resolve_safe_workspace_relpath(relative, base=root) == tmp_path / "result.csv"
    assert not (tmp_path / "result.csv").exists()


def test_explicit_workspace_root_preserves_native_names_and_checks_links(tmp_path: Path):
    root = tmp_path / "tenant"
    outside = tmp_path / "tenant-private"
    root.mkdir()
    outside.mkdir()
    (root / "a").mkdir()
    (root / "a/file").write_text("approved")
    (outside / "file").write_text("private")
    (outside / "nested").mkdir()
    (root / "%61").symlink_to(outside, target_is_directory=True)
    (root / "inside").symlink_to(root / "a", target_is_directory=True)
    (root / "jump").symlink_to(outside / "nested", target_is_directory=True)

    with pytest.raises(HTTPException, match="invalid path"):
        resolve_safe_workspace_relpath("%61/file", base=root)
    with pytest.raises(HTTPException, match="invalid path"):
        resolve_safe_workspace_relpath("jump/../file", base=root)
    assert resolve_safe_workspace_relpath("inside/file", base=root) == root / "a/file"
    assert resolve_safe_workspace_relpath("a/../a/file", base=root) == root / "a/file"
    assert resolve_safe_workspace_relpath("new/output.csv", base=root) == root / "new/output.csv"
    assert not (root / "new").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX native backslash filename")
def test_explicit_workspace_root_does_not_rewrite_native_backslashes(tmp_path: Path):
    literal = tmp_path / "a\\b"
    literal.write_text("literal filename")

    assert resolve_safe_workspace_relpath(literal.name, base=tmp_path) == literal
