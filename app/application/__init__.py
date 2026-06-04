"""
应用服务层统一入口

此模块提供所有应用服务的统一访问入口，确保 routes 层只依赖 application 层
"""

from .ai_chat_app_service import AIChatApplicationService, get_ai_chat_app_service
from .auth_app_service import AuthApplicationService, get_auth_app_service
from .conversation_app_service import ConversationApplicationService, get_conversation_app_service
from .customer_app_service import CustomerApplicationService, get_customer_app_service
from .excel_vector_app_service import (
    ExcelVectorIngestApplicationService,
    ExcelVectorSearchApplicationService,
    get_excel_vector_ingest_app_service,
    get_excel_vector_search_app_service,
)
from .extract_log_app_service import ExtractLogApplicationService, get_extract_log_app_service
from .file_analysis_app_service import FileAnalysisService, get_file_analysis_app_service
from .material_app_service import (
    MaterialApplicationService,
    get_material_app_service,
    get_material_application_service,
)
from .ocr_app_service import OCRApplicationService, get_ocr_application_service
from .print_app_service import PrintApplicationService, get_print_application_service
from .product_app_service import (
    ProductApplicationService,
    get_product_app_service,
    get_product_application_service,
)
from .product_import_app_service import (
    ProductImportApplicationService,
    get_product_import_application_service,
)
from .shipment_app_service import ShipmentApplicationService, get_shipment_application_service
from .template_app_service import TemplateApplicationService, get_template_app_service
from .unit_products_import_app_service import (
    UnitProductsImportService,
    get_unit_products_import_app_service,
)
from .user_app_service import UserApplicationService, get_user_app_service
from .user_memory_vector_app_service import (
    UserMemoryRagApplicationService,
    UserMemoryVectorIngestApplicationService,
    get_user_memory_rag_app_service,
    get_user_memory_vector_ingest_app_service,
)
from .user_preference_app_service import (
    UserPreferenceApplicationService,
    get_user_preference_app_service,
)
from .wechat_contact_app_service import (
    WechatContactApplicationService,
    get_wechat_contact_app_service,
)
from .wechat_task_app_service import WechatTaskApplicationService, get_wechat_task_app_service
from .inventory_app_service import InventoryApplicationService, get_inventory_app_service
from .contract_lifecycle_app_service import (
    ContractLifecycleApplicationService,
    get_contract_lifecycle_app_service,
)
from .user_cs_app_service import UserCsApplicationService, get_user_cs_app_service
from .wechat_integration_app_service import (
    WechatIntegrationApplicationService,
    get_wechat_integration_app_service,
)
from .operations_app_service import OperationsApplicationService, get_operations_app_service
from .admin_sync_app_service import AdminSyncApplicationService, get_admin_sync_app_service
from .purchase_app_service import PurchaseApplicationService, get_purchase_app_service
from .report_app_service import ReportApplicationService, get_report_app_service
from .excel_import_app_service import ExcelImportApplicationService, get_excel_import_app_service
from .query_app_service import QueryApplicationService, get_query_app_service
from .kitten_app_service import KittenApplicationService, get_kitten_app_service

__all__ = [
    "AIChatApplicationService",
    "get_ai_chat_app_service",
    "AuthApplicationService",
    "get_auth_app_service",
    "ConversationApplicationService",
    "get_conversation_app_service",
    "CustomerApplicationService",
    "get_customer_app_service",
    "ExcelVectorIngestApplicationService",
    "get_excel_vector_ingest_app_service",
    "ExcelVectorSearchApplicationService",
    "get_excel_vector_search_app_service",
    "UserMemoryVectorIngestApplicationService",
    "get_user_memory_vector_ingest_app_service",
    "UserMemoryRagApplicationService",
    "get_user_memory_rag_app_service",
    "FileAnalysisService",
    "get_file_analysis_app_service",
    "MaterialApplicationService",
    "get_material_application_service",
    "get_material_app_service",
    "OCRApplicationService",
    "get_ocr_application_service",
    "PrintApplicationService",
    "get_print_application_service",
    "ProductApplicationService",
    "get_product_app_service",
    "get_product_application_service",
    "ProductImportApplicationService",
    "get_product_import_application_service",
    "ExtractLogApplicationService",
    "get_extract_log_app_service",
    "ShipmentApplicationService",
    "get_shipment_application_service",
    "TemplateApplicationService",
    "get_template_app_service",
    "UnitProductsImportService",
    "get_unit_products_import_app_service",
    "UserApplicationService",
    "get_user_app_service",
    "UserPreferenceApplicationService",
    "get_user_preference_app_service",
    "WechatContactApplicationService",
    "get_wechat_contact_app_service",
    "WechatTaskApplicationService",
    "get_wechat_task_app_service",
    "InventoryApplicationService",
    "get_inventory_app_service",
    "ContractLifecycleApplicationService",
    "get_contract_lifecycle_app_service",
    "UserCsApplicationService",
    "get_user_cs_app_service",
    "WechatIntegrationApplicationService",
    "get_wechat_integration_app_service",
    "OperationsApplicationService",
    "get_operations_app_service",
    "AdminSyncApplicationService",
    "get_admin_sync_app_service",
    "PurchaseApplicationService",
    "get_purchase_app_service",
    "ReportApplicationService",
    "get_report_app_service",
    "ExcelImportApplicationService",
    "get_excel_import_app_service",
    "get_material_application_service",
    "QueryApplicationService",
    "get_query_app_service",
    "KittenApplicationService",
    "get_kitten_app_service",
]
