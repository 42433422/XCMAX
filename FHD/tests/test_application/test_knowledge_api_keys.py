"""知识库外部只读 API Key 测试。

覆盖：
- 创建需 dataset.admin 且绑定创建者租户，原始 key 只返回一次
- 列表不回传密钥/哈希；回收后立即失效
- 公共查询只命中绑定数据集、按租户与文档 ACL 过滤，不返回答案/引用
- 无效或回收的 key 明确失败
- HTTP 路由：缺少或错误的 X-KB-Key 返回 401
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.dataset_rag.api_keys import DatasetApiKeyStore
from app.application.dataset_rag.models import DatasetAccessContext
from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.fastapi_routes import knowledge_public

_REFUND = "退货政策：签收后七天内可以申请无理由退货，审核通过后原路退回。" * 6
_INVOICE = "发票规则：支持开具电子发票，红冲需要提供原发票号码。" * 6


def test_key_verifiers_are_salted_and_keys_remain_bound_and_revocable(tmp_path):
    path = tmp_path / "keys.json"
    store = DatasetApiKeyStore(path)
    first = store.create(dataset_id="kb", tenant_id="tenant-a")
    second = store.create(dataset_id="kb", tenant_id="tenant-b")
    rows = json.loads(path.read_text())["datasets"]["kb"]
    assert all(row["key_hash"].startswith("pbkdf2:sha256:600000$") for row in rows)
    assert rows[0]["key_hash"].split("$")[1] != rows[1]["key_hash"].split("$")[1]
    assert first["key"] not in path.read_text() and second["key"] not in path.read_text()
    assert store.resolve(first["key"])["tenant_id"] == "tenant-a"
    assert store.resolve(second["key"])["tenant_id"] == "tenant-b"
    wrong = first["key"][:-1] + ("0" if first["key"][-1] != "0" else "1")
    assert store.resolve(wrong) is None
    assert store.revoke(dataset_id="kb", token_id=first["token_id"])
    assert store.resolve(first["key"]) is None
    assert all(row["requires_reissue"] is False for row in store.list(dataset_id="kb"))


@pytest.mark.parametrize("encoded", ["0" * 64, "plain$secret", "pbkdf2:sha256:1$salt$hash"])
def test_old_or_weak_verifiers_require_reissue_without_hash_work(tmp_path, monkeypatch, encoded):
    path = tmp_path / "keys.json"
    path.write_text(
        json.dumps(
            {
                "datasets": {
                    "kb": [
                        {
                            "token_id": "key_" + "a" * 16,
                            "key_hash": encoded,
                        }
                    ]
                }
            }
        )
    )
    verify = Mock(side_effect=AssertionError("weak verifier must not be evaluated"))
    monkeypatch.setattr("app.application.dataset_rag.api_keys.check_password_hash", verify)
    store = DatasetApiKeyStore(path)
    assert store.resolve("kb_" + "a" * 16 + "_" + "b" * 48) is None
    assert store.resolve("kb_" + "b" * 48) is None
    assert store.list(dataset_id="kb")[0]["requires_reissue"] is True
    verify.assert_not_called()


def test_key_validation_performs_at_most_one_expensive_hash(tmp_path, monkeypatch):
    row = {"token_id": "key_" + "a" * 16, "key_hash": "pbkdf2:sha256:600000$salt$hash"}
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"datasets": {"kb": [row] * 50, "other": [row] * 50}}))
    verify = Mock(return_value=False)
    monkeypatch.setattr("app.application.dataset_rag.api_keys.check_password_hash", verify)
    store = DatasetApiKeyStore(path)
    for invalid in ("kb_" + "a" * 100000, "kb_" + "c" * 16 + "_" + "b" * 48):
        assert store.resolve(invalid) is None
    verify.assert_not_called()
    assert store.resolve("kb_" + "a" * 16 + "_" + "b" * 48) is None
    verify.assert_called_once()


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=None,
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def _ctx(*, permissions: frozenset[str] | None = None, tenant: str = "t1") -> DatasetAccessContext:
    return DatasetAccessContext(
        actor_id="alice",
        tenant_id=tenant,
        permissions=(
            frozenset({"dataset.read", "dataset.write", "dataset.admin"})
            if permissions is None
            else permissions
        ),
        is_admin=False,
    )


def _seed(service: DatasetRagApplicationService, *, acl: dict | None = None) -> None:
    for dataset_id, text, source in (
        ("kb-refund", _REFUND, "退款.md"),
        ("kb-invoice", _INVOICE, "发票.md"),
    ):
        service.ingest_document(
            dataset_id=dataset_id,
            source=source,
            text=text,
            tenant_id="t1",
            chunk_strategy="fixed",
            metadata={"acl": acl} if acl else {},
            access_context=_ctx(),
        )


def test_api_key_scoped_to_dataset_tenant_and_redacted(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    created = service.create_api_key("kb-refund", label="网站检索", access_context=_ctx())
    listed = service.list_api_keys("kb-refund", access_context=_ctx())

    assert created["success"] is True and created["key"].startswith("kb_")
    assert listed["total"] == 1
    assert "key" not in listed["keys"][0] and "key_hash" not in listed["keys"][0]
    assert listed["keys"][0]["label"] == "网站检索"

    hit = service.public_query(api_key=created["key"], query="退货", top_k=3)
    assert hit["success"] is True and hit["dataset_id"] == "kb-refund"
    assert hit["answer"] == "" and "citations" not in hit
    assert hit["chunks"] and all("acl" not in (c.get("metadata") or {}) for c in hit["chunks"])

    revoked = service.revoke_api_key("kb-refund", created["token_id"], access_context=_ctx())
    assert revoked["revoked"] is True
    denied = service.public_query(api_key=created["key"], query="退货")
    assert denied["success"] is False
    assert denied["error_code"] == "knowledge_api_key_invalid"


def test_api_key_requires_admin_and_tenant(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service)
    denied = service.create_api_key(
        "kb-refund",
        access_context=_ctx(permissions=frozenset({"dataset.read", "dataset.write"})),
    )
    no_tenant = service.create_api_key(
        "kb-refund",
        access_context=DatasetAccessContext(
            actor_id="alice",
            tenant_id="",
            permissions=frozenset({"dataset.admin"}),
            is_admin=False,
        ),
    )

    assert denied["success"] is False
    assert denied["error_code"] == "dataset_permission_denied"
    assert no_tenant["success"] is False


def test_api_key_respects_document_acl_and_invalid_keys(tmp_path) -> None:
    service = _service(tmp_path)
    _seed(service, acl={"allow_actors": ["bob"]})
    created = service.create_api_key("kb-refund", access_context=_ctx())

    hidden = service.public_query(api_key=created["key"], query="退货")
    invalid = service.public_query(api_key="kb_not-a-real-key", query="退货")

    assert hidden["success"] is True and hidden["chunks"] == []
    assert invalid["success"] is False
    assert invalid["error_code"] == "knowledge_api_key_invalid"


def test_public_route_requires_valid_header(monkeypatch) -> None:
    calls: list[dict] = []

    class _Fake:
        def public_query(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "dataset_id": "kb-refund", "chunks": [], "answer": ""}

    monkeypatch.setattr(knowledge_public, "_service", lambda: _Fake())
    app = FastAPI()
    app.include_router(knowledge_public.router)
    client = TestClient(app)

    missing = client.post("/api/knowledge/v1/public/query", json={"query": "退货"})
    ok = client.post(
        "/api/knowledge/v1/public/query",
        json={"query": "退货", "top_k": 3},
        headers={"X-KB-Key": "kb_demo"},
    )

    assert missing.status_code == 401
    assert ok.status_code == 200 and ok.json()["dataset_id"] == "kb-refund"
    assert calls[0]["api_key"] == "kb_demo" and calls[0]["top_k"] == 3
