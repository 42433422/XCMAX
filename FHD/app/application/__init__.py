"""Public application services, loaded only when the caller requests that domain.

Tool workers import a small application submodule under a deadline. Importing
this package must not preload unrelated document, spreadsheet, desktop, or
customer services. Explicit lazy exports preserve the existing public API and
module attributes used by pytest and framework dependency overrides.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ai_chat_app_service import (
        AIChatApplicationService as AIChatApplicationService,
        get_ai_chat_app_service as get_ai_chat_app_service,
    )
    from .auth_app_service import (
        AuthApplicationService as AuthApplicationService,
        get_auth_app_service as get_auth_app_service,
    )
    from .conversation_app_service import (
        ConversationApplicationService as ConversationApplicationService,
        get_conversation_app_service as get_conversation_app_service,
    )
    from .customer_app_service import (
        CustomerApplicationService as CustomerApplicationService,
        get_customer_app_service as get_customer_app_service,
    )
    from .excel_vector_app_service import (
        ExcelVectorIngestApplicationService as ExcelVectorIngestApplicationService,
        ExcelVectorSearchApplicationService as ExcelVectorSearchApplicationService,
        get_excel_vector_ingest_app_service as get_excel_vector_ingest_app_service,
        get_excel_vector_search_app_service as get_excel_vector_search_app_service,
    )
    from .extract_log_app_service import (
        ExtractLogApplicationService as ExtractLogApplicationService,
        get_extract_log_app_service as get_extract_log_app_service,
    )
    from .file_analysis_app_service import (
        FileAnalysisService as FileAnalysisService,
        get_file_analysis_app_service as get_file_analysis_app_service,
    )
    from .material_app_service import (
        MaterialApplicationService as MaterialApplicationService,
        get_material_app_service as get_material_app_service,
        get_material_application_service as get_material_application_service,
    )
    from .ocr_app_service import (
        OCRApplicationService as OCRApplicationService,
        get_ocr_application_service as get_ocr_application_service,
    )
    from .print_app_service import (
        PrintApplicationService as PrintApplicationService,
        get_print_application_service as get_print_application_service,
    )
    from .product_app_service import (
        ProductApplicationService as ProductApplicationService,
        get_product_app_service as get_product_app_service,
        get_product_application_service as get_product_application_service,
    )
    from .product_import_app_service import (
        ProductImportApplicationService as ProductImportApplicationService,
        get_product_import_application_service as get_product_import_application_service,
    )
    from .shipment_app_service import (
        ShipmentApplicationService as ShipmentApplicationService,
        get_shipment_application_service as get_shipment_application_service,
    )
    from .template_app_service import (
        TemplateApplicationService as TemplateApplicationService,
        get_template_app_service as get_template_app_service,
    )
    from .unit_products_import_app_service import (
        UnitProductsImportService as UnitProductsImportService,
        get_unit_products_import_app_service as get_unit_products_import_app_service,
    )
    from .user_app_service import (
        UserApplicationService as UserApplicationService,
        get_user_app_service as get_user_app_service,
    )
    from .user_memory_vector_app_service import (
        UserMemoryRagApplicationService as UserMemoryRagApplicationService,
        UserMemoryVectorIngestApplicationService as UserMemoryVectorIngestApplicationService,
        get_user_memory_rag_app_service as get_user_memory_rag_app_service,
        get_user_memory_vector_ingest_app_service as get_user_memory_vector_ingest_app_service,
    )
    from .user_preference_app_service import (
        UserPreferenceApplicationService as UserPreferenceApplicationService,
        get_user_preference_app_service as get_user_preference_app_service,
    )
    from . import (
        ai_chat_helpers,
        employee_pack_runner,
        excel_template_http_app_service,
        facades,
        ocr_app_service,
        print_app_service,
        session_account_meta,
        xcmax_sync_app,
    )
_SERVICE_EXPORTS: dict[str, str] = {
    "AIChatApplicationService": "ai_chat_app_service",
    "get_ai_chat_app_service": "ai_chat_app_service",
    "AuthApplicationService": "auth_app_service",
    "get_auth_app_service": "auth_app_service",
    "ConversationApplicationService": "conversation_app_service",
    "get_conversation_app_service": "conversation_app_service",
    "CustomerApplicationService": "customer_app_service",
    "get_customer_app_service": "customer_app_service",
    "ExcelVectorIngestApplicationService": "excel_vector_app_service",
    "ExcelVectorSearchApplicationService": "excel_vector_app_service",
    "get_excel_vector_ingest_app_service": "excel_vector_app_service",
    "get_excel_vector_search_app_service": "excel_vector_app_service",
    "ExtractLogApplicationService": "extract_log_app_service",
    "get_extract_log_app_service": "extract_log_app_service",
    "FileAnalysisService": "file_analysis_app_service",
    "get_file_analysis_app_service": "file_analysis_app_service",
    "MaterialApplicationService": "material_app_service",
    "get_material_app_service": "material_app_service",
    "get_material_application_service": "material_app_service",
    "OCRApplicationService": "ocr_app_service",
    "get_ocr_application_service": "ocr_app_service",
    "PrintApplicationService": "print_app_service",
    "get_print_application_service": "print_app_service",
    "ProductApplicationService": "product_app_service",
    "get_product_app_service": "product_app_service",
    "get_product_application_service": "product_app_service",
    "ProductImportApplicationService": "product_import_app_service",
    "get_product_import_application_service": "product_import_app_service",
    "ShipmentApplicationService": "shipment_app_service",
    "get_shipment_application_service": "shipment_app_service",
    "TemplateApplicationService": "template_app_service",
    "get_template_app_service": "template_app_service",
    "UnitProductsImportService": "unit_products_import_app_service",
    "get_unit_products_import_app_service": "unit_products_import_app_service",
    "UserApplicationService": "user_app_service",
    "get_user_app_service": "user_app_service",
    "UserMemoryRagApplicationService": "user_memory_vector_app_service",
    "UserMemoryVectorIngestApplicationService": "user_memory_vector_app_service",
    "get_user_memory_rag_app_service": "user_memory_vector_app_service",
    "get_user_memory_vector_ingest_app_service": "user_memory_vector_app_service",
    "UserPreferenceApplicationService": "user_preference_app_service",
    "get_user_preference_app_service": "user_preference_app_service",
}
_MODULE_EXPORTS = frozenset(_SERVICE_EXPORTS.values()) | frozenset(
    [
        "ai_chat_helpers",
        "employee_pack_runner",
        "excel_template_http_app_service",
        "facades",
        "session_account_meta",
        "xcmax_sync_app",
    ]
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
]


def __getattr__(name: str) -> Any:
    module = _SERVICE_EXPORTS.get(name)
    if module is not None:
        return getattr(import_module(f"{__name__}.{module}"), name)
    if name in _MODULE_EXPORTS:
        value = import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SERVICE_EXPORTS.keys() | _MODULE_EXPORTS)
