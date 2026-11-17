"""File ingestion deduplicates only inside the authoritative write boundary."""

import hashlib
import json

import pytest

from app.application.dataset_rag_app_service import DatasetRagApplicationService
from tests.test_application.test_dataset_rag_component_boundaries import _overlapping_ingests


def _service(tmp_path):
    return DatasetRagApplicationService(
        storage_path=tmp_path / "store.json",
        allowed_roots=[tmp_path],
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _file(tmp_path):
    path = tmp_path / "policy.txt"
    path.write_text("same policy content", encoding="utf-8")
    return str(path)


def test_same_file_is_idempotent_and_cas_is_not_bypassed(tmp_path):
    svc = _service(tmp_path)
    request = {"dataset_id": "files", "file_path": _file(tmp_path)}
    first = svc.ingest_document(**request)
    duplicate = svc.ingest_document(**request, expected_source_version=1)
    assert first["success"] and duplicate["duplicate"]
    assert duplicate["document"] == first["document"]
    assert svc.ingest_document(**request, expected_source_version=0) == {
        "success": False,
        "error_code": "dataset_source_version_conflict",
    }
    assert svc.status("files")["document_count"] == 1


@pytest.mark.parametrize(
    "override",
    [
        {"tenant_id": "other"},
        {"source": "other-source"},
        {"version": 2},
        {"document_id": "explicit"},
        {"text": "same policy content"},
    ],
)
def test_file_dedup_preserves_tenant_source_explicit_and_inline_semantics(tmp_path, override):
    svc = _service(tmp_path)
    request = {"dataset_id": "files", "file_path": _file(tmp_path)}
    first = svc.ingest_document(**request)
    second = svc.ingest_document(**request, **override)
    assert first["success"] and second["success"]
    assert not second.get("duplicate")
    assert first["document"]["document_id"] != second["document"]["document_id"]


@pytest.mark.parametrize("cas", [False, True])
def test_file_dedup_rechecks_after_concurrent_embedding(tmp_path, monkeypatch, cas):
    # Parser is synthetic; the helper uses two independent durable repository instances.
    from app.application.dataset_rag.document_parser import DocumentParser

    monkeypatch.setattr(DocumentParser, "_resolve_file_path", lambda self, path: tmp_path / path)
    monkeypatch.setattr(
        DocumentParser, "_extract_file_text", lambda self, path: ("same", "text", {})
    )
    request = {"file_path": "policy.txt"}
    first, second, status = _overlapping_ingests(
        tmp_path,
        slow_request={**request, **({"expected_source_version": 0} if cas else {})},
        concurrent_request=request,
    )
    assert first["success"]
    if cas:
        assert second == {"success": False, "error_code": "dataset_source_version_conflict"}
    else:
        assert second["duplicate"] and second["document"] == first["document"]
    assert status["document_count"] == 1


@pytest.mark.parametrize("file_input", [False, True])
def test_pre_hash_snapshot_keeps_idempotent_retry_contract(tmp_path, monkeypatch, file_input):
    from app.application.dataset_rag.document_parser import DocumentParser

    content = "same policy content"
    monkeypatch.setattr(
        DocumentParser, "_extract_file_text", lambda self, path: (content, "text", {})
    )
    request = {
        "dataset_id": "files",
        "source": "policy",
        "document_id": "record",
        "tenant_id": "tenant-a",
        "idempotency_key": "original-request",
        "metadata": {"category": "policy"},
        **({"file_path": _file(tmp_path)} if file_input else {"text": content}),
    }
    assert _service(tmp_path).ingest_document(**request)["success"]
    # Persist the exact pre-upgrade fingerprint contract and metadata shape.
    metadata = {"category": "policy", "tenant_id": "tenant-a"}
    if file_input:
        metadata["file_path"] = request["file_path"]
    old_fingerprint = hashlib.sha256(
        json.dumps(
            ["tenant-a", "policy", content, metadata, "semantic", 500, 50],
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    storage = tmp_path / "store.json"
    snapshot = json.loads(storage.read_text())
    document = snapshot["datasets"]["files"]["documents"]["record"]
    document["metadata"].pop("document_content_hash")
    document["metadata"]["ingest_fingerprint"] = old_fingerprint
    storage.write_text(json.dumps(snapshot), encoding="utf-8")
    before = storage.read_bytes()
    svc = _service(tmp_path)
    replay = svc.ingest_document(**request)
    assert replay["success"] and replay["document"] == document
    assert storage.read_bytes() == before
    for changed in ({"text": "changed"}, {"idempotency_key": "different"}, {"tenant_id": "other"}):
        assert svc.ingest_document(**{**request, **changed}) == {
            "success": False,
            "error_code": "dataset_document_conflict",
        }


def test_file_restoring_historical_content_creates_a_new_latest_version(tmp_path):
    svc = _service(tmp_path)
    path = tmp_path / "policy.txt"
    request = {"dataset_id": "files", "file_path": str(path)}
    documents = []
    for content in ("policy A", "policy B", "policy A"):
        path.write_text(content, encoding="utf-8")
        result = svc.ingest_document(**request)
        assert result["success"] and not result.get("duplicate")
        documents.append(result["document"])
    assert [doc["version"] for doc in documents] == [1, 2, 3]
    assert svc.ingest_document(**request)["document"] == documents[-1]
    diff = svc.diff_versions(dataset_id="files", source="policy.txt", from_version=1)
    assert diff["success"] and not diff["changed"] and diff["to_version"] == 3
    # Removing the latest A must not resurrect the older A through deduplication.
    assert svc.delete_document("files", documents[-1]["document_id"])["success"]
    replacement = svc.ingest_document(**request)
    assert replacement["success"] and not replacement.get("duplicate")
    assert replacement["document"]["version"] == 3
    assert replacement["document"]["document_id"] != documents[0]["document_id"]
