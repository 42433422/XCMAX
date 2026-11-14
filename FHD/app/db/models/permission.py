from __future__ import annotations

from datetime import datetime
from typing import Optional, TypedDict

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.db_base import Base
from app.utils.time import utc_now_naive

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id", Integer, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    ),
)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=utc_now_naive, onupdate=utc_now_naive
    )

    permissions: Mapped[list[Permission]] = relationship(
        "Permission", secondary=role_permissions, back_populates="roles", lazy="joined"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String, default="")
    module: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime, default=utc_now_naive)

    roles: Mapped[list[Role]] = relationship(
        "Role", secondary=role_permissions, back_populates="permissions", lazy="joined"
    )


class _PermissionSeed(TypedDict):
    name: str
    code: str
    module: str


class _RoleSeed(TypedDict):
    name: str
    description: str
    permissions: list[str]


DEFAULT_PERMISSIONS: list[_PermissionSeed] = [
    {"name": "退款本人所属订单", "code": "model_payment.refund", "module": "payment"},
    {"name": "查看客户", "code": "customer.view", "module": "customer"},
    {"name": "编辑客户", "code": "customer.edit", "module": "customer"},
    {"name": "查看产品", "code": "product.view", "module": "product"},
    {"name": "编辑产品", "code": "product.edit", "module": "product"},
    {"name": "查看出货单", "code": "shipment.view", "module": "shipment"},
    {"name": "创建出货单", "code": "shipment.create", "module": "shipment"},
    {"name": "编辑出货单", "code": "shipment.edit", "module": "shipment"},
    {"name": "审批出货单", "code": "shipment.approve", "module": "shipment"},
    {"name": "标签打印", "code": "print.label", "module": "print"},
    {"name": "查看物料", "code": "material.view", "module": "material"},
    {"name": "编辑物料", "code": "material.edit", "module": "material"},
    {"name": "管理用户", "code": "admin.manage_users", "module": "admin"},
    {"name": "管理本企业角色", "code": "tenant.manage_roles", "module": "tenant"},
    {"name": "管理本人记忆", "code": "memory_v2.write", "module": "memory"},
    {"name": "查询销售订单", "code": "tool.sales.query", "module": "sales"},
    {"name": "导出报表", "code": "tool.reports.export", "module": "reports"},
    {"name": "查询销售汇总", "code": "tool.reports.sales_summary", "module": "reports"},
    {"name": "查看员工", "code": "employee.list", "module": "employee"},
    {"name": "执行员工任务", "code": "employee.execute", "module": "employee"},
    {"name": "读取表格", "code": "tool.excel_analysis.read", "module": "reports"},
    {"name": "系统配置", "code": "admin.system_config", "module": "admin"},
    {"name": "查看企业知识", "code": "dataset.read", "module": "knowledge"},
    {"name": "管理企业知识", "code": "dataset.write", "module": "knowledge"},
    {"name": "跨租户管理知识", "code": "dataset.admin", "module": "knowledge"},
    {"name": "查看数据对接", "code": "etl.read", "module": "etl"},
    {"name": "管理 ELT 模板", "code": "etl.template.manage", "module": "etl"},
    {"name": "执行 ELT", "code": "etl.execute", "module": "etl"},
    {"name": "撤销 ELT", "code": "etl.rollback", "module": "etl"},
    {"name": "管理 ELT 目标", "code": "etl.target.manage", "module": "etl"},
    {"name": "创建销售订单", "code": "tool.sales.create_order", "module": "sales"},
]

DEFAULT_ROLES: list[_RoleSeed] = [
    {
        "name": "user",
        "description": "普通业务用户（默认角色，含基础业务与 ETL 操作）",
        "permissions": [
            "customer.view",
            "customer.edit",
            "product.view",
            "product.edit",
            "shipment.view",
            "shipment.create",
            "shipment.edit",
            "material.view",
            "material.edit",
            "print.label",
            "memory_v2.write",
            "tool.sales.query",
            "tool.reports.export",
            "tool.reports.sales_summary",
            "employee.list",
            "employee.execute",
            "tool.excel_analysis.read",
            "dataset.read",
            "dataset.write",
            "etl.read",
            "etl.template.manage",
            "etl.execute",
            "tool.sales.create_order",
        ],
    },
    {
        "name": "viewer",
        "description": "只读用户",
        "permissions": [
            "customer.view",
            "product.view",
            "shipment.view",
            "material.view",
            "dataset.read",
            "etl.read",
        ],
    },
    {
        "name": "operator",
        "description": "操作员",
        "permissions": [
            "customer.view",
            "customer.edit",
            "product.view",
            "product.edit",
            "shipment.view",
            "shipment.create",
            "shipment.edit",
            "material.view",
            "material.edit",
            "print.label",
            "memory_v2.write",
            "tool.sales.query",
            "tool.reports.export",
            "tool.reports.sales_summary",
            "employee.list",
            "employee.execute",
            "tool.excel_analysis.read",
            "dataset.read",
            "dataset.write",
            "etl.read",
            "etl.template.manage",
            "etl.execute",
            "tool.sales.create_order",
        ],
    },
    {
        "name": "admin",
        "description": "管理员",
        "permissions": [
            "customer.view",
            "customer.edit",
            "product.view",
            "product.edit",
            "shipment.view",
            "shipment.create",
            "shipment.edit",
            "shipment.approve",
            "material.view",
            "material.edit",
            "print.label",
            "memory_v2.write",
            "tool.sales.query",
            "tool.reports.export",
            "tool.reports.sales_summary",
            "employee.list",
            "employee.execute",
            "tool.excel_analysis.read",
            "admin.manage_users",
            "admin.system_config",
            "dataset.read",
            "dataset.write",
            "dataset.admin",
            "etl.read",
            "etl.template.manage",
            "etl.execute",
            "etl.rollback",
            "etl.target.manage",
            "tool.sales.create_order",
        ],
    },
]
