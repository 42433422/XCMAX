import pytest

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
