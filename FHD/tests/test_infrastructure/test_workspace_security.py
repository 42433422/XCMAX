from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.infrastructure.workspace import (
    read_safe_workspace_file,
    resolve_safe_workspace_relpath,
)


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(root))
    return root


def test_valid_nested_workspace_path_is_preserved(workspace: Path) -> None:
    expected = workspace / "uploads" / "nested" / "report.json"
    assert resolve_safe_workspace_relpath("uploads/nested/report.json") == expected


@pytest.mark.parametrize(
    "untrusted",
    [
        "../secret.txt",
        "uploads/../../secret.txt",
        "%2e%2e/secret.txt",
        "%252e%252e%252fsecret.txt",
        "uploads/%252e%252e/%252e%252e/secret.txt",
        "..%255csecret.txt",
        "/etc/passwd",
        "C:\\Windows\\system.ini",
    ],
)
def test_traversal_absolute_and_nested_encoding_are_rejected(
    workspace: Path,
    untrusted: str,
) -> None:
    with pytest.raises(HTTPException) as caught:
        resolve_safe_workspace_relpath(untrusted)
    assert caught.value.status_code == 400


def test_symlink_escape_is_rejected(workspace: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "linked.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(HTTPException) as caught:
        resolve_safe_workspace_relpath("linked.txt")
    assert caught.value.status_code == 400


def test_confined_reader_reads_valid_nested_file(workspace: Path) -> None:
    nested = workspace / "outputs" / "nested"
    nested.mkdir(parents=True)
    target = nested / "result.txt"
    target.write_text("safe result", encoding="utf-8")

    path, blob = read_safe_workspace_file("outputs/nested/result.txt", max_bytes=64)

    assert path == target
    assert blob == b"safe result"
