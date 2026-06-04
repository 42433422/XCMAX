"""
Composition Root / 装配入口

应用服务与基础设施的默认装配。与 ``app.di.registry.ServiceContainer`` 对齐：
重型单例由注册表持有；本模块对外优先暴露 ``app.application`` 的 ``get_*_app_service``。
"""

from __future__ import annotations

import os
import warnings
from functools import lru_cache

from app.application.shipment_app_service import ShipmentApplicationService
from app.application.template_app_service import TemplateApplicationService


def _deprecated_bootstrap(name: str, replacement: str) -> None:
    warnings.warn(
        f"app.bootstrap.{name} 已废弃，请改用 {replacement}",
        DeprecationWarning,
        stacklevel=3,
    )


def get_shipment_application_service_core() -> ShipmentApplicationService:
    """Direct shipment application service (no NeuroBus)."""
    from app.di.registry import get_service_registry

    return get_service_registry().shipment_application_service_core


@lru_cache(maxsize=1)
def get_template_app_service() -> TemplateApplicationService:
    from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore

    base_dir = os.path.dirname(os.path.abspath(__file__))
    base_dir = os.path.dirname(base_dir)
    return TemplateApplicationService(FileSystemTemplateStore(base_dir=base_dir))


def get_wechat_contact_app_service():
    from app.application.wechat_contact_app_service import get_wechat_contact_app_service as g

    return g()


def get_materials_service():
    """已废弃：请使用 ``get_material_application_service()``。"""
    _deprecated_bootstrap("get_materials_service", "app.application.get_material_application_service")
    from app.application.material_app_service import get_material_application_service

    return get_material_application_service()


def get_material_application_service():
    from app.application.material_app_service import get_material_application_service as g

    return g()


@lru_cache(maxsize=1)
def get_products_service():
    """已废弃：请使用 ``get_product_application_service()``。"""
    _deprecated_bootstrap("get_products_service", "app.application.get_product_application_service")
    from app.application.product_app_service import get_product_application_service

    return get_product_application_service()


def get_product_application_service():
    from app.application.product_app_service import get_product_application_service as g

    return g()


def get_customer_application_service_core():
    from app.di.registry import get_service_registry

    return get_service_registry().customer_application_service


def _get_customer_app_service_event_primary():
    from app.di.registry import get_service_registry

    return get_service_registry().customer_event_primary_facade


def get_customer_app_service():
    from app.contexts.flags import is_event_primary_enabled

    if is_event_primary_enabled("customer"):
        return _get_customer_app_service_event_primary()
    return get_customer_application_service_core()


def get_product_application_service_core():
    return get_product_application_service()


def _get_product_app_service_event_primary():
    from app.di.registry import get_service_registry

    return get_service_registry().product_event_primary_facade


def get_product_app_service():
    from app.contexts.flags import is_event_primary_enabled

    if is_event_primary_enabled("product"):
        return _get_product_app_service_event_primary()
    return get_product_application_service_core()


def get_inventory_mutation_service():
    """库存变更：event-primary 或 V1 ``InventoryApplicationService``。"""
    from app.contexts.flags import is_event_primary_enabled

    if is_event_primary_enabled("inventory"):
        from app.di.registry import get_service_registry

        return get_service_registry().inventory_event_primary_facade
    from app.application.inventory_app_service import get_inventory_app_service

    return get_inventory_app_service()


def get_inventory_app_service():
    from app.application.inventory_app_service import get_inventory_app_service as g

    return g()


@lru_cache(maxsize=1)
def get_extract_log_service():
    from app.services.extract_log_service import ExtractLogService

    return ExtractLogService()


def get_product_import_service():
    """已废弃：请使用 ``get_product_import_application_service()``。"""
    _deprecated_bootstrap(
        "get_product_import_service",
        "app.application.get_product_import_application_service",
    )
    from app.application.product_import_app_service import get_product_import_application_service

    return get_product_import_application_service()


def get_ai_chat_app_service():
    from app.application.ai_chat_app_service import get_ai_chat_app_service as g

    return g()


def get_file_analysis_service():
    from app.application.file_analysis_app_service import get_file_analysis_app_service as g

    return g()


def get_unit_products_import_service():
    from app.application.unit_products_import_app_service import get_unit_products_import_app_service as g

    return g()
