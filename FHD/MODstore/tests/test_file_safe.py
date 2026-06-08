"""file_safe 纯函数单测（不启动 HTTP）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from modstore_server.file_safe import (
    MAX_FILE_BYTES,
    normalize_rel_path,
    read_text_file,
    resolve_under_mod,
    write_text_file,
)


def test_normalize_rejects_parent_segments():
    with pytest.raises(ValueError, match="非法路径"):
        normalize_rel_path("../x")
    with pytest.raises(ValueError, match="非法路径"):
        normalize_rel_path("a/../b")


def test_normalize_ok():
    assert normalize_rel_path("backend/foo.py") == "backend/foo.py"
    assert normalize_rel_path("/manifest.json") == "manifest.json"


def test_resolve_under_mod_traversal(tmp_path: Path):
    mod = tmp_path / "mymod"
    mod.mkdir()
    with pytest.raises(ValueError, match="非法路径|路径越界"):
        resolve_under_mod(mod, "../../../etc/passwd")


def test_resolve_rejects_bad_suffix(tmp_path: Path):
    mod = tmp_path / "m"
    mod.mkdir()
    (mod / "x.exe").write_bytes(b"")
    with pytest.raises(ValueError, match="不允许的扩展名"):
        resolve_under_mod(mod, "x.exe")


def test_read_write_roundtrip(tmp_path: Path):
    mod = tmp_path / "m"
    mod.mkdir()
    p = resolve_under_mod(mod, "readme.md")
    write_text_file(p, "hello")
    assert read_text_file(p) == "hello"


def test_read_rejects_oversize(tmp_path: Path):
    mod = tmp_path / "m"
    mod.mkdir()
    big = mod / "big.py"
    big.write_bytes(b"x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(ValueError, match="过大"):
        read_text_file(big)
