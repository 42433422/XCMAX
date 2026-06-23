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

# 下列子模块被 pytest monkeypatch.setattr 的属性遍历路径引用；
# 必须在包层面显式导入，否则 pytest 9.x 在 getattr 找不到时走 importlib
# 回退路径会从错误的起点继续遍历，导致 AttributeError。
from . import (  # noqa: E402
    ai_chat_helpers,
    employee_pack_runner,
    excel_template_http_app_service,
    facades,
    ocr_app_service,
    print_app_service,
    session_account_meta,
    xcmax_sync_app,
)

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
]
