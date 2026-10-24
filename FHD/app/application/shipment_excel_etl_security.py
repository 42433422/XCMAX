"""送货单 ETL 生产加固：路径沙箱、租户键。"""

from __future__ import annotations

import errno
import os
import secrets
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from app.utils.operational_errors import RECOVERABLE_ERRORS


class ShipmentEtlPathError(ValueError):
    """ETL 路径不在允许沙箱内。"""


def _secure_output_handles_available() -> bool:
    """Whether this platform can pin directories and atomically replace a leaf."""
    if os.name == "nt":
        return True  # Windows backend uses handle-relative NT file operations.
    return (
        os.name == "posix"
        and os.open in getattr(os, "supports_dir_fd", set())
        and os.mkdir in getattr(os, "supports_dir_fd", set())
        and os.rename in getattr(os, "supports_dir_fd", set())
        and os.unlink in getattr(os, "supports_dir_fd", set())
        and bool(getattr(os, "O_NOFOLLOW", 0))
        and bool(getattr(os, "O_DIRECTORY", 0))
    )


def _windows_file_api():
    """Bind the small Win32/NT API surface used for handle-relative file I/O."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll")
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.SetFileInformationByHandle.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetFileInformationByHandle.restype = wintypes.BOOL

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("Status", ctypes.c_long), ("Information", ctypes.c_size_t)]

    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    ntdll.NtCreateFile.restype = ctypes.c_long
    ntdll.RtlNtStatusToDosError.argtypes = [ctypes.c_long]
    ntdll.RtlNtStatusToDosError.restype = wintypes.ULONG
    return ctypes, wintypes, kernel32, ntdll, UnicodeString, ObjectAttributes, IoStatusBlock


def _windows_os_error():
    import ctypes

    return ctypes.WinError(ctypes.get_last_error())  # type: ignore[attr-defined]


def _windows_binary_flag() -> int:
    return int(getattr(os, "O_BINARY", 0))


def _windows_file_attributes(handle: int) -> int:
    import ctypes

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [("FileAttributes", ctypes.c_ulong), ("ReparseTag", ctypes.c_ulong)]

    _, wintypes, kernel32, *_ = _windows_file_api()
    info = FileAttributeTagInfo()
    if not kernel32.GetFileInformationByHandleEx(
        wintypes.HANDLE(handle), 9, ctypes.byref(info), ctypes.sizeof(info)
    ):
        raise _windows_os_error()
    return int(info.FileAttributes)


def _windows_wrap_handle(handle: int, flags: int) -> int:
    import msvcrt

    _, _, kernel32, *_ = _windows_file_api()
    descriptor: int | None = None
    accepted = False
    try:
        descriptor = msvcrt.open_osfhandle(  # type: ignore[attr-defined]
            handle, flags | _windows_binary_flag()
        )
        if _windows_file_attributes(handle) & 0x400:
            raise ShipmentEtlPathError("output path contains a reparse point")
        accepted = True
        return descriptor
    finally:
        if descriptor is None:
            kernel32.CloseHandle(handle)
        elif not accepted:
            os.close(descriptor)


def _windows_open_anchor(anchor: str) -> int:
    import msvcrt
    from ctypes import wintypes

    _, _, kernel32, *_ = _windows_file_api()
    handle = kernel32.CreateFileW(
        anchor,
        0x20 | 0x80 | 0x100000,
        0x1 | 0x2 | 0x4,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        raise _windows_os_error()
    transferred = False
    try:
        attrs = _windows_file_attributes(int(handle))
        if not attrs & 0x10 or attrs & 0x400:
            raise ShipmentEtlPathError("trusted output root is not a plain directory")
        descriptor = msvcrt.open_osfhandle(  # type: ignore[attr-defined]
            int(handle), os.O_RDONLY | _windows_binary_flag()
        )
        transferred = True
        return int(descriptor)
    finally:
        if not transferred:
            kernel32.CloseHandle(handle)


def _windows_open_relative(
    parent_fd: int,
    name: str,
    *,
    directory: bool,
    create: bool,
    for_output: bool = False,
    for_input: bool = False,
) -> int:
    """Open/create one child relative to a pinned directory handle."""
    import msvcrt

    name = _validated_path_component(name)
    ctypes, wintypes, _, ntdll, UnicodeString, ObjectAttributes, IoStatusBlock = _windows_file_api()
    from_handle = msvcrt.get_osfhandle(parent_fd)  # type: ignore[attr-defined]
    name_buffer = ctypes.create_unicode_buffer(name)
    name_bytes = len(name) * ctypes.sizeof(ctypes.c_wchar)
    unicode_name = UnicodeString(
        name_bytes,
        name_bytes + ctypes.sizeof(ctypes.c_wchar),
        ctypes.cast(name_buffer, wintypes.LPWSTR),
    )
    attributes = ObjectAttributes(
        ctypes.sizeof(ObjectAttributes),
        wintypes.HANDLE(from_handle),
        ctypes.pointer(unicode_name),
        0x40 | 0x1000,  # case-insensitive and fail if a reparse point is encountered
        None,
        None,
    )
    io_status = IoStatusBlock()
    result = wintypes.HANDLE()
    if for_output:
        access, disposition = (
            0x40000000 | 0x10000 | 0x100000 | 0x80,
            2,
        )  # WRITE | DELETE | SYNCHRONIZE | READ_ATTRIBUTES, CREATE
        options = 0x40 | 0x00200000 | 0x20  # NON_DIRECTORY | OPEN_REPARSE_POINT | SYNCHRONOUS
        attributes_on_create = 0x80
        fd_flags = os.O_WRONLY | _windows_binary_flag()
    elif directory:
        access = 0x80 | 0x20 | 0x100000  # READ_ATTRIBUTES | TRAVERSE | SYNCHRONIZE
        disposition = 3 if create else 1  # OPEN_IF / OPEN
        options = 0x1 | 0x00200000 | 0x20  # DIRECTORY | OPEN_REPARSE_POINT | SYNCHRONOUS
        attributes_on_create = 0x10
        fd_flags = os.O_RDONLY | _windows_binary_flag()
    elif for_input:
        access = 0x1 | 0x80 | 0x100000  # READ_DATA | READ_ATTRIBUTES | SYNCHRONIZE
        disposition = 1
        options = 0x40 | 0x00200000 | 0x20
        attributes_on_create = 0
        fd_flags = os.O_RDONLY | _windows_binary_flag()
    else:
        access, disposition = 0x80 | 0x100000, 1
        options = 0x40 | 0x00200000 | 0x20
        attributes_on_create = 0
        fd_flags = os.O_RDONLY | _windows_binary_flag()
    status = ntdll.NtCreateFile(
        ctypes.byref(result),
        access,
        ctypes.byref(attributes),
        ctypes.byref(io_status),
        None,
        attributes_on_create,
        0x1 | 0x2 | 0x4,
        disposition,
        options,
        None,
        0,
    )
    if status < 0:
        if status & 0xFFFFFFFF == 0xC000050B:
            raise ShipmentEtlPathError("output path contains a reparse point")
        win_error = int(ntdll.RtlNtStatusToDosError(status))
        raise OSError(win_error, ctypes.FormatError(win_error), name)
    raw_handle = int(result.value)
    return _windows_wrap_handle(raw_handle, fd_flags)


def _windows_rename_relative(file_fd: int, parent_fd: int, target_name: str) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    target_name = _validated_path_component(target_name)
    _, _, kernel32, *_ = _windows_file_api()

    class FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", ctypes.c_ubyte),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", ctypes.c_wchar * 1),
        ]

    encoded = target_name.encode("utf-16-le")
    size = ctypes.sizeof(FileRenameInfo) + len(encoded) - ctypes.sizeof(ctypes.c_wchar)
    buffer = ctypes.create_string_buffer(size)
    info = ctypes.cast(buffer, ctypes.POINTER(FileRenameInfo)).contents
    info.ReplaceIfExists = 1
    info.RootDirectory = wintypes.HANDLE(
        msvcrt.get_osfhandle(parent_fd)  # type: ignore[attr-defined]
    )
    info.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(info) + FileRenameInfo.FileName.offset, encoded, len(encoded))
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(file_fd))  # type: ignore[attr-defined]
    if not kernel32.SetFileInformationByHandle(handle, 3, buffer, size):
        raise _windows_os_error()


def _windows_set_delete_pending(file_fd: int) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _, _, kernel32, *_ = _windows_file_api()

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOLEAN)]

    info = FileDispositionInfo(True)
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(file_fd))  # type: ignore[attr-defined]
    if not kernel32.SetFileInformationByHandle(handle, 4, ctypes.byref(info), ctypes.sizeof(info)):
        raise _windows_os_error()


def _windows_reject_existing_reparse_leaf(parent_fd: int, name: str) -> None:
    try:
        existing_fd = _windows_open_relative(
            parent_fd,
            name,
            directory=False,
            create=False,
        )
    except ShipmentEtlPathError:
        raise
    except OSError as exc:
        if exc.errno in (2, 3) or getattr(exc, "winerror", None) in (2, 3):
            return
        raise
    os.close(existing_fd)


@contextmanager
def _open_windows_etl_output_file(path: Path, parent_fd: int) -> Iterator[BinaryIO]:
    """Write beside the destination, then rename through the pinned directory handle."""
    temp_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    stream: BinaryIO | None = None
    published = False
    try:
        descriptor = _windows_open_relative(
            parent_fd,
            temp_name,
            directory=False,
            create=False,
            for_output=True,
        )
        stream = os.fdopen(descriptor, "wb")
        descriptor = None  # ownership transferred to stream
        yield stream
        stream.flush()
        os.fsync(stream.fileno())
        output_name = _validated_path_component(path.name)
        _windows_reject_existing_reparse_leaf(parent_fd, output_name)
        _windows_rename_relative(stream.fileno(), parent_fd, output_name)
        published = True
    finally:
        try:
            if stream is not None:
                try:
                    if not published:
                        _windows_set_delete_pending(stream.fileno())
                finally:
                    stream.close()
            elif descriptor is not None:
                try:
                    _windows_set_delete_pending(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            # Handles are CRT descriptors opened from native directory handles.
            os.close(parent_fd)


def _reject_output_symlink(name: str, parent_fd: int) -> None:
    """Reject an existing leaf link immediately before atomic publication."""
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode):
        raise ShipmentEtlPathError("output file was replaced by a symbolic link")


def _validated_path_component(value: str) -> str:
    """Return one literal path component, rejecting separators and dot names."""
    component = os.path.basename(value)
    if (
        not component
        or component in (".", "..")
        or component != value
        or "/" in component
        or "\\" in component
        or "\x00" in component
    ):
        raise ShipmentEtlPathError("path contains an invalid component")
    if os.name == "nt":
        windows_device = component.split(".", 1)[0].upper()
        if (
            any(character in component for character in '<>:"|?*')
            or component.endswith((".", " "))
            or windows_device in {"CON", "PRN", "AUX", "NUL"}
            or len(windows_device) == 4
            and windows_device[:3] in {"COM", "LPT"}
            and windows_device[3] in "123456789"
        ):
            raise ShipmentEtlPathError("path contains an invalid Windows filename")
    return component


def _is_under_root(path: str, root: str) -> bool:
    """Compare canonical paths by components, including Windows case rules."""
    try:
        common = os.path.commonpath((os.path.normpath(path), os.path.normpath(root)))
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(os.path.normpath(root))


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
                app_data / "outputs",
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
        if any(_is_under_root(wr_real, r) for r in root_reals):
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
        # Check component ancestry before any filesystem operation. This also
        # honors Windows' case-insensitive path comparison.
        if not _is_under_root(normalized, root_text):
            continue
        # realpath removes traversal and resolves symlinks before the second
        # component-ancestry check.
        resolved = Path(os.path.realpath(normalized))
        resolved_root_text = os.path.realpath(root_text)
        resolved_text = str(resolved)
        if not _is_under_root(resolved_text, resolved_root_text):
            continue
        return resolved
    raise ShipmentEtlPathError("path not under allowed dirs")


def _open_directory_under_root(root: Path, directory: Path, *, create: bool) -> int:
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

    if os.name == "nt":
        fd = _windows_open_anchor(root.anchor)
        try:
            for part in (*root.parts[1:], *parts):
                next_fd = _windows_open_relative(
                    fd,
                    _validated_path_component(part),
                    directory=True,
                    create=create,
                )
                os.close(fd)
                fd = next_fd
            result = fd
            fd = -1
            return result
        finally:
            if fd >= 0:
                os.close(fd)

    if not _secure_output_handles_available():
        raise ShipmentEtlPathError(
            "secure ETL output is unavailable: this platform lacks no-follow directory handles"
        )

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow or not getattr(os, "O_DIRECTORY", 0):
        raise ShipmentEtlPathError("safe directory access is unavailable")
    directory_flags |= nofollow | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(root.anchor, directory_flags)
    try:
        for part in (*root.parts[1:], *parts):
            component = _validated_path_component(part)
            if create:
                try:
                    os.mkdir(component, 0o777, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(component, directory_flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        result = fd
        fd = -1  # ownership transferred to the caller
        return result
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ShipmentEtlPathError("output directory contains a link or non-directory") from exc
        raise
    finally:
        if fd >= 0:
            os.close(fd)


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
    name = _validated_path_component(Path(raw).name)
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
    os.close(parent_fd)
    return candidate


@contextmanager
def open_etl_input_file(
    file_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> Iterator[BinaryIO]:
    """Open a regular input file beneath a pinned, trusted directory handle."""
    path = resolve_etl_path(file_path, workspace_root=workspace_root)
    roots = etl_allowed_roots(workspace_root)
    root = next(
        (
            Path(os.path.realpath(str(allowed_root)))
            for allowed_root in roots
            if path == Path(os.path.realpath(str(allowed_root)))
            or Path(os.path.realpath(str(allowed_root))) in path.parents
        ),
        None,
    )
    if root is None:
        raise ShipmentEtlPathError("path not under allowed dirs")
    parent_fd = _open_directory_under_root(root, path.parent, create=False)
    descriptor: int | None = None
    try:
        name = _validated_path_component(path.name)
        if os.name == "nt":
            descriptor = _windows_open_relative(
                parent_fd,
                name,
                directory=False,
                create=False,
                for_input=True,
            )
        else:
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(name, flags, dir_fd=parent_fd)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ShipmentEtlPathError("input is not a regular file")
        stream = os.fdopen(descriptor, "rb")
        descriptor = None
        with stream:
            yield stream
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ShipmentEtlPathError("input path contains a link or non-file") from exc
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


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
    if not _secure_output_handles_available():
        raise ShipmentEtlPathError(
            "secure ETL output is unavailable: this platform lacks no-follow directory handles"
        )
    parent_fd = _open_directory_under_root(root, path.parent, create=True)
    if os.name == "nt":
        with _open_windows_etl_output_file(path, parent_fd) as output_stream:
            yield output_stream
        return
    temp_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    stream: BinaryIO | None = None
    published = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        flags |= getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(temp_name, flags, 0o666, dir_fd=parent_fd)
        stream = os.fdopen(descriptor, "wb")
        descriptor = None  # ownership transferred to stream
        yield stream
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()
        stream = None
        # Rename within the already-open, verified parent. This atomically
        # overwrites an existing regular file without following a leaf link.
        _reject_output_symlink(path.name, parent_fd)
        output_name = _validated_path_component(path.name)
        os.rename(temp_name, output_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        published = True
    finally:
        try:
            if stream is not None:
                stream.close()
            if descriptor is not None:
                os.close(descriptor)
        finally:
            try:
                if not published:
                    try:
                        os.unlink(temp_name, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
            finally:
                os.close(parent_fd)


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
