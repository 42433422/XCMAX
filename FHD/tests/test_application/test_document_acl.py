"""文档级 ACL：入库、检索、状态与 ACL 更新的可见性约束。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dataset_rag.document_acl import (
    document_visible_to,
    normalize_document_acl,
)
from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService

_TEXT = "权限说明：本资料仅对指定成员开放。" * 20


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=lambda text: [float(len(text)), 1.0],
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx(actor: str, *, admin: bool = False) -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id=actor,
        tenant_id="t1",
        permissions=frozenset({"dataset.read", "dataset.write"}),
        is_admin=admin,
    )


def test_normalize_rejects_unknown_keys_and_bad_shapes() -> None:
    assert normalize_document_acl({"allow_actors": [" alice ", "alice"], "deny_actors": []}) == {
        "allow_actors": ["alice"]
    }
    with pytest.raises(ValueError, match="unsupported acl keys"):
        normalize_document_acl({"everyone": True})
    with pytest.raises(ValueError, match="must be a list"):
        normalize_document_acl({"allow_actors": "alice"})
    with pytest.raises(ValueError, match="too long"):
        normalize_document_acl({"allow_actors": ["x" * 200]})


def test_document_visible_to_semantics() -> None:
    metadata = {"acl": {"allow_actors": ["alice"], "deny_actors": ["mallory"]}}
    assert document_visible_to({}, _ctx("bob")) is True
    assert document_visible_to(metadata, _ctx("alice")) is True
    assert document_visible_to(metadata, _ctx("mallory")) is False
    assert document_visible_to(metadata, _ctx("bob")) is False
    assert document_visible_to(metadata, _ctx("bob", admin=True)) is True
    assert document_visible_to(metadata, None) is True


def test_restricted_document_is_hidden_from_other_actors(tmp_path) -> None:
    service = _service(tmp_path)
    result = service.ingest_document(
        dataset_id="kb",
        source="secret.md",
        text=_TEXT,
        tenant_id="t1",
        chunk_strategy="fixed",
        metadata={"acl": {"allow_actors": ["alice"]}},
        access_context=_ctx("alice"),
    )
    assert result["success"] is True

    alice = service.query(
        dataset_id="kb", query="权限说明", tenant_id="t1", access_context=_ctx("alice")
    )
    bob = service.query(
        dataset_id="kb", query="权限说明", tenant_id="t1", access_context=_ctx("bob")
    )
    admin = service.query(
        dataset_id="kb",
        query="权限说明",
        tenant_id="t1",
        access_context=_ctx("root", admin=True),
    )
    assert alice["chunks"] and not bob["chunks"] and admin["chunks"]

    bob_status = service.status("kb", access_context=_ctx("bob"))
    admin_status = service.status("kb", access_context=_ctx("root", admin=True))
    assert bob_status["document_count"] == 0
    assert admin_status["document_count"] == 1


def test_update_acl_changes_visibility_without_new_version(tmp_path) -> None:
    service = _service(tmp_path)
    ingested = service.ingest_document(
        dataset_id="kb",
        source="policy.md",
        text=_TEXT,
        tenant_id="t1",
        chunk_strategy="fixed",
        access_context=_ctx("alice"),
    )
    document_id = ingested["document"]["document_id"]
    version = ingested["document"]["version"]

    # 默认租户内可见
    assert service.query(
        dataset_id="kb", query="权限说明", tenant_id="t1", access_context=_ctx("bob")
    )["chunks"]

    updated = service.update_document_acl(
        "kb", document_id, acl={"deny_actors": ["bob"]}, access_context=_ctx("alice")
    )
    assert updated["success"] is True
    assert updated["document"]["version"] == version
    assert updated["acl"] == {"deny_actors": ["bob"]}
    assert not service.query(
        dataset_id="kb", query="权限说明", tenant_id="t1", access_context=_ctx("bob")
    )["chunks"]
    assert service.query(
        dataset_id="kb", query="权限说明", tenant_id="t1", access_context=_ctx("alice")
    )["chunks"]

    cleared = service.update_document_acl("kb", document_id, acl={}, access_context=_ctx("alice"))
    assert cleared["acl"] == {}
    assert service.query(
        dataset_id="kb", query="权限说明", tenant_id="t1", access_context=_ctx("bob")
    )["chunks"]


def test_update_acl_rejects_invalid_payload_and_missing_document(tmp_path) -> None:
    service = _service(tmp_path)
    ingested = service.ingest_document(
        dataset_id="kb",
        source="policy.md",
        text=_TEXT,
        tenant_id="t1",
        access_context=_ctx("alice"),
    )
    invalid = service.update_document_acl(
        "kb",
        ingested["document"]["document_id"],
        acl={"roles": ["admin"]},
        access_context=_ctx("alice"),
    )
    missing = service.update_document_acl(
        "kb", "doc_missing", acl={"deny_actors": ["bob"]}, access_context=_ctx("alice")
    )
    bad_ingest = service.ingest_document(
        dataset_id="kb",
        source="bad.md",
        text=_TEXT,
        tenant_id="t1",
        metadata={"acl": {"nope": []}},
        access_context=_ctx("alice"),
    )
    assert invalid["error_code"] == "dataset_acl_invalid"
    assert missing["error_code"] == "dataset_document_not_found"
    assert bad_ingest["error_code"] == "dataset_ingest_failed"


def test_acl_route_dispatches_governed_action() -> None:
    from app.fastapi_routes.knowledge.document_routes import DocumentRoutes

    calls: list[dict] = []

    def _dispatch(**kwargs):
        from fastapi.responses import JSONResponse

        calls.append(kwargs)
        return JSONResponse({"success": True})

    routes = DocumentRoutes(dispatch=lambda: _dispatch, uploads=lambda _get: None)
    app = FastAPI()
    app.include_router(routes.deletion)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/datasets/kb/documents/doc_1/acl", json={"acl": {"allow_actors": ["alice"]}}
    )
    rejected = client.post("/datasets/kb/documents/doc_1/acl", json={"acl": {"roles": []}})

    assert response.status_code == 200
    assert calls[0]["action"] == "update_document_acl"
    assert calls[0]["params"] == {
        "dataset_id": "kb",
        "document_id": "doc_1",
        "acl": {"allow_actors": ["alice"]},
    }
    assert rejected.status_code == 422
