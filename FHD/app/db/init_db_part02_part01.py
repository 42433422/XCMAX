# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.db.init_db")


def ensure_sqlite_rbac_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite：补齐 permissions/roles（/api/auth/me 管理员权限列表依赖）。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.permission import Permission, Role, role_permissions

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        needed = {"permissions", "roles", "role_permissions"}
        if not needed.issubset(tables):
            _facade().logger.info("SQLite 缺少 RBAC 表，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[
                    _facade()._orm_table(Permission),
                    _facade()._orm_table(Role),
                    role_permissions,
                ],
                checkfirst=True,
            )
        _facade()._seed_sqlite_rbac_defaults(real_engine)
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning("ensure_sqlite_rbac_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def ensure_sqlite_inventory_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite 基库：补齐库存、采购、出货和财务汇总相关表。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.finance import FinancialTransaction
    from app.db.models.inventory import (
        InventoryLedger,
        InventoryTransaction,
        StorageLocation,
        Warehouse,
    )
    from app.db.models.material import Material
    from app.db.models.product import Product, UomCategory, UomUnit
    from app.db.models.purchase import (
        PurchaseInbound,
        PurchaseInboundItem,
        PurchaseOrder,
        PurchaseOrderItem,
        Supplier,
    )
    from app.db.models.shipment import ShipmentRecord
    from app.db.models.tenant import Tenant

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        needed = {
            "tenants",
            "uom_categories",
            "uom_units",
            "products",
            "materials",
            "warehouses",
            "storage_locations",
            "inventory_ledger",
            "inventory_transactions",
            "suppliers",
            "purchase_orders",
            "purchase_order_items",
            "purchase_inbounds",
            "purchase_inbound_items",
            "shipment_records",
            "financial_transactions",
        }
        if not needed.issubset(tables):
            missing = ", ".join(sorted(needed - tables))
            _facade().logger.info("SQLite 缺少业务汇总表，正在通过 ORM 创建: %s", missing)
            Base.metadata.create_all(
                real_engine,
                tables=[
                    _facade()._orm_table(Tenant),
                    _facade()._orm_table(UomCategory),
                    _facade()._orm_table(UomUnit),
                    _facade()._orm_table(Product),
                    _facade()._orm_table(Material),
                    _facade()._orm_table(Warehouse),
                    _facade()._orm_table(StorageLocation),
                    _facade()._orm_table(InventoryLedger),
                    _facade()._orm_table(InventoryTransaction),
                    _facade()._orm_table(Supplier),
                    _facade()._orm_table(PurchaseOrder),
                    _facade()._orm_table(PurchaseOrderItem),
                    _facade()._orm_table(PurchaseInbound),
                    _facade()._orm_table(PurchaseInboundItem),
                    _facade()._orm_table(ShipmentRecord),
                    _facade()._orm_table(FinancialTransaction),
                ],
                checkfirst=True,
            )
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning(
                "ensure_sqlite_inventory_bootstrap 失败: %s", exc, exc_info=True
            )
            return
        raise


def ensure_sqlite_enterprise_business_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite 旧库：补齐企业登录/太阳鸟交付依赖的基础业务表。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.customer import Customer
    from app.db.models.product import Product, UomCategory, UomUnit
    from app.db.models.purchase_unit import PurchaseUnit
    from app.db.models.tenant import Tenant

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        needed = {
            "tenants",
            "customers",
            "uom_categories",
            "uom_units",
            "products",
            "purchase_units",
        }
        if not needed.issubset(tables):
            _facade().logger.info("SQLite 缺少企业业务基础表，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[
                    _facade()._orm_table(Tenant),
                    _facade()._orm_table(UomCategory),
                    _facade()._orm_table(UomUnit),
                    _facade()._orm_table(Product),
                    _facade()._orm_table(Customer),
                    _facade()._orm_table(PurchaseUnit),
                ],
                checkfirst=True,
            )
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning(
                "ensure_sqlite_enterprise_business_bootstrap 失败: %s",
                exc,
                exc_info=True,
            )
            return
        raise


