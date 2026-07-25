"""将下载/导出路径解析到允许目录树下，防止目录穿越。"""

from __future__ import annotations

import os
from pathlib import Path


class UnsafeDownloadPathError(ValueError):
    """路径不在允许的根目录之下。"""


def is_path_within(root: Path, candidate: Path) -> bool:
    """判断 candidate 是否落在 root 之下（含 root 自身）。"""
    try:
        root_s = os.path.realpath(str(root))
        cand_s = os.path.realpath(str(candidate))
        return os.path.commonpath([root_s, cand_s]) == root_s
    except (ValueError, OSError):
        return False


def resolve_under_allowed_dirs(file_arg: str, allowed_roots: list[Path]) -> Path:
    """
    :param file_arg: 绝对路径或相对于首个 allowed_root 的文件名。
    :param allowed_roots: 允许的目录列表（应已 resolve）。
    :returns: 解析后的绝对路径。
    """
    if not allowed_roots:
        raise UnsafeDownloadPathError("no allowed roots")
    roots = [Path(r).resolve() for r in allowed_roots]
    raw = (file_arg or "").strip()
    if not raw:
        raise UnsafeDownloadPathError("empty path")

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (roots[0] / raw).resolve()
    else:
        candidate = candidate.resolve()

    for root in roots:
        if is_path_within(root, candidate):
            return candidate
    raise UnsafeDownloadPathError("path not under allowed dirs")
