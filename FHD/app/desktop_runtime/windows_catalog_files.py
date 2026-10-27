"""Dormant Windows catalog inspection, NOT source admission or writer fencing.

Main/ancestor handles deny rename/deletion but allow SQLite writes. Sidecars are
short-lived observations: holding their handles would interfere with SQLite's
cleanup, and absence is not a promise that another writer cannot create one.
No production caller uses this module. Durable JSON publication remains refused.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import re
import sys
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import PureWindowsPath


class WindowsCatalogUnsupported(RuntimeError):
    pass


def _local_path(value):
    if not isinstance(value, str) or not re.match(r"^[A-Za-z]:\\", value):
        raise ValueError("absolute local Windows path required")
    path = PureWindowsPath(value)
    if str(path) != value or any(
        part in {".", ".."}
        or part.endswith((" ", "."))
        or any(ord(char) < 32 or char in ':"<>|?*' for char in part)
        or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\..*)?", part)
        for part in path.parts[1:]
    ):
        raise ValueError("unsupported Windows path alias")
    return path


@dataclass(frozen=True)
class FileObservation:
    path: PureWindowsPath
    volume: int
    file_id: int


@dataclass(frozen=True)
class SqliteFamilySnapshot:
    main: FileObservation
    # None means absent at this probe only; no sidecar handle is retained.
    sidecars: tuple[tuple[str, FileObservation | None], ...]
    _pins: object

    def recheck_main_and_ancestors(self):
        """Re-read held native handles; does not revalidate sidecars or content."""
        self._pins.recheck()


class _FileInfo(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32),
        ("times", ctypes.c_uint32 * 6),
        ("volume", ctypes.c_uint32),
        ("size", ctypes.c_uint32 * 2),
        ("links", ctypes.c_uint32),
        ("index_high", ctypes.c_uint32),
        ("index_low", ctypes.c_uint32),
    ]


class _NativeFiles:
    def __init__(self):
        if sys.platform != "win32":
            raise WindowsCatalogUnsupported("requires the real Windows kernel")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateFileW": (
                ctypes.c_void_p,
                [
                    ctypes.c_wchar_p,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_void_p,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_void_p,
                ],
            ),
            "GetFileInformationByHandle": (
                ctypes.c_int,
                [ctypes.c_void_p, ctypes.POINTER(_FileInfo)],
            ),
            "GetFinalPathNameByHandleW": (
                ctypes.c_uint32,
                [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32],
            ),
            "GetDriveTypeW": (ctypes.c_uint32, [ctypes.c_wchar_p]),
            "CloseHandle": (ctypes.c_int, [ctypes.c_void_p]),
        }
        for name, (result, arguments) in signatures.items():
            function = getattr(self.kernel, name)
            function.restype, function.argtypes = result, arguments
        self.stack, self.held, self.active = ExitStack(), [], False

    def __enter__(self):
        self.active = True
        return self

    def __exit__(self, *args):
        self.active = False
        return self.stack.__exit__(*args)

    @staticmethod
    def _require(value):
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())
        return value

    def require_local_drive(self, target):
        if self.kernel.GetDriveTypeW(target.anchor) != 3:  # DRIVE_FIXED only.
            raise WindowsCatalogUnsupported("fixed local drive required for this probe")

    def _identity(self, handle, path, directory):
        info = _FileInfo()
        self._require(
            self.kernel.GetFileInformationByHandle(handle, ctypes.byref(info))
        )
        buffer = ctypes.create_unicode_buffer(32768)
        size = self.kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not size or size >= len(buffer) or not buffer.value.startswith("\\\\?\\"):
            raise WindowsCatalogUnsupported("native canonical path unavailable")
        actual = _local_path(buffer.value[4:])
        file_id = (info.index_high << 32) | info.index_low
        if (
            actual != path
            or info.attributes & 0x400
            or bool(info.attributes & 0x10) != directory
            or (not directory and info.links != 1)
            or not file_id
        ):
            raise WindowsCatalogUnsupported(
                "reparse, alias, hardlink or native identity refused"
            )
        return FileObservation(actual, info.volume, file_id)

    def _close(self, handle):
        self._require(self.kernel.CloseHandle(handle))

    def _open(self, path, directory, *, share_delete=False):
        if not self.active:
            raise WindowsCatalogUnsupported("native observation scope is closed")
        # READ_ATTRIBUTES; SHARE_READ | SHARE_WRITE; only sidecar probes share DELETE.
        # This is NOT an immutable bundle pin and does not exclude content writers.
        handle = self.kernel.CreateFileW(
            "\\\\?\\" + str(path),
            0x80,
            7 if share_delete else 3,
            None,
            3,
            0x02200000,
            None,
        )  # OPEN_EXISTING; OPEN_REPARSE_POINT | BACKUP_SEMANTICS.
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        with ExitStack() as rollback:
            rollback.callback(self._close, handle)
            identity = self._identity(handle, path, directory)
            rollback.pop_all()
            return handle, identity

    def pin(self, path, *, directory):
        handle, identity = self._open(path, directory)
        self.stack.callback(self._close, handle)
        self.held.append((handle, identity, directory))
        return identity

    def inspect_sidecar(self, path):
        try:
            handle, identity = self._open(path, False, share_delete=True)
        except OSError as error:
            if getattr(error, "winerror", None) == 2:  # Never denied/unknown parent.
                return None
            raise
        try:
            return identity
        finally:
            self._close(handle)

    def recheck(self):
        if not self.active:
            raise WindowsCatalogUnsupported("native observation scope is closed")
        for handle, original, directory in self.held:
            if self._identity(handle, original.path, directory) != original:
                raise WindowsCatalogUnsupported("held native identity changed")


def _observe_family(api, target):
    """Private injected test seam; never an execution capability or enrollment."""
    api.require_local_drive(target)
    for parent in reversed(target.parents):
        api.pin(parent, directory=True)
    main = api.pin(target, directory=False)
    sidecars = tuple(
        (suffix, api.inspect_sidecar(PureWindowsPath(str(target) + suffix)))
        for suffix in ("-wal", "-shm", "-journal")
    )
    api.recheck()
    return SqliteFamilySnapshot(main, sidecars, api)


@contextmanager
def observe_sqlite_family(target: str):
    """Hold main/ancestor native observations; no SQL connection is authorized.

    Each ancestor is opened and checked by handle, not only by lexical path.
    This does not prove SQLite uses that file or make sidecar/namespace snapshots
    race-proof. It does not fence another principal, process or pre-opened handle.
    """
    target = _local_path(target)
    with _NativeFiles() as api:
        yield _observe_family(api, target)
        api.recheck()


@dataclass(frozen=True)
class JsonPublicationRequest:
    target: PureWindowsPath
    payload: bytes
    sha256: str
    expected_previous_sha256: str | None  # None requires atomic no-clobber creation.


def prepare_json_publication(
    target: str, value: dict, *, expected_previous_sha256=None
):
    """Pure request encoding only; not a publication, receipt or durable proof."""
    target = _local_path(target)
    if not isinstance(value, dict) or (
        expected_previous_sha256 is not None
        and (
            not isinstance(expected_previous_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_previous_sha256)
        )
    ):
        raise ValueError("JSON object and original publication digest required")
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(payload) > 128 * 1024 * 1024 or json.loads(payload) != value:
        raise ValueError("bounded lossless JSON object required")
    return JsonPublicationRequest(
        target, payload, hashlib.sha256(payload).hexdigest(), expected_previous_sha256
    )


def publish_catalog_json(target: str, value: dict, *, expected_previous_sha256=None):
    """Always refuse before any filesystem access; Windows durability is unproven.

    Future implementation requires native atomic no-clobber/CAS publication and
    durable namespace acknowledgement. File flush or os.replace alone is not that
    contract. Callers must not turn this refusal into OPEN or an effect receipt.
    """
    prepare_json_publication(
        target, value, expected_previous_sha256=expected_previous_sha256
    )
    raise WindowsCatalogUnsupported(
        "native durable JSON publication unavailable; no write attempted"
    )
