"""Portable contracts with fake native observations, NOT Windows acceptance."""

from pathlib import PureWindowsPath
from types import SimpleNamespace

import pytest

from app.desktop_runtime import windows_catalog_files as files


@pytest.mark.parametrize(
    "path",
    [
        "relative.sqlite",
        r"C:relative.sqlite",
        r"\\server\share\db.sqlite",
        r"\\?\C:\db.sqlite",
        "C:/db.sqlite",
        r"C:\a\..\db.sqlite",
        r"C:\a\.\db.sqlite",
        r"C:\a\\db.sqlite",
        r"C:\db.sqlite:stream",
        r"C:\NUL.sqlite",
        r"C:\COM1",
        r"C:\a.\db.sqlite",
        r"C:\a \db.sqlite",
        "C:\\a\x00.sqlite",
        "C:\\a\n.sqlite",
    ],
)
def test_path_aliases_are_rejected_without_native_io(path):
    with pytest.raises(ValueError):
        files._local_path(path)


class Observations:
    def __init__(self, failure=None):
        self.calls, self.failure = [], failure

    def require_local_drive(self, target):
        self.calls.append(("drive", str(target)))

    def pin(self, path, *, directory):
        self.calls.append(("pin", str(path), directory))
        if path == self.failure:
            raise files.WindowsCatalogUnsupported("injected identity mismatch")
        return files.FileObservation(path, 7, len(self.calls))

    def inspect_sidecar(self, path):
        self.calls.append(("snapshot-only", str(path)))
        if path == self.failure:
            raise PermissionError("denied sidecar is not absence")
        return None

    def recheck(self):
        self.calls.append(("native-handle-recheck",))


def test_parent_order_sidecar_snapshots_and_recheck_contract():
    api = Observations()
    target = PureWindowsPath(r"C:\owner\catalog.sqlite")
    snapshot = files._observe_family(api, target)
    assert api.calls[1:4] == [
        ("pin", "C:\\", True),
        ("pin", r"C:\owner", True),
        ("pin", str(target), False),
    ]
    assert snapshot.main.path == target
    assert snapshot.sidecars == (("-wal", None), ("-shm", None), ("-journal", None))
    assert [call[0] for call in api.calls[4:]] == ["snapshot-only"] * 3 + [
        "native-handle-recheck"
    ]
    snapshot.recheck_main_and_ancestors()
    assert api.calls[-1] == ("native-handle-recheck",)


@pytest.mark.parametrize("failure", [r"C:\owner", r"C:\owner\catalog.sqlite-shm"])
def test_failed_boundary_does_not_return_a_successful_snapshot(failure):
    api = Observations(PureWindowsPath(failure))
    with pytest.raises((files.WindowsCatalogUnsupported, PermissionError)):
        files._observe_family(api, PureWindowsPath(r"C:\owner\catalog.sqlite"))


@pytest.mark.parametrize("error_type", [files.WindowsCatalogUnsupported, KeyboardInterrupt])
def test_native_open_requests_mutable_data_sharing_and_closes_on_validation_failure(error_type):
    calls = []
    native = files._NativeFiles.__new__(files._NativeFiles)
    native.active = True
    native.kernel = SimpleNamespace(CreateFileW=lambda *args: calls.append(args) or 41)
    native._close = lambda handle: calls.append(("close", handle))

    def rejected(*args):
        raise error_type("injected reparse rejection")

    native._identity = rejected
    with pytest.raises(error_type):
        native._open(PureWindowsPath(r"C:\db.sqlite"), False)
    assert calls == [
        (r"\\?\C:\db.sqlite", 0x80, 3, None, 3, 0x02200000, None),
        ("close", 41),
    ]


def test_sidecar_snapshot_shares_delete_and_closes_handle():
    native = files._NativeFiles.__new__(files._NativeFiles)
    calls, identity = [], object()
    native._open = lambda *a, **kw: calls.append(kw) or (41, identity)
    native._close = lambda handle: calls.append(handle)
    assert native.inspect_sidecar(PureWindowsPath(r"C:\db.sqlite-wal")) is identity
    assert calls == [{"share_delete": True}, 41]


def test_recheck_uses_original_held_handle_not_a_path_reopen():
    native = files._NativeFiles.__new__(files._NativeFiles)
    identity = files.FileObservation(PureWindowsPath(r"C:\db.sqlite"), 7, 9)
    native.active, native.held = True, [(41, identity, False)]
    calls = []
    native._identity = lambda *args: calls.append(args) or identity
    native.recheck()
    assert calls == [(41, identity.path, False)]
    native._identity = lambda *args: files.FileObservation(identity.path, 7, 10)
    with pytest.raises(files.WindowsCatalogUnsupported, match="identity changed"):
        native.recheck()
    native.active = False
    with pytest.raises(files.WindowsCatalogUnsupported, match="scope is closed"):
        native.recheck()


def test_json_request_is_lossless_and_distinguishes_create_from_compare_swap():
    first = files.prepare_json_publication(
        r"C:\owner\catalog.json", {"b": 2, "a": "值"}
    )
    again = files.prepare_json_publication(
        str(first.target), {"a": "值", "b": 2}, expected_previous_sha256=first.sha256
    )
    assert first.payload == again.payload == '{"a":"值","b":2}'.encode()
    assert first.expected_previous_sha256 is None
    assert again.expected_previous_sha256 == first.sha256


@pytest.mark.parametrize(
    "value,digest",
    [
        ([], None),
        ({1: "non-string-key"}, None),
        ({"x": (1, 2)}, None),
        ({"x": float("nan")}, None),
        ({}, "A" * 64),
        ({}, False),
    ],
)
def test_invalid_publication_request_is_rejected(value, digest):
    with pytest.raises(ValueError):
        files.prepare_json_publication(
            r"C:\owner\catalog.json", value, expected_previous_sha256=digest
        )


def test_publication_is_unavailable_before_any_native_or_file_open(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unimplemented publication attempted filesystem/native access")

    monkeypatch.setattr(files, "_NativeFiles", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr("os.open", forbidden)
    with pytest.raises(files.WindowsCatalogUnsupported, match="no write attempted"):
        files.publish_catalog_json(r"C:\owner\catalog.json", {"head": "untrusted"})
