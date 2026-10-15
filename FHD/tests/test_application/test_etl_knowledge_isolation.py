"""Knowledge ETL contracts use a real isolated dataset service and no network."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.application import dataset_rag_app_service as rag
from app.application.etl.errors import EtlError
from app.application.etl.targets.knowledge import KnowledgeAdapter
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def service(tmp_path, monkeypatch):
    svc = rag.DatasetRagApplicationService(
        embedder=lambda text: [1.0, 0.0],
        storage_path=tmp_path / "knowledge.json",
        allowed_roots=[tmp_path],
        rebuild_workers_enabled=False,
    )
    monkeypatch.setattr(rag, "get_dataset_rag_app_service", lambda: svc)
    return svc


def execute(content, run, **kwargs):
    return KnowledgeAdapter().execute_row(
        None,
        {"content": content, "source_key": "synthetic"},
        action=kwargs.pop("action", "new"),
        match_ref=kwargs.pop("match_ref", ""),
        allowed_update_fields={"content"},
        context={"owner_user_id": 1, "run_id": run, **kwargs},
    )


def documents(service, tenant):
    return service.status(dataset_id="office-docking", tenant_id=str(tenant))["documents"]


def test_identical_content_in_two_tenants_never_replaces_first(service):
    with tenant_scope(1):
        first = execute("shared synthetic content", "run-a")
    with tenant_scope(2):
        second = execute("shared synthetic content", "run-b")
    assert first["match_ref"] != second["match_ref"]
    assert len(documents(service, 1)) == len(documents(service, 2)) == 1


def test_replaying_one_import_preserves_version_and_receipt(service):
    with tenant_scope(1):
        first = execute("retry-safe synthetic content", "run-a")
        second = execute("retry-safe synthetic content", "run-a")
    assert second == first
    assert len(documents(service, 1)) == 1


def test_stale_new_preview_cannot_claim_another_runs_document(service):
    with tenant_scope(1):
        first = execute("shared synthetic content", "run-a")
        with pytest.raises(EtlError) as error:
            execute("shared synthetic content", "run-b")
    assert error.value.code == "ETL_PREVIEW_STALE"
    assert documents(service, 1)[0]["metadata"]["etl_run_id"] == "run-a"
    assert documents(service, 1)[0]["document_id"] == first["match_ref"]


def test_rollback_rejects_later_replacement_at_same_document_id(service):
    with tenant_scope(1):
        imported = execute("old synthetic content", "run-a")
        replacement = service.ingest_document(
            dataset_id="office-docking",
            document_id=imported["match_ref"],
            source="synthetic",
            text="later manual content",
            tenant_id="1",
        )
        assert replacement["success"] is True
        with pytest.raises(EtlError) as error:
            KnowledgeAdapter().rollback_row(
                None,
                match_ref=imported["match_ref"],
                before={},
                after=imported["after"],
                context={"owner_user_id": 1, "run_id": "run-a"},
            )
    assert error.value.code == "ETL_ROLLBACK_CONCURRENT_CHANGE"
    assert documents(service, 1)[0]["version"] == replacement["document"]["version"]


def test_source_update_then_rollback_restores_previous_content(service):
    with tenant_scope(1):
        first = execute("first synthetic version", "run-a")
        second = execute(
            "second synthetic version", "run-b", action="update", match_ref=first["match_ref"]
        )
        KnowledgeAdapter().rollback_row(
            None,
            match_ref=second["match_ref"],
            before=first["after"],
            after=second["after"],
            context={"owner_user_id": 1, "run_id": "run-b"},
        )
    assert [doc["document_id"] for doc in documents(service, 1)] == [first["match_ref"]]


@pytest.mark.parametrize("response", [{"success": False}, {}, {"success": True, "documents": {}}])
def test_inventory_failure_blocks_preview_instead_of_claiming_empty(response, monkeypatch):
    service = MagicMock()
    service.status.return_value = response
    monkeypatch.setattr(rag, "get_dataset_rag_app_service", lambda: service)
    with tenant_scope(1), pytest.raises(EtlError) as error:
        KnowledgeAdapter().preview(
            None, {"content": "synthetic"}, allowed_update_fields=set(), context={}
        )
    assert error.value.code == "ETL_KNOWLEDGE_STATUS_FAILED"
    service.ingest_document.assert_not_called()


def test_dataset_explicit_id_cannot_overwrite_a_different_tenant(service):
    service.ingest_document(
        dataset_id="office-docking", document_id="same-id", text="tenant one", tenant_id="1"
    )
    denied = service.ingest_document(
        dataset_id="office-docking", document_id="same-id", text="tenant two", tenant_id="2"
    )
    assert denied["success"] is False
    assert len(documents(service, 1)) == 1
    assert documents(service, 2) == []


def test_confirmed_source_version_cannot_change_before_execution(service):
    with tenant_scope(1):
        first = execute("first synthetic version", "run-a")
        old_preview = documents(service, 1)[0]
        service.ingest_document(
            dataset_id="office-docking",
            document_id=first["match_ref"],
            text="manual replacement",
            source="synthetic",
            tenant_id="1",
        )
        with pytest.raises(EtlError) as error:
            execute(
                "second synthetic version",
                "run-b",
                action="update",
                match_ref=first["match_ref"],
                preview_before=old_preview,
            )
    assert error.value.code == "ETL_PREVIEW_STALE"
    assert len(documents(service, 1)) == 1


def test_source_version_guard_is_atomic_with_ingest(service, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)
    split_text = service._split_text

    def synchronized_split(*args, **kwargs):
        chunks = split_text(*args, **kwargs)
        barrier.wait(timeout=3)
        return chunks

    monkeypatch.setattr(service, "_split_text", synchronized_split)

    def ingest(number):
        return service.ingest_document(
            dataset_id="office-docking",
            document_id=f"concurrent-{number}",
            text=f"synthetic version {number}",
            source="synthetic",
            tenant_id="1",
            idempotency_key=f"run-{number}",
            expected_source_version=0,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(ingest, [1, 2]))
    assert sum(result["success"] is True for result in results) == 1
    assert [result["error_code"] for result in results if not result["success"]] == [
        "dataset_source_version_conflict"
    ]
    assert len(documents(service, 1)) == 1


def test_idempotency_key_reuse_with_changed_payload_is_rejected(service):
    first = service.ingest_document(
        dataset_id="office-docking",
        document_id="idempotent",
        source="synthetic",
        text="original content",
        tenant_id="1",
        idempotency_key="same-key",
    )
    rejected = service.ingest_document(
        dataset_id="office-docking",
        document_id="idempotent",
        source="synthetic",
        text="changed content",
        tenant_id="1",
        idempotency_key="same-key",
    )
    assert rejected == {"success": False, "error_code": "dataset_document_conflict"}
    assert documents(service, 1)[0] == first["document"]
