"""Idempotent creation of finite ORM table groups with explicit error policies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from typing import Literal

from sqlalchemy import MetaData, Table
from sqlalchemy.engine import Engine

from app.db.base import Base
from app.db.bootstrap.contracts import InspectorFactory
from app.utils.operational_errors import RECOVERABLE_ERRORS

GroupName = Literal[
    "auth",
    "rbac",
    "inventory",
    "enterprise",
    "preferences",
    "neuro",
    "im",
    "employee",
    "conversations",
    "mobile",
    "erp",
    "approval",
    "bridge",
    "persona",
]


@dataclass(frozen=True)
class TableGroup:
    tables: tuple[Table, ...]
    operation: str
    sqlite_only: bool = False
    missing_only: bool = False


def table_group(name: GroupName, orm_table: Callable[[type[Base]], Table]) -> TableGroup:
    """Keep model ownership in the domain modules; select only each bootstrap's tables."""
    from app.db import models as m

    groups: dict[GroupName, tuple[type[Base] | Table, ...]] = {
        "auth": (m.User, m.UserSession),
        "rbac": (m.Permission, m.Role, m.role_permissions),
        "inventory": (
            m.Tenant,
            m.UomCategory,
            m.UomUnit,
            m.Product,
            m.Material,
            m.Warehouse,
            m.StorageLocation,
            m.InventoryLedger,
            m.InventoryTransaction,
            m.Supplier,
            m.PurchaseOrder,
            m.PurchaseOrderItem,
            m.PurchaseInbound,
            m.PurchaseInboundItem,
            m.ShipmentRecord,
            m.FinancialTransaction,
        ),
        "enterprise": (m.Tenant, m.UomCategory, m.UomUnit, m.Product, m.Customer, m.PurchaseUnit),
        "preferences": (m.UserPreference,),
        "neuro": (m.NeuroEventLog,),
        "im": (
            m.ImConversation,
            m.ImConversationMember,
            m.ImMessage,
            m.ImCustomerServiceAutomationState,
            m.AiEmployeeProfile,
        ),
        "employee": (m.EmployeeRunLog,),
        "conversations": (m.AIConversationSession, m.AIConversation),
        "mobile": (m.MobileDeviceToken, m.MobileNotificationOutbox),
        "erp": (
            m.SalesOrder,
            m.SalesOrderItem,
            m.ChartOfAccount,
            m.JournalEntry,
            m.JournalEntryLine,
            m.ReceivableAllocation,
            m.Bom,
            m.BomLine,
            m.ManufacturingOrder,
            m.ManufacturingOrderLine,
            m.CustomerAddress,
            m.UomCategory,
            m.UomUnit,
        ),
        "approval": (
            m.ApprovalFlow,
            m.ApprovalFlowNode,
            m.ApprovalRequest,
            m.ApprovalRecord,
            m.ApprovalDelegation,
        ),
        "bridge": (m.ServiceRequest, m.ServiceBridgeConfig),
        "persona": (m.PersonaProfileModel, m.PersonaEventLogModel),
    }
    operation_names: dict[GroupName, str] = {
        "auth": "ensure_sqlite_auth_bootstrap",
        "rbac": "ensure_sqlite_rbac_bootstrap",
        "inventory": "ensure_sqlite_inventory_bootstrap",
        "enterprise": "ensure_sqlite_enterprise_business_bootstrap",
        "preferences": "ensure_user_preferences_bootstrap",
        "neuro": "ensure_neuro_event_log_bootstrap",
        "im": "ensure_sqlite_im_bootstrap",
        "employee": "ensure_employee_run_log_bootstrap",
        "conversations": "ensure_ai_conversation_bootstrap",
        "mobile": "ensure_mobile_push_bootstrap",
        "erp": "ensure_erp_bootstrap",
    }
    return TableGroup(
        tuple(item if isinstance(item, Table) else orm_table(item) for item in groups[name]),
        operation=operation_names.get(name, name),
        sqlite_only=name in {"auth", "rbac", "inventory", "enterprise", "im"},
        missing_only=name in {"mobile", "erp"},
    )


@dataclass(frozen=True)
class OrmBootstrap:
    metadata: MetaData
    inspect: InspectorFactory
    logger: Logger

    def ensure(
        self,
        engine: Engine | None,
        group: TableGroup,
        *,
        swallow_errors: bool,
        seed: Callable[[Engine], None] | None = None,
    ) -> None:
        if engine is None or (group.sqlite_only and engine.dialect.name != "sqlite"):
            return
        try:
            existing = set(self.inspect(engine).get_table_names() or [])
            missing = [table for table in group.tables if table.name not in existing]
            if missing:
                self.logger.info(
                    "%s 缺少表 %s，正在通过 ORM 创建 …", group.operation, [t.name for t in missing]
                )
                self.metadata.create_all(
                    engine,
                    tables=missing if group.missing_only else list(group.tables),
                    checkfirst=True,
                )
            if seed is not None:
                seed(engine)
        except RECOVERABLE_ERRORS as exc:
            if not swallow_errors:
                raise
            self.logger.warning("%s 失败: %s", group.operation, exc, exc_info=True)

    def create(
        self, engine: Engine, group: TableGroup, *, label: str, swallow_errors: bool
    ) -> None:
        try:
            self.metadata.create_all(engine, tables=list(group.tables), checkfirst=True)
        except RECOVERABLE_ERRORS as exc:
            if not swallow_errors:
                raise
            self.logger.warning("%s 表 create_all 失败: %s", label, exc)
