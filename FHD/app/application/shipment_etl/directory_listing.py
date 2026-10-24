"""Directory-entry enumeration from an already pinned directory handle."""

from __future__ import annotations

import os
import struct

_FILE_ID_BOTH_DIRECTORY_INFO_NAME_OFFSET = 104
_FILE_ID_BOTH_DIRECTORY_INFO_NAME_LENGTH_OFFSET = 60
_FILE_ID_BOTH_DIRECTORY_INFO = 10
_FILE_ID_BOTH_DIRECTORY_RESTART_INFO = 11


def _parse_windows_directory_page(data: bytes) -> list[str]:
    """Parse a bounded FILE_ID_BOTH_DIR_INFO page returned by Win32."""
    names: list[str] = []
    offset = 0
    while True:
        remaining = len(data) - offset
        if remaining < _FILE_ID_BOTH_DIRECTORY_INFO_NAME_OFFSET:
            raise OSError("truncated Windows directory entry header")
        next_offset = struct.unpack_from("<I", data, offset)[0]
        name_length = struct.unpack_from(
            "<I", data, offset + _FILE_ID_BOTH_DIRECTORY_INFO_NAME_LENGTH_OFFSET
        )[0]
        name_start = offset + _FILE_ID_BOTH_DIRECTORY_INFO_NAME_OFFSET
        if name_length == 0 or name_length % 2 or name_length > len(data) - name_start:
            raise OSError("invalid Windows directory entry filename length")
        try:
            name = data[name_start : name_start + name_length].decode("utf-16-le", errors="strict")
        except UnicodeDecodeError as exc:
            raise OSError("invalid UTF-16 filename in Windows directory entry") from exc
        if name not in (".", ".."):
            names.append(name)

        if next_offset == 0:
            return names
        if (
            next_offset < _FILE_ID_BOTH_DIRECTORY_INFO_NAME_OFFSET + name_length
            or next_offset % 8
            or next_offset + _FILE_ID_BOTH_DIRECTORY_INFO_NAME_OFFSET > remaining
        ):
            raise OSError("invalid Windows directory entry offset")
        offset += next_offset


def _windows_directory_names(directory_fd: int) -> list[str]:
    """Enumerate names with GetFileInformationByHandleEx on a directory handle."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(directory_fd))  # type: ignore[attr-defined]
    buffer = ctypes.create_string_buffer(64 * 1024)
    names: list[str] = []
    info_class = _FILE_ID_BOTH_DIRECTORY_RESTART_INFO
    while True:
        if not kernel32.GetFileInformationByHandleEx(handle, info_class, buffer, len(buffer)):
            error = ctypes.get_last_error()  # type: ignore[attr-defined]
            if error == 18:  # ERROR_NO_MORE_FILES
                return names
            raise ctypes.WinError(error)  # type: ignore[attr-defined]
        info_class = _FILE_ID_BOTH_DIRECTORY_INFO
        page = ctypes.string_at(ctypes.addressof(buffer), len(buffer))
        names.extend(_parse_windows_directory_page(page))


def list_directory_names(directory_fd: int) -> list[str]:
    """List names from a pinned directory descriptor without path lookup."""
    if os.name == "nt":
        return _windows_directory_names(directory_fd)
    if os.listdir not in getattr(os, "supports_fd", set()):
        raise OSError("descriptor-based directory enumeration is unavailable")
    return os.listdir(directory_fd)
