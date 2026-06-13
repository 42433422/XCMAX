"""
Process-wide service registry (composition root).

Replaces scattered ``global _foo_service`` singletons with one replaceable container.
Tests: ``set_service_registry(CustomServiceContainer(...))`` or ``reset_service_registry()``.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    from app.application.ai_chat_app_service import AIChatApplicationService
    from app.application.customer_app_service import CustomerApplicationService
    from app.application.facades.shipment_event_primary import (
        ShipmentApplicationServiceEventPrimary,
    )
    from app.application.file_analysis_app_service import FileAnalysisService
    from app.application.shipment_app_service import ShipmentApplicationService
    from app.application.unit_products_import_app_service import UnitProductsImportService
    from app.application.wechat_contact_app_service import WechatContactApplicationService
    from app.services.auth_service import AuthService
    from app.services.session_service import SessionService
    from app.services.user_preference_service import UserPreferenceService
    from app.services.user_service import UserService

_lock = threading.RLock()
_registry: Optional[ServiceContainer] = None


class ServiceContainer:
    """Lazily constructed application and infrastructure services (single process)."""

    __slots__ = (
        "_session_service",
        "_auth_service",
        "_user_service",
        "_user_preference_service",
        "_customer_application_service",
        "_ai_chat_application_service",
        "_unit_products_import_application_service",
        "_file_analysis_application_service",
        "_wechat_contact_store",
        "_wechat_contact_application_service",
        "_shipment_application_service_core",
        "_shipment_event_primary_facade",
    )

    def __init__(self) -> None:
        self._session_service = None
        self._auth_service = None
        self._user_service = None
        self._user_preference_service = None
        self._customer_application_service = None
        self._ai_chat_application_service = None
        self._unit_products_import_application_service = None
        self._file_analysis_application_service = None
        self._wechat_contact_store = None
        self._wechat_contact_application_service = None
        self._shipment_application_service_core = None
        self._shipment_event_primary_facade = None

    def _lazy(self, attr: str, factory):
        """线程安全懒加载：模块级 ``_lock``（RLock，可重入）下双重检查初始化。

        避免多个请求并发首次访问同一懒加载属性时各自构造一个实例。
        """
        if getattr(self, attr) is None:
            with _lock:
                if getattr(self, attr) is None:
                    setattr(self, attr, factory())
        return getattr(self, attr)

    # --- core HTTP / session services ---

    @property
    def session_service(self) -> SessionService:
        from app.services.session_service import SessionService

        return cast("SessionService", self._lazy("_session_service", SessionService))

    @property
    def auth_service(self) -> AuthService:
        from app.services.auth_service import AuthService

        return cast("AuthService", self._lazy("_auth_service", AuthService))

    @property
    def user_service(self) -> UserService:
        from app.services.user_service import UserService

        return cast("UserService", self._lazy("_user_service", UserService))

    @property
    def user_preference_service(self) -> UserPreferenceService:
        from app.services.user_preference_service import UserPreferenceService

        return cast("UserPreferenceService", self._lazy("_user_preference_service", UserPreferenceService))

    # --- application services (formerly module-level singletons) ---

    @property
    def customer_application_service(self) -> CustomerApplicationService:
        from app.application.customer_app_service import CustomerApplicationService

        return cast("CustomerApplicationService", self._lazy("_customer_application_service", CustomerApplicationService))

    def invalidate_customer_application_service(self) -> None:
        self._customer_application_service = None

    @property
    def ai_chat_application_service(self) -> AIChatApplicationService:
        from app.application.ai_chat_app_service import AIChatApplicationService

        return cast("AIChatApplicationService", self._lazy("_ai_chat_application_service", AIChatApplicationService))

    @property
    def unit_products_import_application_service(self) -> UnitProductsImportService:
        from app.application.unit_products_import_app_service import UnitProductsImportService

        return cast(
            "UnitProductsImportService",
            self._lazy(
                "_unit_products_import_application_service",
                UnitProductsImportService,
            ),
        )

    @property
    def file_analysis_application_service(self) -> FileAnalysisService:
        from app.application.file_analysis_app_service import FileAnalysisService

        return cast("FileAnalysisService", self._lazy("_file_analysis_application_service", FileAnalysisService))

    @property
    def wechat_contact_application_service(self) -> WechatContactApplicationService:
        def _factory() -> WechatContactApplicationService:
            from app.application.wechat_contact_app_service import (
                WechatContactApplicationService,
            )
            from app.infrastructure.persistence.wechat_contact_store_impl import (
                SQLAlchemyWechatContactStore,
            )

            if self._wechat_contact_store is None:
                self._wechat_contact_store = SQLAlchemyWechatContactStore()
            return WechatContactApplicationService(self._wechat_contact_store)

        return cast("WechatContactApplicationService", self._lazy("_wechat_contact_application_service", _factory))

    def invalidate_wechat_contact_application_service(self) -> None:
        self._wechat_contact_application_service = None
        self._wechat_contact_store = None

    # --- shipment (full infra wiring; parity with former bootstrap lru_cache) ---

    @property
    def shipment_application_service_core(self) -> ShipmentApplicationService:
        def _factory() -> ShipmentApplicationService:
            from app.application.shipment_app_service import ShipmentApplicationService
            from app.infrastructure.documents.shipment_document_generator_impl import (
                LegacyShipmentDocumentGenerator,
            )
            from app.infrastructure.persistence.purchase_unit_query_impl import (
                SQLAlchemyPurchaseUnitQuery,
            )
            from app.infrastructure.persistence.shipment_record_command_impl import (
                SQLAlchemyShipmentRecordCommand,
            )
            from app.infrastructure.persistence.shipment_record_query_impl import (
                SQLAlchemyShipmentRecordQuery,
            )
            from app.infrastructure.persistence.shipment_record_store_impl import (
                SQLAlchemyShipmentRecordStore,
            )
            from app.mod_sdk.erp_repository_registry import resolve_shipment_repository

            shipment_repo, _provider = resolve_shipment_repository()
            return ShipmentApplicationService(
                repository=shipment_repo,
                document_generator=LegacyShipmentDocumentGenerator(),
                record_store=SQLAlchemyShipmentRecordStore(),
                record_query=SQLAlchemyShipmentRecordQuery(),
                record_command=SQLAlchemyShipmentRecordCommand(),
                purchase_unit_query=SQLAlchemyPurchaseUnitQuery(),
            )

        return cast("ShipmentApplicationService", self._lazy("_shipment_application_service_core", _factory))

    @property
    def shipment_event_primary_facade(self) -> ShipmentApplicationServiceEventPrimary:
        def _factory() -> ShipmentApplicationServiceEventPrimary:
            from app.application.facades.shipment_event_primary import (
                ShipmentApplicationServiceEventPrimary,
            )

            return ShipmentApplicationServiceEventPrimary(
                self.shipment_application_service_core
            )

        return cast("ShipmentApplicationServiceEventPrimary", self._lazy("_shipment_event_primary_facade", _factory))

    def invalidate_shipment_wiring(self) -> None:
        """Clear shipment singletons (tests / hot-reload hooks)."""
        self._shipment_application_service_core = None
        self._shipment_event_primary_facade = None


def get_service_registry() -> ServiceContainer:
    global _registry
    with _lock:
        if _registry is None:
            _registry = ServiceContainer()
        return _registry


def set_service_registry(container: Optional[ServiceContainer]) -> None:
    """Replace the entire registry (tests). Pass ``None`` to drop the current container."""
    global _registry
    with _lock:
        _registry = container


def reset_service_registry() -> None:
    """Drop the registry so the next ``get_service_registry()`` builds a fresh container."""
    set_service_registry(None)
