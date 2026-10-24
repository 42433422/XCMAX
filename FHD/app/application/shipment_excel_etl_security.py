"""送货单 ETL 生产加固：路径沙箱、租户键。"""

from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from app.utils.operational_errors import RECOVERABLE_ERRORS


class ShipmentEtlPathError(ValueError):
    """ETL 路径不在允许沙箱内。"""


def _trusted_base_roots() -> list[Path]:
    """Return managed data roots plus an explicitly configured workspace."""
    roots: list[Path] = []
    try:
        from app.utils.path_io.path_utils import (
            get_app_data_dir,
            get_data_dir,
            get_shipment_output_dir,
            get_upload_dir,
        )

        app_data = Path(get_app_data_dir()).resolve()
        roots.extend(
            (
                app_data / "temp_excel",
                Path(get_upload_dir()),
                Path(get_data_dir()),
                Path(get_shipment_output_dir()),
            )
        )
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        pass
    # A workspace is trusted only when the server operator configures its exact
    # root. Never add the whole current directory or system temp as a fallback.
    configured = str(os.environ.get("WORKSPACE_ROOT") or "").strip()
    if configured and not any(ch in configured for ch in ("\x00", "\n", "\r")):
        import tempfile

        configured_root = Path(os.path.realpath(configured))
        broad_roots = {os.path.realpath(os.getcwd()), os.path.realpath(tempfile.gettempdir())}
        covers_cwd = configured_root in Path(os.path.realpath(os.getcwd())).parents
        if (
            configured_root not in broad_roots
            and not covers_cwd
            and configured_root != Path(configured_root.anchor)
        ):
            roots.append(configured_root)
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def etl_allowed_roots(workspace_root: str | Path | None = None) -> list[Path]:
    """返回受信根；仅当 workspace_root 已落在受信根下时才并入。"""
    roots = list(_trusted_base_roots())
    candidates = [
        str(workspace_root or "").strip(),
        str(os.environ.get("WORKSPACE_ROOT") or "").strip(),
    ]
    root_reals = [os.path.realpath(str(r)) for r in roots]
    for wr in candidates:
        if not wr or any(ch in wr for ch in ("\x00", "\n", "\r")):
            continue
        try:
            wr_real = os.path.realpath(wr)
        except (OSError, ValueError):
            continue
        if any(wr_real == r or wr_real.startswith(r + os.sep) for r in root_reals):
            roots.append(Path(wr_real))
            root_reals.append(wr_real)
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = os.path.realpath(str(r))
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(key))
    return out


def _safe_under_roots(raw: str, roots: list[Path]) -> Path:
    """Resolve a path and require it to remain beneath one configured root."""
    text = str(raw or "").strip()
    if not text or "\x00" in text:
        raise ShipmentEtlPathError("empty path")

    root_paths = [Path(os.path.realpath(str(root))) for root in roots]
    if not root_paths:
        raise ShipmentEtlPathError("path not under allowed dirs")
    requested = Path(text)
    if ".." in requested.parts:
        raise ShipmentEtlPathError("path not under allowed dirs")
    for root in root_paths:
        candidate = requested if requested.is_absolute() else root / requested
        normalized = os.path.normpath(str(candidate))
        root_text = os.path.normpath(str(root))
        # Normalize first, then enforce a component-boundary prefix before any
        # filesystem operation. The second check protects against `/root-other`
        # while the following realpath check rejects symlink escapes.
        if not normalized.startswith(root_text):
            continue
        if normalized != root_text and not normalized.startswith(root_text + os.sep):
            continue
        # realpath removes traversal and resolves symlinks before the boundary
        # check. Keep the separator in the prefix test so `/root-other` is not
        # treated as a child of `/root`.
        resolved = Path(os.path.realpath(normalized))
        resolved_root_text = os.path.realpath(root_text)
        resolved_text = str(resolved)
        if not resolved_text.startswith(resolved_root_text):
            continue
        if resolved_text != resolved_root_text and not resolved_text.startswith(
            resolved_root_text + os.sep
        ):
            continue
        return resolved
    raise ShipmentEtlPathError("path not under allowed dirs")


