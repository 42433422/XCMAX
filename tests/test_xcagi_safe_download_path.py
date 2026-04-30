"""XCAGI 下载路径白名单：防目录穿越。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.safe_download_path import (
    UnsafeDownloadPathError,
    resolve_under_allowed_dirs,
)


def test_resolve_under_allowed_dirs_ok(tmp_path: Path) -> None:
    root = tmp_path / "generated_price_lists"
    root.mkdir(parents=True)
    f = root / "demo.docx"
    f.write_bytes(b"x")
    resolved = resolve_under_allowed_dirs(str(f), [root])
    assert resolved == f.resolve()


def test_resolve_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "generated_price_lists"
    root.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    with pytest.raises(UnsafeDownloadPathError):
        resolve_under_allowed_dirs(str(outside), [root])


def test_resolve_relative_basename(tmp_path: Path) -> None:
    root = tmp_path / "generated_price_lists"
    root.mkdir(parents=True)
    f = root / "rel.docx"
    f.write_bytes(b"x")
    resolved = resolve_under_allowed_dirs("rel.docx", [root])
    assert resolved == f.resolve()
