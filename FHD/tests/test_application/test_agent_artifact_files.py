import os

import pytest

from app.application.agent_orchestrator import artifact_files
from app.application.agent_orchestrator.artifact_files import (
    artifact_path,
    store_spreadsheet,
    verified_spreadsheet_path,
)


def test_artifacts_are_run_scoped_idempotent_and_verified(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    receipt = store_spreadsheet("run-one", b"fixture-content")
    assert store_spreadsheet("run-one", b"fixture-content") == receipt
    assert verified_spreadsheet_path("run-one", receipt).read_bytes() == b"fixture-content"
    if os.name != "nt":
        assert artifact_path("run-one", receipt["artifact_id"]).stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileNotFoundError):
        verified_spreadsheet_path("run-two", receipt)
    artifact_path("run-one", receipt["artifact_id"]).write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksum"):
        verified_spreadsheet_path("run-one", receipt)


@pytest.mark.parametrize("run_id", ["../outside", "/tmp/outside", "run/other", ""])
def test_artifact_identity_cannot_escape_storage(tmp_path, monkeypatch, run_id):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        store_spreadsheet(run_id, b"fixture")


@pytest.mark.parametrize("operation", ["read", "write"])
def test_artifact_parent_swap_cannot_redirect_io(tmp_path, monkeypatch, operation):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path / "data"))
    receipt = store_spreadsheet("run-one", b"fixture")
    original = artifact_path("run-one", receipt["artifact_id"])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / original.name).write_bytes(b"private data")
    resolver = artifact_files.artifact_path

    def swapped(run_id, artifact_id):
        result = resolver(run_id, artifact_id)
        result.parent.rename(result.parent.with_name("previous"))
        result.parent.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(artifact_files, "artifact_path", swapped)
    with pytest.raises((ValueError, OSError)):
        if operation == "read":
            artifact_files.read_verified_run_file("run-one", receipt)
        else:
            store_spreadsheet("run-one", b"another file")
    assert list(outside.iterdir()) == [outside / original.name]
    assert (outside / original.name).read_bytes() == b"private data"
