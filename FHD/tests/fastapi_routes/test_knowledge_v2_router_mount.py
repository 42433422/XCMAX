"""验证 v2 路由 lazy 初始化与主应用挂载。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.application.memory_graph_app_service import MemoryGraphAppService
from app.application.memory_update_engine import MemoryUpdateEngine
from app.db.base import Base
from app.fastapi_routes.knowledge_v2 import (
    create_v2_router,
    get_default_app_service,
    reset_default_app_service,
)
from app.infrastructure.memory_graph_store import MemoryGraphStore


@pytest.fixture()
def in_memory_app_service():
    """构造内存级 AppService，并在测试后重置 v2 模块单例。"""
    reset_default_app_service()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    store = MemoryGraphStore(Session(engine))
    app_service = MemoryGraphAppService(store=store, update_engine=MemoryUpdateEngine(store))
    yield app_service
    reset_default_app_service()


def test_create_v2_router_with_explicit_app_service(in_memory_app_service):
    """显式传入 app_service 时直接使用，不触发 lazy 初始化。"""
    reset_default_app_service()
    app = FastAPI()
    app.include_router(create_v2_router(in_memory_app_service))
    client = TestClient(app)
    resp = client.get("/api/knowledge/v2/health")
    assert resp.status_code == 200
    assert resp.json()["version"] == "v2"


def test_create_v2_router_lazy_init(monkeypatch, in_memory_app_service):
    """app_service 为 None 时通过 get_default_app_service() 懒构造。"""
    # 让 lazy 路径返回我们的内存 AppService，避免触发真实 DB
    monkeypatch.setattr(
        "app.fastapi_routes.knowledge_v2.get_default_app_service",
        lambda: in_memory_app_service,
    )
    app = FastAPI()
    app.include_router(create_v2_router(None))
    client = TestClient(app)
    resp = client.get("/api/knowledge/v2/health")
    assert resp.status_code == 200
    # 写入一条节点验证 lazy 实例真的可用
    resp = client.post(
        "/api/knowledge/v2/nodes",
        json={
            "type": "constraint",
            "title": "lazy-init 约束",
            "content": "v2 路由可在不显式注入依赖时工作",
            "scope": "project",
            "scope_id": "XCMAX",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_get_default_app_service_singleton():
    """get_default_app_service 默认返回同一个单例。"""
    reset_default_app_service()
    captured: list = []

    def _fake_session_local():
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        session = Session(engine)
        captured.append(session)
        return session

    # 直接 patch 模块内部的 SessionLocal 引用，避免触发真实数据库
    import app.db as db_module

    original_session_local = db_module.SessionLocal
    db_module.SessionLocal = _fake_session_local
    try:
        svc1 = get_default_app_service()
        svc2 = get_default_app_service()
        assert svc1 is svc2
    finally:
        db_module.SessionLocal = original_session_local
        reset_default_app_service()


def test_v2_router_mounted_in_business_routes(in_memory_app_service, monkeypatch):
    """主应用 business 路由注册器应包含 knowledge_v2 名称。"""
    monkeypatch.setattr(
        "app.fastapi_routes.knowledge_v2.get_default_app_service",
        lambda: in_memory_app_service,
    )
    captured_names: list[str] = []

    class _StubRegistry:
        def __init__(self) -> None:
            self.app = None
            self._routers: dict[str, object] = {}

        def register_router(
            self,
            name: str,
            router,
            *,
            priority: int = 50,
            prefix: str | None = None,
            tags: list[str] | None = None,
            **kwargs,
        ) -> None:
            captured_names.append(name)
            self._routers[name] = router

    from app.fastapi_routes.mounts.business import register_business_routes

    app = FastAPI()
    registry = _StubRegistry()
    register_business_routes(app, registry)
    assert "knowledge_v2" in captured_names
    assert "knowledge_v1" in captured_names
