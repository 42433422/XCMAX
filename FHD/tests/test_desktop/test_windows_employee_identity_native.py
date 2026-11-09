"""Real Windows identity-file boundary checks on disposable files.

No platform mocks, ACL changes, elevation, live data or network. Linux skips
are collection-only evidence, never Windows acceptance.
"""

import json
import os
import subprocess
import sys
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="requires real Windows kernel")


def _read(workspace):
    # Keep Linux collection independent of runtime imports, and exercise the real
    # production package on Windows without importing Unix-only task_continuity.
    from app.application.employee_runtime.handoff_identity import load_identity_card

    return load_identity_card(workspace, "clerk")


def _card(workspace):
    folder = workspace / "employees"
    folder.mkdir(parents=True)
    path = folder / "clerk.json"
    path.write_text(
        json.dumps(
            {
                "employee_id": "clerk",
                "tenant_id": "tenant-one",
                "available": True,
                "private_note": "do-not-project",
            }
        ),
        encoding="utf-8",
    )
    return path


@contextmanager
def _junction(path, target):
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(path), str(target)],
        check=True,
        capture_output=True,
    )
    try:
        yield
    finally:
        os.rmdir(path)  # Unlink this junction only; never recurse into its target.


def test_native_employee_identity_round_trip(tmp_path):
    _card(tmp_path)
    identity, error = _read(tmp_path)
    assert not error
    assert identity == {
        "employee_id": "clerk",
        "tenant_id": "tenant-one",
        "available": True,
        "timeout": False,
        "crash": False,
        "unrecoverable": False,
    }


def test_native_employee_identity_hardlink_is_refused(tmp_path):
    card = _card(tmp_path)
    alias = tmp_path / "linked-card.json"
    os.link(card, alias)
    assert _read(tmp_path) == (None, "handoff_identity_unverified")
    alias.unlink()
    assert _read(tmp_path)[0]["employee_id"] == "clerk"


def test_native_employee_identity_parent_junction_is_refused(tmp_path):
    actual = tmp_path / "actual"
    card = _card(actual)
    selected = tmp_path / "selected"
    selected.mkdir()
    with _junction(selected / "employees", card.parent):
        assert _read(selected) == (None, "handoff_identity_unverified")
    assert card.is_file()


def test_native_employee_identity_workspace_junction_is_refused(tmp_path):
    actual = tmp_path / "actual"
    card = _card(actual)
    with _junction(tmp_path / "selected", actual):
        assert _read(tmp_path / "selected") == (None, "handoff_identity_unverified")
    assert card.is_file()
