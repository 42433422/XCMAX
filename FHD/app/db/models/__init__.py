from app.db.models.agent import (
    AgentRunRecord,
    AgentTaskCommandRecord,
    AgentTaskExecutionRecord,
    AgentTaskRecord,
)
from app.db.models.ai_circle import AiCircleComment, AiCirclePost, AiCircleReaction
from app.db.models.ai_employee import AiEmployeeProfile
from app.db.models.employee_run_log import EmployeeRunLog
from app.db.models.neuro_event_log import NeuroEventLog
from app.db.models.butler_profile import ButlerUserProfile
from app.db.models.im import ImConversation, ImConversationMember, ImMessage
from app.db.models.ai import (
    AIConversation,
    AIConversationSession,
    AITool,
    AIToolCategory,
    UserPreference,
)
from app.db.models.accounting import (
    ACCOUNT_TYPES,
    ChartOfAccount,
    JournalEntry,
    JournalEntryLine,
)
from app.db.models.ai_business_evidence import (
    ContractExpiryNotification,
    ShipmentAuditEvent,
)
from app.db.models.approval import (
    ApprovalDelegation,
    ApprovalFlow,
    ApprovalFlowNode,
    ApprovalRecord,
    ApprovalRequest,
)
from app.db.models.crm import CustomerAddress
from app.db.models.customer import Customer
from app.db.models.mrp import (
    Bom,
    BomLine,
    ManufacturingOrder,
    ManufacturingOrderLine,
)
from app.db.models.etl import (
    EtlRun,
    EtlRunRow,
    EtlTargetConfig,
    EtlTemplate,
    EtlTemplateVersion,
    EtlUpload,
)
from app.db.models.finance import FinancialTransaction
from app.db.models.hr_attendance import (
    AttendanceDailyRecord,
    AttendanceImportBatch,
    AttendanceLeaveRecord,
    ErpDepartment,
    ErpEmployee,
)
from app.db.models.inventory import (
    InventoryLedger,
    InventoryTransaction,
    StorageLocation,
    Warehouse,
)
from app.db.models.material import Material
from app.db.models.mobile_device import MobileDeviceToken
from app.db.models.mobile_notification import MobileNotificationOutbox
from app.db.models.permission import Permission, Role, role_permissions
from app.db.models.product import Product, UomCategory, UomUnit
from app.db.models.purchase import (
    PurchaseInbound,
    PurchaseInboundItem,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.db.models.purchase_unit import PurchaseUnit
from app.db.models.sales import SALES_ORDER_STATUS_FLOW, SalesOrder, SalesOrderItem
from app.db.models.receivable_allocation import ReceivableAllocation
from app.db.models.service_request import ServiceBridgeConfig, ServiceRequest
from app.db.models.shipment import ShipmentRecord
from app.db.models.shipment_etl_fingerprint import ShipmentEtlImportFingerprint
from app.db.models.tenant import Tenant
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.db.models.tutorial import TutorialRun, TutorialStepEvidence, TutorialWorkspace
from app.db.models.workflow import (
    WorkflowCheckpoint,
    WorkflowDefinition,
    WorkflowPlan,
    WorkflowRun,
    WorkflowRunStep,
)
from app.infrastructure.persona.models import PersonaEventLogModel, PersonaProfileModel

# 所有模型映射完成后安装全局多租户过滤事件（继承 TenantScopedMixin 的业务模型自动隔离）。
from app.db import tenant_filter as _tenant_filter  # noqa: E402,F401

__all__ = [
    "PurchaseUnit",
    "SalesOrder",
    "SalesOrderItem",
    "ReceivableAllocation",
    "UomCategory",
    "UomUnit",
    "SALES_ORDER_STATUS_FLOW",
    "AgentRunRecord",
    "AgentTaskRecord",
    "AgentTaskCommandRecord",
    "AgentTaskExecutionRecord",
    "AiCirclePost",
    "AiCircleReaction",
    "AiCircleComment",
    "AiEmployeeProfile",
    "EmployeeRunLog",
    "ImConversation",
    "ImConversationMember",
    "ImMessage",
    "Product",
    "ShipmentRecord",
    "ShipmentEtlImportFingerprint",
    "Customer",
    "CustomerAddress",
    "Bom",
    "BomLine",
    "ManufacturingOrder",
    "ManufacturingOrderLine",
    "EtlUpload",
    "EtlTemplate",
    "EtlTemplateVersion",
    "EtlRun",
    "EtlRunRow",
    "EtlTargetConfig",
    "FinancialTransaction",
    "ErpDepartment",
    "ErpEmployee",
    "AttendanceImportBatch",
    "AttendanceDailyRecord",
    "AttendanceLeaveRecord",
    "ChartOfAccount",
    "JournalEntry",
    "JournalEntryLine",
    "ACCOUNT_TYPES",
    "User",
    "Tenant",
    "TutorialWorkspace",
    "TutorialRun",
    "TutorialStepEvidence",
    "UserSession",
    "Permission",
    "Role",
    "AIToolCategory",
    "AITool",
    "AIConversation",
    "AIConversationSession",
    "UserPreference",
    "Material",
    "Warehouse",
    "StorageLocation",
    "InventoryLedger",
    "InventoryTransaction",
    "Supplier",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "PurchaseInbound",
    "PurchaseInboundItem",
    "ApprovalFlow",
    "ApprovalFlowNode",
    "ApprovalRequest",
    "ApprovalRecord",
    "ApprovalDelegation",
    "ServiceRequest",
    "ServiceBridgeConfig",
    "ShipmentAuditEvent",
    "ContractExpiryNotification",
    "PersonaProfileModel",
    "PersonaEventLogModel",
    "NeuroEventLog",
    "WorkflowDefinition",
    "WorkflowRun",
    "WorkflowRunStep",
    "WorkflowCheckpoint",
    "WorkflowPlan",
]
