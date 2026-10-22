"""Validate and stage Mod archives before touching a published directory."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tempfile
import threading
import unicodedata
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from modman.manifest_util import validate_manifest_dict

MAX_FILES = 10_000
MAX_UNPACKED_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_THREAD_LOCK = threading.Lock()
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *(f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "¹²³"),
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _validated_archive(zf: zipfile.ZipFile) -> tuple[str, list[tuple[zipfile.ZipInfo, list[str]]]]:
    infos = zf.infolist()
    if (
        not infos
        or len(infos) > MAX_FILES
        or sum(info.file_size for info in infos) > MAX_UNPACKED_BYTES
    ):
        raise ValueError("空 zip 或解压规模超过限制")
    entries = []
    seen: dict[str, bool] = {}
    roots = set()
    for info in infos:
        name = info.filename
        if info.orig_filename != name or "\\" in name or info.flag_bits & 1:
            raise ValueError("zip 包含不安全或加密的路径")
        parts = name[:-1].split("/") if info.is_dir() else name.split("/")
        if any(
            not part
            or part in {".", ".."}
            or any(char in part for char in ':<>"|?*')
            or part[-1:] in {".", " "}
            or any(ord(char) < 32 for char in part)
            or part.split(".")[0].rstrip(" ").upper() in _RESERVED
            for part in parts
        ):
            raise ValueError("zip 包含不安全路径")
        kind = stat.S_IFMT(info.external_attr >> 16)
        if kind not in {0, stat.S_IFREG, stat.S_IFDIR} or (
            kind != 0 and (kind == stat.S_IFDIR) != info.is_dir()
        ):
            raise ValueError("zip 禁止符号链接和特殊文件")
        key = unicodedata.normalize("NFC", "/".join(parts)).casefold()
        if key in seen:
            raise ValueError("zip 包含重复或跨平台冲突路径")
        seen[key] = info.is_dir()
        roots.add(parts[0])
        entries.append((info, parts))
    if len(roots) != 1:
        raise ValueError("zip 顶层须为一个 Mod 文件夹")
    root = next(iter(roots))
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", root):
        raise ValueError("非法 Mod 文件夹名")
    for key in seen:
        components = key.split("/")
        if any(
            seen.get("/".join(components[:index])) is False for index in range(1, len(components))
        ):
            raise ValueError("zip 文件与目录路径冲突")
    manifest_info = next(
        (info for info, parts in entries if parts == [root, "manifest.json"]), None
    )
    if (
        manifest_info is None
        or manifest_info.is_dir()
        or manifest_info.file_size > MAX_MANIFEST_BYTES
    ):
        raise ValueError("缺少有效 manifest.json 或文件过大")
    try:
        data = json.loads(zf.read(manifest_info).decode("utf-8"))
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("id"), str)
            or data["id"].strip() != root
        ):
            raise ValueError("文件夹名须与 manifest.id 一致")
        errors = validate_manifest_dict(data)
    except (UnicodeError, TypeError, AttributeError) as exc:
        raise ValueError("manifest 字段类型无效") from exc
    if errors:
        raise ValueError("manifest: " + "; ".join(errors))
    return root, entries


@contextmanager
def _library_write_lock(library: Path) -> Iterator[None]:
    """Importers share a process and OS lock; unsupported platforms fail closed."""
    with _THREAD_LOCK:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(library / ".mod-import.lock", flags, 0o600)
        with os.fdopen(descriptor, "r+b") as handle:
            if sys.platform == "win32":
                import msvcrt

                if not os.fstat(handle.fileno()).st_size:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

                def unlock() -> None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

            elif os.name == "posix":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

                def unlock() -> None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

            else:
                raise RuntimeError("当前平台不支持安全导入锁")
            try:
                yield
            finally:
                unlock()


def import_zip(zip_path: Path, library: Path, *, replace: bool = True) -> Path:
    """Validate, stage, serialize, then publish; retain recovery data if rollback fails.

    This is not a power-loss transaction. A killed process may leave a hidden
    staging directory that needs operator recovery; never silently discard it.
    """
    library = library.resolve()
    if library == library.parent:
        raise ValueError("Mod 库不能是文件系统根目录")
    staging: Path | None = None
    retain_recovery = False
    try:
        with zipfile.ZipFile(zip_path.resolve(), "r") as zf:
            root, entries = _validated_archive(zf)
            library.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".mod-import-", dir=library))
            payload = staging / "payload"
            for info, parts in entries:
                target = payload.joinpath(*parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(info) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, length=64 * 1024)
        destination = library / root
        backup = staging / "previous"
        with _library_write_lock(library):
            if destination.is_symlink() or destination.resolve().parent != library:
                raise ValueError("目标目录不能是符号链接或越界路径")
            exists = destination.exists()
            if exists and not replace:
                raise FileExistsError(str(destination))
            if exists and not destination.is_dir():
                raise ValueError("目标不是目录")
            if exists:
                # Fail closed before moving the only old copy, including interrupts.
                retain_recovery = True
                os.replace(destination, backup)
            try:
                os.replace(payload / root, destination)
            except OSError:
                if exists:
                    try:
                        os.replace(backup, destination)
                    except OSError as recovery_error:
                        retain_recovery = True
                        raise RuntimeError(f"恢复失败，旧版本保留于 {backup}") from recovery_error
                    retain_recovery = False
                raise
            retain_recovery = False
        return destination
    except (zipfile.BadZipFile, NotImplementedError) as exc:
        raise ValueError("无效或不支持的 zip") from exc
    finally:
        if staging is not None and not retain_recovery:
            shutil.rmtree(staging, ignore_errors=True)
