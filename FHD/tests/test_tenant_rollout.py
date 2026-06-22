"""验证租户隔离全量推广：分类正确性 + 代表模型隔离。

分类规则：业务/协作/AI 会话数据 → 挂 TenantScopedMixin；
身份/RBAC/全局目录(AITool) + 暂缓项(miniprogram/mobile) → 绝不挂。
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.mixins import TenantScopedMixin
from app.db.models import (
    ai,
    ai_business_evidence,
    approval,
    customer,
    finance,
    im,
    inventory,
    material,
    miniprogram,
    mobile_device,
    permission,
    product,
    purchase,
    purchase_unit,
    service_request,
    shipment,
    tenant,
    user,
    wechat,
)
from app.db.tenant_filter import install_tenant_filter
from app.request_tenant_ctx import tenant_scope

SCOPED = [
    product.Product, customer.Customer, material.Material,
    purchase.Supplier, purchase.PurchaseOrder, purchase.PurchaseOrderItem,
    purchase.PurchaseInbound, purchase.PurchaseInboundItem, purchase_unit.PurchaseUnit,
    inventory.Warehouse, inventory.StorageLocation, inventory.InventoryLedger,
    inventory.InventoryTransaction, finance.FinancialTransaction,
    shipment.ShipmentRecord, ai_business_evidence.ShipmentAuditEvent,
    ai_business_evidence.ContractExpiryNotification,
    approval.ApprovalFlow, approval.ApprovalFlowNode, approval.ApprovalRequest,
    approval.ApprovalRecord, approval.ApprovalDelegation,
    im.ImConversation, im.ImConversationMember, im.ImMessage,
    service_request.ServiceRequest, service_request.ServiceBridgeConfig,
    wechat.WechatTask, wechat.WechatContact, wechat.WechatContactContext,
    ai.AIConversation, ai.AIConversationSession, ai.UserPreference, ai.UserMemory,
]

# 身份/RBAC/全局目录 + 暂缓项(miniprogram 终端消费者 / mobile 设备)——必须保持非隔离
GLOBAL = [
    user.User, user.Session, tenant.Tenant, permission.Role, permission.Permission,
    ai.AIToolCategory, ai.AITool,
    miniprogram.MpOrder, miniprogram.MpCart, mobile_device.MobileDeviceToken,
]


def test_scoped_models_are_tenant_scoped():
    for m in SCOPED:
        assert issubclass(m, TenantScopedMixin), f"{m.__name__} 应被租户隔离但未挂 mixin"
        assert "tenant_id" in m.__table__.columns, f"{m.__name__} 表缺 tenant_id 列"


def test_global_models_not_scoped():
    for m in GLOBAL:
        assert not issubclass(m, TenantScopedMixin), f"{m.__name__} 不应被租户隔离(全局/身份/暂缓)"


def test_isolation_on_representative_model():
    install_tenant_filter()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[purchase.Supplier.__table__])
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with maker() as s, tenant_scope(1), s.begin():
        s.add(purchase.Supplier(code="t1-001", name="供应商A"))
    with maker() as s, tenant_scope(2), s.begin():
        s.add(purchase.Supplier(code="t2-001", name="供应商B"))

    with maker() as s, tenant_scope(1):
        assert {r.code for r in s.execute(select(purchase.Supplier)).scalars()} == {"t1-001"}
    with maker() as s, tenant_scope(2):
        assert {r.code for r in s.execute(select(purchase.Supplier)).scalars()} == {"t2-001"}
    engine.dispose()
