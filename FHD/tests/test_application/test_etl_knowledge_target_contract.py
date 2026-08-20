from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.application.etl.errors import EtlError
from app.application.etl.targets import knowledge


def test_knowledge_validation_hash_and_source_fallbacks() -> None:
    adapter = knowledge.KnowledgeAdapter()
    assert adapter.validate({})[0]["code"] == "ETL_KNOWLEDGE_CONTENT_REQUIRED"
    assert adapter.validate({"content": "x"}) == []
    assert (
        adapter._content_hash({"content": "正文"}, {})
        == hashlib.sha256("正文".encode()).hexdigest()
    )
    assert adapter._content_hash({}, {"file_sha256": "sha"}) == "sha"
    assert adapter._source_label({"source_key": "s"}, {}) == "s"
    assert adapter._source_label({}, {"file_name": "a.pdf"}) == "a.pdf"
    assert adapter._source_label({}, {}) == "etl-import"


def test_documents_status_cache_success_and_shape_fallbacks() -> None:
    adapter = knowledge.KnowledgeAdapter()
    service = MagicMock()
    service.status.return_value = {"success": True, "documents": [{"document_id": "d"}]}
    context = {"owner_user_id": 3}
    with (
        patch.object(knowledge, "tenant_id_for_write", return_value=7),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        assert adapter._documents(context) == [{"document_id": "d"}]
        assert adapter._documents(context) == [{"document_id": "d"}]
    service.status.assert_called_once()

    for response in ({"success": False, "documents": [{}]}, {"success": True, "documents": {}}):
        service = MagicMock()
        service.status.return_value = response
        with (
            patch.object(knowledge, "tenant_id_for_write", return_value=8),
            patch(
                "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
                return_value=service,
            ),
        ):
            assert adapter._documents({}) == []


def test_preview_validation_duplicate_and_source_replacement_decisions() -> None:
    adapter = knowledge.KnowledgeAdapter()
    with patch.object(knowledge, "is_uploaded_document_path", return_value=False):
        decision = adapter.preview(
            None,
            {"document_path": "/outside/file.pdf"},
            allowed_update_fields=set(),
            context={},
        )
    assert decision.action == "error"
    assert {item["code"] for item in decision.issues or []} == {"ETL_DOCUMENT_PATH_FORBIDDEN"}

    digest = hashlib.sha256(b"same").hexdigest()
    duplicate = {"document_id": "d1", "metadata": {"content_hash": digest}}
    with patch.object(adapter, "_documents", return_value=[duplicate]):
        decision = adapter.preview(
            None,
            {"content": "same"},
            allowed_update_fields=set(),
            context={},
        )
    assert decision.action == "skip" and decision.match_ref == "d1"
    assert decision.reason == "duplicate_content_hash"

    versions = [
        {"document_id": "v1", "source": "sheet", "version": 1},
        {"document_id": "v3", "source": "sheet", "version": 3},
        {"document_id": "other", "source": "other", "version": 9},
    ]
    with patch.object(adapter, "_documents", return_value=versions):
        skipped = adapter.preview(
            None,
            {"content": "new", "source_key": "sheet"},
            allowed_update_fields=set(),
            context={},
        )
        updated = adapter.preview(
            None,
            {"content": "new", "source_key": "sheet"},
            allowed_update_fields={"content"},
            context={},
        )
    assert skipped.action == "skip" and skipped.match_ref == "v3"
    assert updated.action == "update" and updated.match_ref == "v3"
    assert updated.after and updated.after["source_key"] == "sheet"

    with patch.object(adapter, "_documents", return_value=[]):
        created = adapter.preview(
            None,
            {"content": "brand new"},
            allowed_update_fields=set(),
            context={"file_name": "upload.txt"},
        )
    assert created.action == "new"
    assert created.after and created.after["source_key"] == "upload.txt"


def test_execute_row_rejects_untrusted_path_and_handles_service_results() -> None:
    adapter = knowledge.KnowledgeAdapter()
    with patch.object(knowledge, "is_uploaded_document_path", return_value=False):
        with pytest.raises(EtlError):
            adapter.execute_row(
                None,
                {"document_path": "/outside/file.pdf"},
                action="new",
                match_ref="",
                allowed_update_fields=set(),
                context={},
            )

    service = MagicMock()
    service.ingest_document.return_value = {"success": False}
    patches = (
        patch.object(knowledge, "tenant_id_for_write", return_value=7),
        patch.object(knowledge, "is_uploaded_document_path", return_value=True),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    )
    with patches[0], patches[1], patches[2], pytest.raises(EtlError):
        adapter.execute_row(
            None,
            {"content": "正文", "source_key": "s"},
            action="new",
            match_ref="",
            allowed_update_fields=set(),
            context={"owner_user_id": 9, "run_id": "r"},
        )

    service.ingest_document.return_value = {"success": True, "document": {"version": 2}}
    with (
        patch.object(knowledge, "tenant_id_for_write", return_value=7),
        patch.object(knowledge, "is_uploaded_document_path", return_value=True),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        result = adapter.execute_row(
            None,
            {"document_path": "/upload/file.pdf", "source_key": "s"},
            action="update",
            match_ref="old",
            allowed_update_fields={"document_path"},
            context={"file_sha256": "abcdef", "owner_user_id": 9, "run_id": "r"},
        )
    assert result["match_ref"] == "etl-abcdef"
    assert result["after"]["version"] == 2
    kwargs = service.ingest_document.call_args.kwargs
    assert kwargs["tenant_id"] == "7" and kwargs["metadata"]["etl_run_id"] == "r"


def test_rollback_row_success_and_failure() -> None:
    adapter = knowledge.KnowledgeAdapter()
    service = SimpleNamespace(delete_document=MagicMock(return_value={"success": True}))
    with (
        patch.object(knowledge, "tenant_id_for_write", return_value=7),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
    ):
        assert (
            adapter.rollback_row(
                None,
                match_ref="d1",
                before={},
                after={},
                context={"owner_user_id": 9},
            )
            is None
        )

    service.delete_document.return_value = {"success": False}
    with (
        patch.object(knowledge, "tenant_id_for_write", return_value=7),
        patch(
            "app.application.dataset_rag_app_service.get_dataset_rag_app_service",
            return_value=service,
        ),
        pytest.raises(EtlError),
    ):
        adapter.rollback_row(
            None,
            match_ref="d1",
            before={},
            after={},
            context={},
        )
