"""raw SQL 租户作用域 helper 单测 + 防回归 ratchet 守卫。

helper 与 ORM 全局过滤(app/db/tenant_filter.py)语义一致，用于 text() 原生 SQL 路径。
守卫测试锁住"触及隔离业务表的 raw SQL"的当前已知面：新增未加租户作用域的文件会让 CI 红。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.request_tenant_ctx import tenant_scope
from app.shell.mod_row_scope import (
    append_tenant_insert_col,
    append_tenant_insert_ident,
    append_tenant_scope_where,
)

COLS = {"id", "name", "tenant_id"}
NO_TID = {"id", "name"}


# ---------- helper 单测 ----------
def test_where_noop_without_tenant_id_column():
    parts: list[str] = []
    bind: dict[str, object] = {}
    with tenant_scope(1):
        append_tenant_scope_where(parts, bind, NO_TID)
    assert parts == [] and bind == {}


def test_where_noop_without_context():
    parts: list[str] = []
    bind: dict[str, object] = {}
    append_tenant_scope_where(parts, bind, COLS)  # 无 tenant_scope
    assert parts == [] and bind == {}


def test_where_appends_null_tolerant():
    parts: list[str] = []
    bind: dict[str, object] = {}
    with tenant_scope(5):
        append_tenant_scope_where(parts, bind, COLS)
    assert parts == ["(tenant_id = :__tenant_id OR tenant_id IS NULL)"]
    assert bind == {"__tenant_id": 5}


def test_where_strict(monkeypatch):
    monkeypatch.setenv("XCAGI_TENANT_STRICT", "1")
    parts: list[str] = []
    bind: dict[str, object] = {}
    with tenant_scope(5):
        append_tenant_scope_where(parts, bind, COLS)
    assert parts == ["tenant_id = :__tenant_id"]


def test_where_kill_switch(monkeypatch):
    monkeypatch.setenv("XCAGI_DISABLE_TENANT_FILTER", "1")
    parts: list[str] = []
    bind: dict[str, object] = {}
    with tenant_scope(5):
        append_tenant_scope_where(parts, bind, COLS)
    assert parts == []


def test_insert_col_stamps():
    col_pairs: list[tuple[str, str]] = [("name", "n")]
    bind: dict[str, object] = {"n": "x"}
    with tenant_scope(9):
        append_tenant_insert_col(col_pairs, bind, COLS)
    assert ("tenant_id", "__tenant_id") in col_pairs and bind["__tenant_id"] == 9


def test_insert_ident_stamps():
    icols: list[str] = ["name"]
    bind: dict[str, object] = {"name": "x"}
    with tenant_scope(9):
        append_tenant_insert_ident(icols, bind, COLS)
    assert "tenant_id" in icols and bind["tenant_id"] == 9


def test_insert_noop_without_context():
    col_pairs: list[tuple[str, str]] = [("name", "n")]
    append_tenant_insert_col(col_pairs, {}, COLS)
    assert ("tenant_id", "__tenant_id") not in col_pairs


# ---------- 防回归 ratchet ----------
_SCOPED = (
    "products|customers|materials|suppliers|purchase_orders|purchase_order_items|"
    "purchase_inbounds|purchase_inbound_items|purchase_units|warehouses|storage_locations|"
    "inventory_ledger|inventory_transactions|financial_transactions|shipment_records|"
    "shipment_audit_events|contract_expiry_notifications|approval_flows|approval_flow_nodes|"
    "approval_requests|approval_records|approval_delegations|im_conversations|"
    "im_conversation_members|im_messages|service_requests|service_bridge_config|wechat_tasks|"
    "wechat_contacts|wechat_contact_context|ai_conversations|ai_conversation_sessions|"
    "user_preferences|user_memories"
)
_RAW_SQL_RE = re.compile(rf"(?:FROM|INTO|UPDATE|DELETE FROM|JOIN)\s+\"?(?:{_SCOPED})\b", re.IGNORECASE)

# 永久豁免（设计上全局/非真实查询）
_EXEMPT = {
    "app/utils/query_optimizer.py",  # track_query 的标签字符串，非真实执行
    "app/infrastructure/database/fk_validation.py",  # 按主键的 FK 存在性校验，维护用
}
# 已知缺口（TODO: 逐文件加租户作用域 + staging 验证后从此移除）
_KNOWN_GAPS = {
    "app/infrastructure/products/db_read.py",
    "app/application/workflow/approval_service.py",
    "app/mod_sdk/client_primary_erp.py",
    "app/services/xcmax_sync_service.py",
    "app/services/wechat_contact_cache_import.py",
    "app/tasks/wechat_tasks.py",
}
_ALLOWED = _EXEMPT | _KNOWN_GAPS


def test_no_new_unscoped_raw_sql_on_tenant_tables():
    app_dir = Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for py in app_dir.rglob("*.py"):
        rel = py.relative_to(app_dir.parent).as_posix()
        if "/models/" in rel:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if not _RAW_SQL_RE.search(text):
            continue
        guarded = "append_tenant_scope_where" in text or "tenant_scope" in text
        if not guarded and rel not in _ALLOWED:
            offenders.append(rel)
    assert not offenders, (
        "发现未加租户作用域的 raw SQL（触及隔离业务表）。"
        "请加 append_tenant_scope_where / append_tenant_insert_*，或纳入白名单并说明原因：\n  "
        + "\n  ".join(sorted(offenders))
    )
