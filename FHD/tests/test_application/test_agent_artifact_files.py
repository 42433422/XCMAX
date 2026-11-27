import hashlib
import os
from contextlib import contextmanager

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


def test_content_address_cannot_be_rebound_by_replacing_bytes_and_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    receipt = store_spreadsheet("run-one", b"original")
    replacement = b"replaced"
    artifact_path("run-one", receipt["artifact_id"]).write_bytes(replacement)
    receipt["metadata"]["sha256"] = hashlib.sha256(replacement).hexdigest()
    with pytest.raises(ValueError, match="identity"):
        artifact_files.read_verified_run_file("run-one", receipt)


@pytest.mark.parametrize("field", ["run_id", "uri", "name", "mime_type"])
def test_spreadsheet_download_requires_consistent_receipt(tmp_path, monkeypatch, field):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    receipt = store_spreadsheet("run-one", b"original")
    if field == "run_id":
        receipt["metadata"][field] = "other-run"
    else:
        receipt[field] = {"uri": "/unrelated", "name": "result.csv", "mime_type": "text/csv"}[field]
    with pytest.raises(ValueError):
        artifact_files.read_verified_run_file("run-one", receipt)


def test_scoped_spreadsheet_retains_original_owner_and_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    receipt = store_spreadsheet("run-one", b"original", owner_user_id=71, tenant_id="7")
    assert receipt["metadata"] == {
        "run_id": "run-one",
        "owner_user_id": "71",
        "tenant_id": "7",
        "sha256": hashlib.sha256(b"original").hexdigest(),
        "size_bytes": 8,
    }


def _crash_during_artifact_publication(data_dir, after_publish):
    os.environ["XCAGI_DATA_DIR"] = data_dir
    original_writer = artifact_files._open_elt_output_under_root

    @contextmanager
    def crash_before_rename(*args, **kwargs):
        with original_writer(*args, **kwargs) as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
            os._exit(73)

    if not after_publish:
        artifact_files._open_elt_output_under_root = crash_before_rename
    artifact_files.store_spreadsheet("crashed-run", b"durable artifact")
    os._exit(73)


@pytest.mark.parametrize("after_publish", [False, True])
def test_artifact_publication_survives_writer_process_loss(
    tmp_path, monkeypatch, spawn_context, after_publish
):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    process = spawn_context.Process(
        target=_crash_during_artifact_publication, args=(str(tmp_path), after_publish)
    )
    process.start()
    process.join(30)
    try:
        assert process.exitcode == 73
    finally:
        if process.is_alive():
            process.kill()
            process.join(5)
        process.close()
    artifact_id = "xlsx_" + hashlib.sha256(b"durable artifact").hexdigest()[:32]
    assert artifact_path("crashed-run", artifact_id).exists() is after_publish
    receipt = store_spreadsheet("crashed-run", b"durable artifact")
    assert receipt["artifact_id"] == artifact_id
    assert artifact_files.read_verified_run_file("crashed-run", receipt) == b"durable artifact"
