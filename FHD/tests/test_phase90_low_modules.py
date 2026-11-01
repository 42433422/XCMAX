"""低覆盖模块的业务回归测试。

保留的测试函数提供专用测试未覆盖的模块覆盖：
- client_primary_erp: SQLite 客户列表查询 + mod 桥接调用
- surface_audit_demo_account: demo 用户种子行创建

已删除的冗余测试（被专用测试覆盖）：
- customer_delivery_seed_* → test_mod_sdk/test_customer_delivery_seed_cov.py
- planner_business_db_private_helpers → test_workflow_planner_cov.py
- ai_chat_app_service_runtime_context_helpers → test_ai_chat_app_service_ext2.py 等
- application_tools_workflow_excel_analysis → test_workflow_tools.py 等
- registered_workflow_router_private_branches → test_tools_workflow_registered.py 等
"""

from __future__ import annotations

import sqlite3
import types

import pytest


def _make_customer_db(path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE customers ("
            "id INTEGER PRIMARY KEY, "
            "customer_name TEXT, "
            "contact_person TEXT, "
            "contact_phone TEXT, "
            "address TEXT, "
            "purchase_unit TEXT"
            ")"
        )
        conn.executemany(
            "INSERT INTO customers "
            "(customer_name, contact_person, contact_phone, address, purchase_unit) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("成都修茈", "张三", "13800000000", "成都", "吨"),
                ("上海样例", "李四", "13900000000", "上海", "件"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


def test_surface_audit_seed_demo_user_row_creates_user_and_tenant(monkeypatch):
    from app.application import surface_audit_demo_account as demo

    class FakeQuery:
        def __init__(self, session, model):
            self.session = session
            self.model = model

        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            if self.model.__name__ == "User":
                return self.session.user
            if self.model.__name__ == "Tenant":
                return self.session.tenant
            return None

    class FakeSession:
        def __init__(self):
            self.user = None
            self.tenant = None
            self.added = []
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def query(self, model):
            return FakeQuery(self, model)

        def add(self, row):
            self.added.append(row)
            if row.__class__.__name__ == "User":
                self.user = row
            if row.__class__.__name__ == "Tenant":
                self.tenant = row

        def flush(self):
            for idx, row in enumerate(self.added, start=1):
                if getattr(row, "id", None) is None:
                    row.id = idx

        def commit(self):
            self.committed = True

    demo.demo_account_config.cache_clear()
    monkeypatch.setenv("SURFACE_AUDIT_DEMO_USER", "audit-demo")
    monkeypatch.setenv("SURFACE_AUDIT_DEMO_PASSWORD", "Audit@2026")
    session = FakeSession()

    demo.seed_demo_user_row(session_factory=lambda: session)

    assert session.committed is True
    assert session.user.username == "audit-demo"
    assert session.user.role == "user"
    assert session.user.tenant_id == session.tenant.id
    assert session.tenant.plan_id == "saas-enterprise"
    assert session.tenant.is_active is True


def test_client_primary_erp_sqlite_customer_list(tmp_path):
    from app.mod_sdk import client_primary_erp as erp

    # M14 回归：私有库缺失时必须**抛出**（由调用方回落宿主服务路径），
    # 而不是静默返回空列表 —— 否则「客户 0 条」与「库缺失」不可区分。
    with pytest.raises(FileNotFoundError):
        erp._sqlite_customers_list(tmp_path / "missing.sqlite", page=1, per_page=20, keyword=None)

    db_path = tmp_path / "customers.sqlite"
    _make_customer_db(db_path)

    result = erp._sqlite_customers_list(db_path, page=1, per_page=1, keyword="张")

    assert result["success"] is True
    assert result["total"] == 1
    assert result["data"][0]["customer_name"] == "成都修茈"
    assert result["data"][0]["contact_phone"] == "13800000000"


def test_client_primary_erp_invokes_mod_customer_database(monkeypatch, tmp_path):
    import app.infrastructure.mods.mod_manager as mod_manager
    import app.request_active_mod_ctx as active_ctx
    from app.mod_sdk import client_primary_erp as erp

    db_path = tmp_path / "customers.sqlite"
    _make_customer_db(db_path)

    monkeypatch.setattr(erp, "PROTECTED_CLIENT_MOD_IDS", {"client-mod"})
    monkeypatch.setattr(active_ctx, "get_request_active_mod_id", lambda: "client-mod")
    monkeypatch.setattr(mod_manager, "ensure_mod_api_ready", lambda mod_id: None)
    monkeypatch.setattr(
        mod_manager,
        "get_mod_manager",
        lambda: types.SimpleNamespace(resolve_mod_directory=lambda mod_id: tmp_path / "client-mod"),
    )
    monkeypatch.setattr(
        mod_manager,
        "import_mod_backend_py",
        lambda *_args: types.SimpleNamespace(get_database_path=lambda: db_path),
    )

    result = erp.try_invoke_client_mod_customers_list(page=1, per_page=20, keyword="成都")

    assert result is not None
    assert result["source"] == "mod:client-mod"
    assert result["execution_path"] == "client_primary_mod_sqlite"
    assert result["total"] == 1
    assert result["data"][0]["contact_person"] == "张三"


def test_client_primary_erp_falls_back_when_private_db_missing(monkeypatch, tmp_path, caplog):
    """M14 回归：Mod 私有库不存在时不得返回 200 空列表，须返回 None 以回落宿主路径，
    并留下可检索的 WARNING 告警。"""
    import logging

    import app.infrastructure.mods.mod_manager as mod_manager
    import app.request_active_mod_ctx as active_ctx
    from app.mod_sdk import client_primary_erp as erp

    monkeypatch.setattr(erp, "PROTECTED_CLIENT_MOD_IDS", {"client-mod"})
    monkeypatch.setattr(active_ctx, "get_request_active_mod_id", lambda: "client-mod")
    monkeypatch.setattr(mod_manager, "ensure_mod_api_ready", lambda mod_id: None)
    monkeypatch.setattr(
        mod_manager,
        "get_mod_manager",
        lambda: types.SimpleNamespace(resolve_mod_directory=lambda mod_id: tmp_path / "client-mod"),
    )
    monkeypatch.setattr(
        mod_manager,
        "import_mod_backend_py",
        lambda *_args: types.SimpleNamespace(
            get_database_path=lambda: tmp_path / "mod_dbs" / "taiyangniao_pro.db"
        ),
    )

    with caplog.at_level(logging.WARNING, logger=erp.__name__):
        result = erp.try_invoke_client_mod_customers_list(page=1, per_page=20, keyword=None)

    assert result is None
    assert "private sqlite missing" in caplog.text


def test_client_primary_erp_returns_none_for_parse_or_runtime_failures(monkeypatch):
    import app.infrastructure.mods.mod_manager as mod_manager
    import app.request_active_mod_ctx as active_ctx
    from app.mod_sdk import client_primary_erp as erp

    monkeypatch.setattr(erp, "PROTECTED_CLIENT_MOD_IDS", {"client-mod"})
    monkeypatch.setattr(active_ctx, "get_request_active_mod_id", lambda: "")
    monkeypatch.setattr(
        active_ctx,
        "parse_active_mod_header",
        lambda _headers: (_ for _ in ()).throw(OSError("bad header")),
    )
    request = types.SimpleNamespace(headers={"x-active-mod-id": "client-mod"})
    assert erp.try_invoke_client_mod_customers_list(request=request) is None

    monkeypatch.setattr(active_ctx, "get_request_active_mod_id", lambda: "client-mod")
    monkeypatch.setattr(
        mod_manager,
        "ensure_mod_api_ready",
        lambda _mod_id: (_ for _ in ()).throw(OSError("not ready")),
    )
    assert erp.try_invoke_client_mod_customers_list() is None
