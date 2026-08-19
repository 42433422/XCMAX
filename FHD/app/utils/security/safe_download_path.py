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
    roots = [Path(os.path.realpath(str(r))) for r in allowed_roots]
    raw = (file_arg or "").strip()
    if not raw:
        raise UnsafeDownloadPathError("empty path")

    # 去掉空段与「.」，保留「..」以便后续 commonpath 拒绝穿越
    parts = [p for p in Path(raw).parts if p not in ("", ".")]
    if not parts:
        raise UnsafeDownloadPathError("empty path")

    if Path(raw).is_absolute():
        # 绝对路径：先 realpath，再用相对片段在命中根下重建，切断 taint
        abs_candidate = Path(os.path.realpath(raw))
    else:
        abs_candidate = Path(os.path.realpath(str(roots[0].joinpath(*parts))))

    for root in roots:
        if not is_path_within(root, abs_candidate):
            continue
        try:
            rel = os.path.relpath(str(abs_candidate), str(root))
        except ValueError:
            continue
        if rel.startswith("..") or os.path.isabs(rel):
            continue
        # 在受信根下按相对路径重建，避免把用户原始字符串传到下游 I/O
        safe = Path(os.path.realpath(str(root.joinpath(*Path(rel).parts)))) if rel != "." else root
        if is_path_within(root, safe):
            return safe
    raise UnsafeDownloadPathError("path not under allowed dirs")
