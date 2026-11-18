"""AIOPEN 待验证删除接口：最小测试数据下的真实存储状态验证。

为什么用服务层/仓储层而不是 HTTP 调用：
7 个删除接口的 HTTP 层都只是鉴权 + 参数转发（``/api/excel/templates`` 薄层、
knowledge 的 dispatch、``/api/memory/v2`` 的 agent 路由、``/api/mods`` 的
uninstall 路由、``/api/products/delete`` 的 Agent 提交）。删除动作最终都落在
下面测试直接调用的函数上，且路由层不改变删除语义；直接调用可以避开会话、
审批桥、MobilePrincipal 等与「最终对数据做了什么」无关的依赖。群聊接口额外
跳过 ``require_deletion_allowed``（仅做有无 OpenIM 的开关判断），删除本体仍是
``GroupCatalog.delete_group``。

每个用例都断言最终存储状态，而不是 HTTP 200。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.group_chat.catalog import GroupCatalog
from app.application.group_chat.protocols import DirectoryActions, GroupStore, MessageStore
from app.application.group_chat.storage import GroupChatRepository

TENANT_ID = 1

# Python 3.12 弃用了 sqlite3 内置 datetime 适配器；生产代码把 datetime 交给
# 参数化 SQL，测试内按官方建议注册显式适配器，避免 DeprecationWarning 被当成错误。
sqlite3.register_adapter(datetime, lambda value: value.isoformat(" "))


@pytest.fixture()
def sqlite_db():
    """内存 SQLite：关闭外键并 patch 进程级 SessionLocal。"""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _disable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    import app.db.models
    from app.db.db_base import Base

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with patch("app.db.session.SessionLocal", factory):
        yield factory, engine


def _fresh_memory_service(tmp_path: Path, monkeypatch):
    """把单例用户记忆服务指向 tmp_path，返回可用实例。"""
    from app.domain.shared_services.user_memory_service import (
        UserMemoryService,
        reset_user_memory_service,
    )

    monkeypatch.setenv("XCAGI_USER_MEMORY_DIR", str(tmp_path))
    monkeypatch.delenv("XCAGI_USER_MEMORY_JSON_PATH", raising=False)
    reset_user_memory_service()
    return UserMemoryService()


def test_excel_template_delete_is_soft_delete(sqlite_db):
    """DELETE /api/excel/templates/{id} → is_active=0，行仍在，并写使用日志。"""
    from app.application.excel_template_http_app_service import delete_template
    from app.infrastructure.tenant_scope import tenant_scope

    factory, engine = sqlite_db
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_name TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    tenant_id INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE template_usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO templates (id, template_name, is_active, tenant_id) VALUES (1, 'T', 1, :tid)"
            ),
            {"tid": TENANT_ID},
        )

    with tenant_scope(TENANT_ID):
        response = delete_template(1)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["success"] is True

    with engine.connect() as conn:
        row = conn.execute(text("SELECT is_active FROM templates WHERE id = 1")).first()
        assert row is not None, "模板行不应被物理删除"
        assert row[0] == 0, "删除必须表现为 is_active=0"

        log = conn.execute(
            text("SELECT action, result FROM template_usage_log WHERE template_id = 1")
        ).first()
        assert log is not None and log[0] == "delete"


def test_knowledge_document_delete_removes_document_and_chunks(tmp_path):
    """DELETE .../documents/{id} → 文档与分块从状态和持久化 JSON 中硬删除。"""
    from app.application.dataset_rag_app_service import (
        DATASET_READ_PERMISSION,
        DATASET_WRITE_PERMISSION,
        DatasetAccessContext,
        DatasetRagApplicationService,
    )

    store = tmp_path / "datasets.json"
    service = DatasetRagApplicationService(
        storage_path=store,
        embedder=lambda value: [float(len(value) % 11), 1.0],
        vector_index_backend_name="memory",
        rebuild_workers_enabled=False,
    )
    ctx = DatasetAccessContext(
        actor_id="u1",
        tenant_id=str(TENANT_ID),
        permissions=frozenset({DATASET_READ_PERMISSION, DATASET_WRITE_PERMISSION}),
    )
    ingested = service.ingest_document(
        dataset_id="kb1",
        source="delete-me.txt",
        text="合同条款需要被删除。" * 20,
        chunk_strategy="fixed",
        chunk_size=50,
        chunk_overlap=0,
        tenant_id=str(TENANT_ID),
        access_context=ctx,
    )
    assert ingested["success"] is True
    document_id = ingested["document"]["document_id"]
    chunk_count = ingested["chunk_count"]
    assert chunk_count >= 1

    deleted = service.delete_document("kb1", document_id, access_context=ctx)
    assert deleted["success"] is True
    assert deleted["deleted_chunks"] == chunk_count

    status = service.status("kb1", tenant_id=str(TENANT_ID), access_context=ctx)
    assert status.get("success") is True
    assert [d for d in status.get("documents") or [] if d.get("document_id") == document_id] == []

    raw = json.loads(store.read_text(encoding="utf-8"))
    dataset = raw["datasets"]["kb1"]
    assert document_id not in dataset["documents"]
    assert all(
        (chunk.get("metadata") or {}).get("document_id") != document_id
        for chunk in dataset["chunks"]
    )


def test_knowledge_memory_delete_is_soft_status(tmp_path, monkeypatch):
    """DELETE .../memories/{id} → 记录保留，status=deleted 且写入 deleted_at。"""
    from app.application.dataset_rag_app_service import (
        DATASET_READ_PERMISSION,
        DATASET_WRITE_PERMISSION,
        DatasetAccessContext,
    )
    from app.application.persy_memory_app_service import PersyMemoryApplicationService
    from app.domain.shared_services.user_memory_service import reset_user_memory_service

    try:
        memory_service = _fresh_memory_service(tmp_path, monkeypatch)
        created = memory_service.propose_memory_candidate(
            "u1",
            "preference",
            "reply_style",
            "concise",
            source="memory_v2_api",
            confidence=0.9,
        )
        assert created["success"] is True
        memory_id = created["candidate"]["memory_id"]

        persy = PersyMemoryApplicationService(memory_service=memory_service)
        ctx = DatasetAccessContext(
            actor_id="u1",
            tenant_id=str(TENANT_ID),
            permissions=frozenset({DATASET_READ_PERMISSION, DATASET_WRITE_PERMISSION}),
        )
        result = persy.mutate(
            access_context=ctx,
            memory_id=memory_id,
            action="delete",
            reason="test",
        )
        assert result["success"] is True
        assert result["memory"]["status"] == "deleted"

        records = [r for r in memory_service.list_memories("u1") if r.get("memory_id") == memory_id]
        assert len(records) == 1, "知识库删除不得物理移除记忆行"
        assert records[0]["status"] == "deleted"
        assert records[0].get("deleted_at")

        stored = json.loads((tmp_path / "memory_store.json").read_text(encoding="utf-8"))
        persisted = [
            r for r in stored["u1"]["memory_v2_records"] if r.get("memory_id") == memory_id
        ]
        assert persisted and persisted[0]["status"] == "deleted"
    finally:
        reset_user_memory_service()


def test_memory_v2_delete_is_soft_status(tmp_path, monkeypatch):
    """DELETE /api/memory/v2/{id} → status=deleted，记录和文件都保留。"""
    from app.domain.shared_services.user_memory_service import reset_user_memory_service

    try:
        service = _fresh_memory_service(tmp_path, monkeypatch)
        created = service.propose_memory_candidate(
            "u2",
            "entity",
            "company",
            "XCMAX",
            source="memory_v2_api",
            confidence=0.8,
        )
        memory_id = created["candidate"]["memory_id"]
        assert (tmp_path / "memory_store.json").exists()

        result = service.delete_memory("u2", memory_id, reason="user asked")
        assert result["success"] is True
        assert result["memory"]["status"] == "deleted"
        assert result["memory"].get("deleted_at")

        records = [r for r in service.list_memories("u2") if r.get("memory_id") == memory_id]
        assert len(records) == 1
        assert records[0]["status"] == "deleted"

        stored = json.loads((tmp_path / "memory_store.json").read_text(encoding="utf-8"))
        persisted = [
            r for r in stored["u2"]["memory_v2_records"] if r.get("memory_id") == memory_id
        ]
        assert persisted and persisted[0]["status"] == "deleted"
    finally:
        reset_user_memory_service()


def test_mobile_ai_group_delete_rewrites_catalog_but_keeps_messages(tmp_path):
    """DELETE /api/mobile/v1/ai-groups/{id} → groups.jsonl 重写，messages.jsonl 保留。"""
    repository = GroupChatRepository(tmp_path)
    repository.append_group({"id": "g1", "user_id": 7, "name": "A"})
    repository.append_group({"id": "g2", "user_id": 8, "name": "B"})
    repository.append_messages([{"group_id": "g1", "user_id": 7, "text": "should survive"}])
    messages_before = repository._messages_path.read_bytes()

    store = GroupStore(
        all=repository.all_groups,
        for_user=repository.user_groups,
        append=repository.append_group,
        rewrite=repository.rewrite_groups,
        resolve=repository.resolve_group_id,
        compact=repository.compact_groups_file_if_needed,
    )
    messages = MessageStore(
        read=repository.read_messages,
        append=repository.append_messages,
        rewrite=repository.rewrite_messages,
        previews=lambda user_id: {},
    )
    directory = DirectoryActions(seed=lambda user_id: [], backfill=lambda rows: None)
    catalog = GroupCatalog(store, messages, directory, mode="local")

    result = catalog.delete_group(user_id=7, group_id="g1")
    assert result["deleted"] is True

    assert repository.user_groups(7) == []
    assert [g["id"] for g in repository.user_groups(8)] == ["g2"]
    assert "g1" not in repository._groups_path.read_text(encoding="utf-8")

    assert repository._messages_path.exists()
    assert repository._messages_path.read_bytes() == messages_before
    assert [m["text"] for m in repository.read_messages()] == ["should survive"]


def test_mods_delete_removes_mod_directory(tmp_path, monkeypatch):
    """DELETE /api/mods/{id} → 删除 mods/ 目录文件（无数据库记录可删）。"""
    from app.application.mod_uninstall import uninstall_mod_for_request
    from app.infrastructure.mods.mod_manager import ModManager

    root = tmp_path / "mods"
    mod_dir = root / "demo-mod"
    mod_dir.mkdir(parents=True)
    (mod_dir / "manifest.json").write_text(
        json.dumps({"id": "demo-mod", "name": "Demo", "version": "1.0.0", "scope": "global"}),
        encoding="utf-8",
    )
    (mod_dir / "index.py").write_text("VALUE = 1\n", encoding="utf-8")

    manager = ModManager(mods_root=str(root))

    class _Registry:
        def get_mod_metadata(self, mod_id):
            return SimpleNamespace(id=mod_id) if mod_id == "demo-mod" else None

    monkeypatch.setattr(
        "app.application.mod_uninstall.get_logged_in_user",
        lambda request: SimpleNamespace(tier="admin", username="admin"),
    )
    monkeypatch.setattr(
        "app.application.mod_uninstall.resolve_workspace_owner_id",
        lambda request, user: "workspace-owner",
    )
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_manager", lambda: manager)
    monkeypatch.setattr("app.infrastructure.mods.mod_manager.get_mod_registry", lambda: _Registry())

    ok, message = uninstall_mod_for_request(object(), "demo-mod")
    assert ok is True, message
    assert not mod_dir.exists()


def test_products_delete_is_hard_delete(sqlite_db):
    """POST /api/products/delete → 仓储 DELETE，产品行不存在（对照组：无软删除）。"""
    from app.db.models import Product
    from app.domain.shared_services.products_service import ProductsService
    from app.infrastructure.tenant_scope import tenant_scope

    factory, _engine = sqlite_db
    with factory() as db:
        product = Product(name="待删产品", tenant_id=TENANT_ID, is_active=1)
        db.add(product)
        db.commit()
        db.refresh(product)
        product_id = product.id

    with tenant_scope(TENANT_ID):
        result = ProductsService().delete_product(product_id)
    assert result["success"] is True

    with factory() as db:
        assert db.query(Product).filter(Product.id == product_id).first() is None, (
            "产品删除必须是物理删除，行不应保留"
        )