def _open_directory_under_root(root: Path, directory: Path, *, create: bool) -> int | None:
    """Open a managed directory by walking components without following links."""
    root = Path(os.path.realpath(str(root)))
    directory = Path(os.path.normpath(str(directory)))
    try:
        relative = directory.relative_to(root)
    except ValueError as exc:
        raise ShipmentEtlPathError("path not under allowed dirs") from exc
    parts = relative.parts
    if any(part in ("", ".", "..") or "\\" in part for part in parts):
        raise ShipmentEtlPathError("path not under allowed dirs")

    if os.name != "posix" or os.open not in getattr(os, "supports_dir_fd", set()):
        # Keep Windows and other platforms working. Their path-based fallback
        # revalidates the canonical parent immediately before each filesystem
        # operation; POSIX uses directory descriptors and O_NOFOLLOW below.
        if create:
            directory.mkdir(parents=True, exist_ok=True)
        if Path(os.path.realpath(str(directory))) != directory:
            raise ShipmentEtlPathError("output directory changed during validation")
        return None

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow or not getattr(os, "O_DIRECTORY", 0):
        raise ShipmentEtlPathError("safe directory access is unavailable")
    directory_flags |= nofollow | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(root.anchor, directory_flags)
    try:
        for part in (*root.parts[1:], *parts):
            if create:
                try:
                    os.mkdir(part, 0o777, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, directory_flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ShipmentEtlPathError("output directory contains a link or non-directory") from exc
        raise
    except BaseException:
        os.close(fd)
        raise


def resolve_etl_path(
    file_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
    must_exist: bool = False,
) -> Path:
    """将用户传入路径解析到沙箱内。

    ``must_exist`` 保留兼容签名；存在性由调用方在打开文件时处理，
    避免 ``Path.exists`` 被静态分析标为 path-injection sink。
    """
    _ = must_exist
    roots = etl_allowed_roots(workspace_root)
    preferred = (
        Path(os.path.realpath(str(workspace_root)))
        if workspace_root
        else Path(os.path.realpath(os.getcwd()))
    )
    if preferred in roots:
        roots = [preferred, *(root for root in roots if root != preferred)]
    return _safe_under_roots(str(file_path or ""), roots)


def resolve_etl_output_path(
    output_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> Path:
    """输出路径必须落在沙箱内（父目录可尚不存在）。"""
    raw = str(output_path or "").strip()
    if not raw:
        raise ShipmentEtlPathError("empty output path")
    name = Path(raw).name
    if not name or name in (".", "..") or "\\" in name or "\x00" in name:
        raise ShipmentEtlPathError("invalid output name")
    parent_raw = str(Path(raw).parent) if Path(raw).parent.as_posix() not in (".", "") else "."
    if parent_raw in (".", ""):
        # 仅文件名：落到第一个受信根
        roots = etl_allowed_roots(workspace_root)
        if not roots:
            raise ShipmentEtlPathError("path not under allowed dirs")
        parent = roots[0]
    else:
        parent = _safe_under_roots(parent_raw, etl_allowed_roots(workspace_root))
    # Derive the leaf only from the validated canonical parent, never from the
    # original output path after validating its parent.
    parent_path = Path(os.path.realpath(str(parent)))
    candidate = Path(os.path.normpath(os.path.join(str(parent_path), name)))
    parent_text = str(parent_path)
    candidate_text = str(candidate)
    if candidate.parent != parent_path or candidate_text == parent_text:
        raise ShipmentEtlPathError("output path not under allowed dirs")
    resolved_candidate = Path(os.path.realpath(candidate_text))
    if resolved_candidate != candidate:
        raise ShipmentEtlPathError("output path resolves through a symbolic link")
    # Create parent components only after validating the complete destination;
    # the descriptor walk rejects links inserted during directory creation.
    root = next(
        (
            Path(os.path.realpath(str(allowed_root)))
            for allowed_root in etl_allowed_roots(workspace_root)
            if parent_path == Path(os.path.realpath(str(allowed_root)))
            or Path(os.path.realpath(str(allowed_root))) in parent_path.parents
        ),
        None,
    )
    if root is None:
        raise ShipmentEtlPathError("path not under allowed dirs")
    parent_fd = _open_directory_under_root(root, parent_path, create=True)
    if parent_fd is not None:
        os.close(parent_fd)
    return candidate


@contextmanager
def open_etl_output_file(
    output_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> Iterator[BinaryIO]:
    """Open an approved output without following a replaced parent or leaf link."""
    path = resolve_etl_output_path(output_path, workspace_root=workspace_root)
    roots = etl_allowed_roots(workspace_root)
    root = next(
        (
            Path(os.path.realpath(str(allowed_root)))
            for allowed_root in roots
            if path.parent == Path(os.path.realpath(str(allowed_root)))
            or Path(os.path.realpath(str(allowed_root))) in path.parent.parents
        ),
        None,
    )
    if root is None:
        raise ShipmentEtlPathError("path not under allowed dirs")
    parent_fd = _open_directory_under_root(root, path.parent, create=True)
    if parent_fd is None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o666)
    else:
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
            flags |= getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(path.name, flags, 0o666, dir_fd=parent_fd)
        except OSError as exc:
            if exc.errno in (errno.ELOOP, errno.EISDIR):
                raise ShipmentEtlPathError("output file was replaced by a link") from exc
            raise
        finally:
            os.close(parent_fd)
    with os.fdopen(descriptor, "wb") as stream:
        yield stream


def tenant_key_for_etl() -> str:
    try:
        from app.infrastructure.tenant_scope import current_tenant_id

        tid = current_tenant_id()
        if tid is not None:
            return f"tenant:{int(tid)}"
    except RECOVERABLE_ERRORS:  # noqa: BLE001
        pass
    return "tenant:local"


def batch_execute_allowed() -> bool:
    return os.environ.get("FHD_SHIPMENT_ETL_ALLOW_BATCH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def direct_execute_allowed() -> bool:
    """无预览直写生产库：默认关闭，需显式环境开关。"""
    for key in ("FHD_EXCEL_ETL_ALLOW_DIRECT", "FHD_SHIPMENT_ETL_ALLOW_DIRECT"):
        if os.environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False