def ensure_user_preferences_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """补齐 user_preferences 表（工作区 prefs 跨设备同步依赖）。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.ai import UserPreference

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None:
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "user_preferences" not in tables:
            _facade().logger.info("缺少 user_preferences 表，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[_facade()._orm_table(UserPreference)],
                checkfirst=True,
            )
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning(
                "ensure_user_preferences_bootstrap 失败: %s", exc, exc_info=True
            )
            return
        raise


def ensure_neuro_event_log_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """补齐 neuro_event_log 表（NeuroBus 核心 app service 消费者的持久落地副作用）。"""
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.neuro_event_log import NeuroEventLog

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None:
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        if "neuro_event_log" not in tables:
            _facade().logger.info("缺少 neuro_event_log 表，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[_facade()._orm_table(NeuroEventLog)],
                checkfirst=True,
            )
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning(
                "ensure_neuro_event_log_bootstrap 失败: %s", exc, exc_info=True
            )
            return
        raise


def ensure_sqlite_im_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """桌面 SQLite：补齐 IM 三张表 + AI 员工虚拟用户档案表。

    IM 表（im_conversations / im_conversation_members / im_messages）和
    ai_employee_profiles 在 Alembic 迁移链里建；SQLite 桌面模式不跑 Alembic，
    需要这里显式建出来，否则员工主动 IM 推送链路会因缺表 500。
    """
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.ai_employee import AiEmployeeProfile
    from app.db.models.im import (
        ImConversation,
        ImConversationMember,
        ImCustomerServiceAutomationState,
        ImMessage,
    )

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None or real_engine.dialect.name != "sqlite":
        return
    try:
        insp = inspect(real_engine)
        tables = set(insp.get_table_names() or [])
        needed = {
            "im_conversations",
            "im_conversation_members",
            "im_messages",
            "im_cs_automation_states",
            "ai_employee_profiles",
        }
        missing = needed - tables
        if missing:
            _facade().logger.info(
                "SQLite 缺少 IM/员工档案表 %s，正在通过 ORM 创建 …", sorted(missing)
            )
            Base.metadata.create_all(
                real_engine,
                tables=[
                    _facade()._orm_table(ImConversation),
                    _facade()._orm_table(ImConversationMember),
                    _facade()._orm_table(ImMessage),
                    _facade()._orm_table(ImCustomerServiceAutomationState),
                    _facade()._orm_table(AiEmployeeProfile),
                ],
                checkfirst=True,
            )
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning("ensure_sqlite_im_bootstrap 失败: %s", exc, exc_info=True)
            return
        raise


def ensure_employee_run_log_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """Create the employee execution ledger when migrations are not run.

    Desktop SQLite bundles intentionally bootstrap their schema in-process
    instead of invoking Alembic. The local employee execute endpoint writes to
    this table before running any employee, so a missing ledger must not turn
    every Office docking action into HTTP 500.
    """
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.employee_run_log import EmployeeRunLog

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None:
        return
    try:
        tables = set(inspect(real_engine).get_table_names() or [])
        if "employee_run_logs" not in tables:
            _facade().logger.info("缺少 employee_run_logs 表，正在通过 ORM 创建 …")
            Base.metadata.create_all(
                real_engine,
                tables=[_facade()._orm_table(EmployeeRunLog)],
                checkfirst=True,
            )
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning(
                "ensure_employee_run_log_bootstrap 失败: %s", exc, exc_info=True
            )
            return
        raise


def ensure_ai_conversation_bootstrap(
    engine: _facade().Engine | None = None,
    *,
    database_url: str | None = None,
    swallow_errors: bool = True,
) -> None:
    """Create the AI conversation memory tables when migrations are not run.

    Desktop bundles bootstrap their database schema in-process. Both the main
    chat service and local employee runtime persist context through these
    tables, so leaving them to Alembic makes otherwise-successful employee runs
    emit database errors and silently lose their conversation memory.
    """
    from sqlalchemy import inspect

    from app.db.base import Base
    from app.db.models.ai import AIConversation, AIConversationSession

    real_engine = _facade()._resolve_auth_bootstrap_engine(engine, database_url=database_url)
    if real_engine is None:
        return
    try:
        tables = set(inspect(real_engine).get_table_names() or [])
        needed = {"ai_conversation_sessions", "ai_conversations"}
        missing = needed - tables
        if missing:
            _facade().logger.info("缺少 AI 会话表 %s，正在通过 ORM 创建 …", sorted(missing))
            Base.metadata.create_all(
                real_engine,
                tables=[
                    _facade()._orm_table(AIConversationSession),
                    _facade()._orm_table(AIConversation),
                ],
                checkfirst=True,
            )
    except _facade().RECOVERABLE_ERRORS as exc:
        if swallow_errors:
            _facade().logger.warning(
                "ensure_ai_conversation_bootstrap 失败: %s", exc, exc_info=True
            )
            return
        raise
