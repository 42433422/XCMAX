"""
Composition Root / 装配入口

应用服务与基础设施的默认装配统一由 ``app.di.registry.ServiceContainer`` 持有。
本模块只保留历史调用名，避免路由、任务与工具链直接知道容器内部属性。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.contexts.flags import is_event_primary_enabled
from app.di.registry import get_service_registry

if TYPE_CHECKING:
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.customer_app_service import CustomerApplicationService
    from app.application.facades.shipment_event_primary import (
        ShipmentApplicationServiceEventPrimary,
    )
    from app.application.file_analysis_app_service import FileAnalysisService
    from app.application.shipment_app_service import ShipmentApplicationService
    from app.application.template_app_service import TemplateApplicationService
    from app.application.unit_products_import_app_service import UnitProductsImportService
    from app.application.wechat_contact_app_service import WechatContactApplicationService
    from app.services.extract_log_service import ExtractLogService
    from app.services.materials_service import MaterialsService
    from app.services.product_import_service import ProductImportService
    from app.services.products_service import ProductsService

# Intent recognition is now provided by domain layer - see get_intent_recognition_service()
# in app/domain/services/intent_recognition_service.py


def get_shipment_application_service_core() -> ShipmentApplicationService:
    """Direct shipment application service (no NeuroBus). Handlers must use this to avoid recursion."""
    return get_service_registry().shipment_application_service_core


def _get_shipment_app_service_event_primary() -> ShipmentApplicationServiceEventPrimary:
    return get_service_registry().shipment_event_primary_facade


def get_shipment_app_service() -> (
    ShipmentApplicationService | ShipmentApplicationServiceEventPrimary
):
    """
    Default entry for routes. When ``XCAGI_EVENT_PRIMARY`` or ``XCAGI_EVENT_PRIMARY_SHIPMENT``
    is set, returns the event-primary facade; otherwise the core service.
    """
    if is_event_primary_enabled("shipment"):
        return _get_shipment_app_service_event_primary()
    return get_shipment_application_service_core()


def get_template_app_service() -> TemplateApplicationService:
    return get_service_registry().template_application_service


def get_wechat_contact_app_service() -> WechatContactApplicationService:
    return get_service_registry().wechat_contact_application_service


def get_materials_service() -> MaterialsService:
    return get_service_registry().materials_service


def get_products_service() -> ProductsService:
    return get_service_registry().products_service


def get_customer_app_service() -> CustomerApplicationService:
    return get_service_registry().customer_application_service


def get_extract_log_service() -> ExtractLogService:
    return get_service_registry().extract_log_service


def get_product_import_service() -> ProductImportService:
    return get_service_registry().product_import_service


def get_ai_chat_app_service() -> AIChatApplicationService:
    return get_service_registry().ai_chat_application_service


def get_file_analysis_service() -> FileAnalysisService:
    return get_service_registry().file_analysis_application_service


def get_unit_products_import_service() -> UnitProductsImportService:
    return get_service_registry().unit_products_import_application_service
