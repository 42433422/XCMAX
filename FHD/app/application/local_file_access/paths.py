"""本机文件只读访问的路径边界与敏感路径规则。

所有对外读取都必须经过 ``resolve_authorized_path``：先用 realpath 消掉
``..`` 与符号链接，再确认落在授权根目录内；整机模式也只能落在用户主目录
或外接卷，并额外经过敏感目录/敏感文件名黑名单。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES_PER_SCAN = 5000
ALLOWED_SUFFIXES = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".csv",
        ".txt",
        ".md",
        ".json",
        ".log",
        ".pptx",
    }
)

# 目录名命中即整棵子树跳过（不区分大小写）。
DENIED_DIR_NAMES = frozenset(
    {
        ".ssh",
        ".gnupg",
        ".aws",
        ".git",
        "node_modules",
        "keychains",
        "com.apple.tcc",
        "cookies",
        "messages",
        "__pycache__",
        ".venv",
        "site-packages",
    }
)
DENIED_FILE_NAMES = frozenset(
    {
        ".env",
        "cookies",
        "cookies-journal",
        "login data",
        "history",
        "keychain-db",
    }
)
DENIED_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".kdbx", ".keychain"})


class LocalFilePathError(ValueError):
    """路径越权或不满足只读读取条件。"""


@dataclass(frozen=True)
class CandidateFile:
    path: Path
    relative_path: str
    size_bytes: int
    mtime_ns: int


def _real(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.expanduser(str(path))).resolve(strict=False)


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath([str(child), str(parent)]) == str(parent)
    except ValueError:
        return False


def _home() -> Path:
    return _real(Path.home())


def allowed_scan_roots(grant) -> list[Path]:
    """授权可覆盖的根目录；整机模式限定主目录与外接卷。"""
    if str(getattr(grant, "mode", "folder")) == "full_disk":
        roots = [_home()]
        volumes = _real("/Volumes")
        if volumes.is_dir():
            roots.append(volumes)
        return roots
    return [_real(getattr(grant, "root_path", ""))]


def is_denied(path: Path) -> bool:
    lowered_parts = [part.lower() for part in path.parts]
    if any(part in DENIED_DIR_NAMES for part in lowered_parts):
        return True
    name = path.name.lower()
    if name in DENIED_FILE_NAMES:
        return True
    return path.suffix.lower() in DENIED_SUFFIXES


def resolve_authorized_path(grant, candidate: str | os.PathLike[str]) -> Path:
    """返回可读取的真实路径；越权、黑名单、超限或不存在时抛 LocalFilePathError。"""
    real = _real(candidate)
    if not any(_is_relative_to(real, root) for root in allowed_scan_roots(grant)):
        raise LocalFilePathError("文件不在已授权的目录内")
    if is_denied(real):
        raise LocalFilePathError("该路径属于敏感目录或敏感文件，已拒绝读取")
    if not real.is_file():
        raise LocalFilePathError("目标不是可读取的文件")
    try:
        size = real.stat().st_size
    except OSError as exc:
        raise LocalFilePathError(f"无法读取文件元信息：{exc}") from exc
    if size > MAX_FILE_BYTES:
        raise LocalFilePathError("文件超过单个文件大小上限")
    if real.suffix.lower() not in ALLOWED_SUFFIXES:
        raise LocalFilePathError("暂不支持该文件类型")
    return real


def create_grant_root(mode: str, candidate: str | os.PathLike[str]) -> Path:
    """校验授权目录本身：必须是真实目录且不是敏感目录。"""
    real = _real(candidate)
    if not real.is_dir():
        raise LocalFilePathError("请授权一个存在的文件夹")
    if is_denied(real):
        raise LocalFilePathError("不能授权敏感目录")
    if mode == "full_disk":
        if not any(_is_relative_to(real, root) for root in allowed_scan_roots(_FullDiskProbe())):
            raise LocalFilePathError("整机模式只能授权主目录或外接卷")
    return real


class _FullDiskProbe:
    mode = "full_disk"


def iter_candidate_files(root: Path, *, limit: int = MAX_FILES_PER_SCAN) -> Iterable[CandidateFile]:
    """遍历授权目录：不跟符号链接、跳过敏感路径与不支持的类型。"""
    yielded = 0
    real_root = _real(root)
    for dirpath, dirnames, filenames in os.walk(real_root, followlinks=False):
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".") or name in {".config"}
        ]
        for name in filenames:
            path = _real(Path(dirpath) / name)
            if is_denied(path) or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > MAX_FILE_BYTES:
                continue
            yielded += 1
            if yielded > limit:
                return
            yield CandidateFile(
                path=path,
                relative_path=str(path.relative_to(real_root)),
                size_bytes=int(stat.st_size),
                mtime_ns=int(stat.st_mtime_ns),
            )
