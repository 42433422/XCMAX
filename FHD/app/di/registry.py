"""
Process-wide service registry (composition root).

Replaces scattered ``global _foo_service`` singletons with one replaceable container.
Tests: ``set_service_registry(CustomServiceContainer(...))`` or ``reset_service_registry()``.
"""

from __future__ import annotations

import os
import threading
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, cast

# LG-W1-T9-A 组合根：下划线是唯一合法的标识符分隔符。所有涉及 workflow 运行时
# 装配的精确标识符都必须用 ``sep``（即 ``chr(95)`` == ``_``）机械拼装，避免任何
# 依赖下划线显示缺失的脆弱写法。
sep = chr(95)

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
    from app.application.workflow.ports.checkpoint import CheckpointStore
    from app.application.workflow.ports.runtime import WorkflowRuntime
    from app.services.auth_service import AuthService
    from app.services.extract_log_service import ExtractLogService
    from app.services.materials_service import MaterialsService
    from app.services.product_import_service import ProductImportService
    from app.services.products_service import ProductsService
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
        "_template_application_service",
        "_materials_service",
        "_products_service",
        "_extract_log_service",
        "_product_import_service",
        "_shipment_application_service_core",
        "_shipment_event_primary_facade",
        # LG-W1-T9-A workflow 运行时组合根槽位（_ + workflow + _ + ...）
        # 名称 = "_" + "workflow" + "_" + <suffix>，与 sep 机械拼装一致。
        "_" + "workflow" + "_" + "runtime",
        "_" + "workflow" + "_" + "checkpointer",
        "_" + "workflow" + "_" + "shadow" + "_" + "checkpointer",
        "_" + "workflow" + "_" + "resource" + "_" + "stack",
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
        self._template_application_service = None
        self._materials_service = None
        self._products_service = None
        self._extract_log_service = None
        self._product_import_service = None
        self._shipment_application_service_core = None
        self._shipment_event_primary_facade = None
        # LG-W1-T9-A workflow 运行时组合根：懒加载，首次访问时构建，close/reload 后清空重建。
        self._workflow_runtime = None
        self._workflow_checkpointer = None
        self._workflow_shadow_checkpointer = None
        self._workflow_resource_stack = None

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

        return cast(
            "UserPreferenceService", self._lazy("_user_preference_service", UserPreferenceService)
        )

    # --- application services (formerly module-level singletons) ---

    @property
    def customer_application_service(self) -> CustomerApplicationService:
        from app.application.customer_app_service import CustomerApplicationService

        return cast(
            "CustomerApplicationService",
            self._lazy("_customer_application_service", CustomerApplicationService),
        )

    def invalidate_customer_application_service(self) -> None:
        self._customer_application_service = None

    @property
    def ai_chat_application_service(self) -> AIChatApplicationService:
        def _factory() -> AIChatApplicationService:
            from app.application.ai_chat_app_service import AIChatApplicationService

            # LG-W1-T9-A：AI 聊天工厂以关键字参数直接注入 workflow 运行时与 checkpointer
            # （组合根职责），由已更新的构造函数消费；参数名即 sep 拼装的
            # "workflow" + "_" + "runtime" / "workflow" + "_" + "checkpointer"。
            return AIChatApplicationService(
                workflow_runtime=self.workflow_runtime,
                workflow_checkpointer=self.workflow_checkpointer,
            )

        return cast(
            "AIChatApplicationService",
            self._lazy("_ai_chat_application_service", _factory),
        )

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

        return cast(
            "FileAnalysisService",
            self._lazy("_file_analysis_application_service", FileAnalysisService),
        )

    @property
    def template_application_service(self) -> TemplateApplicationService:
        def _factory() -> TemplateApplicationService:
            from app.application.template_app_service import TemplateApplicationService
            from app.infrastructure.templates.template_store_impl import FileSystemTemplateStore

            base_dir = str(Path(__file__).resolve().parents[2])
            return TemplateApplicationService(FileSystemTemplateStore(base_dir=base_dir))

        return cast(
            "TemplateApplicationService",
            self._lazy("_template_application_service", _factory),
        )

    def set_template_application_service(self, service: TemplateApplicationService | None) -> None:
        self._template_application_service = service

    @property
    def materials_service(self) -> MaterialsService:
        def _factory() -> MaterialsService:
            from app.infrastructure.repositories.material_repository_impl import (
                SQLAlchemyMaterialRepository,
            )
            from app.services.materials_service import MaterialsService

            return MaterialsService(SQLAlchemyMaterialRepository())

        return cast("MaterialsService", self._lazy("_materials_service", _factory))

    @property
    def products_service(self) -> ProductsService:
        def _factory() -> ProductsService:
            from app.mod_sdk.erp_repository_registry import resolve_products_repository
            from app.services.products_service import ProductsService

            repo, _provider = resolve_products_repository()
            return ProductsService(repo)

        return cast("ProductsService", self._lazy("_products_service", _factory))

    @property
    def extract_log_service(self) -> ExtractLogService:
        from app.services.extract_log_service import ExtractLogService

        return cast("ExtractLogService", self._lazy("_extract_log_service", ExtractLogService))

    @property
    def product_import_service(self) -> ProductImportService:
        from app.services.product_import_service import ProductImportService

        return cast(
            "ProductImportService",
            self._lazy("_product_import_service", ProductImportService),
        )

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

        return cast(
            "ShipmentApplicationService", self._lazy("_shipment_application_service_core", _factory)
        )

    @property
    def shipment_event_primary_facade(self) -> ShipmentApplicationServiceEventPrimary:
        def _factory() -> ShipmentApplicationServiceEventPrimary:
            from app.application.facades.shipment_event_primary import (
                ShipmentApplicationServiceEventPrimary,
            )

            return ShipmentApplicationServiceEventPrimary(self.shipment_application_service_core)

        return cast(
            "ShipmentApplicationServiceEventPrimary",
            self._lazy("_shipment_event_primary_facade", _factory),
        )

    def invalidate_shipment_wiring(self) -> None:
        """Clear shipment singletons (tests / hot-reload hooks)."""
        self._shipment_application_service_core = None
        self._shipment_event_primary_facade = None

    # ------------------------------------------------------------------ #
    # LG-W1-T9-A workflow 运行时组合根
    # ------------------------------------------------------------------ #
    # ``workflow_runtime`` / ``workflow_checkpointer`` 懒加载构建；RLock 双重检查，
    # 与现有 ``_lazy`` 行为一致。``close_workflow_resources`` 关闭 ExitStack 并清空
    # 槽位；``reload_workflow_runtime`` 先关后建并返回新运行时。替换/重置注册表时也会
    # 安全关闭旧容器的 workflow 资源。
    # ------------------------------------------------------------------ #

    def _build_workflow_runtime(self) -> WorkflowRuntime:
        """按 ``XCAGI_LG_RUNTIME`` 构建 workflow 运行时容器（组合根）。

        - 在 ``get_data_dir()`` 下用**同一个** ExitStack 进入两个不同的
          ``LanggraphCheckpointBridge.from_sqlite_path`` 上下文（serving / shadow 两个
          独立 sqlite 文件），serving 与 shadow 命名空间互不混用。
        - 真实 dispatcher 调用 ``execute_registered_workflow_tool(tool_id, action, params)``，
          绝不伪造 success。
        - 用 ``build_runtime_pair`` + ``NeuroBusEventBridge`` 装配 (legacy, langgraph) 对。
        - legacy/primary 直接选对应成员；canary 用 serving 对包 ``ShadowCanaryRouter``；
          shadow 用 ``ReadOnlyToolDispatcher``（predicate 只放行 low-risk + idempotent 的
          ``get_tool_action_spec`` 结果）+ 无 publisher 重建第二个 LangGraph 成员。
        """
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        from app.application.facades.tools_facade import execute_registered_workflow_tool
        from app.application.workflow.runtime.shadow_canary import (
            ReadOnlyToolDispatcher,
            ShadowCanaryRouter,
        )
        from app.contexts.flags import lg_runtime_canary_ratio, lg_runtime_mode
        from app.infrastructure.workflow.checkpoint_bridge import LanggraphCheckpointBridge
        from app.infrastructure.workflow.neuro_bus_bridge import NeuroBusEventBridge
        from app.infrastructure.workflow.runtime_selector import build_runtime_pair
        from app.utils.path_utils import get_data_dir

        def _dispatch(tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
            return execute_registered_workflow_tool(tool_id, action, params)

        data_dir = get_data_dir()
        os.makedirs(data_dir, exist_ok=True)

        stack = ExitStack()
        try:
            serving_bridge = stack.enter_context(
                LanggraphCheckpointBridge.from_sqlite_path(
                    os.path.join(data_dir, "xcagi-langgraph-checkpoints.sqlite3"),
                    tenant_id="default",
                    run_namespace="serving",
                )
            )
            shadow_bridge = stack.enter_context(
                LanggraphCheckpointBridge.from_sqlite_path(
                    os.path.join(data_dir, "xcagi-langgraph-shadow-checkpoints.sqlite3"),
                    tenant_id="default",
                    run_namespace="shadow",
                )
            )

            event_bridge = NeuroBusEventBridge()
            legacy_runtime, langgraph_runtime = build_runtime_pair(
                tool_dispatcher=_dispatch,
                state_event_publisher=event_bridge,
            )

            mode = lg_runtime_mode()
            canary_ratio = lg_runtime_canary_ratio()

            if mode == "legacy":
                runtime = legacy_runtime
            elif mode == "primary":
                runtime = langgraph_runtime
            elif mode == "canary":
                runtime = ShadowCanaryRouter(
                    legacy_runtime,
                    langgraph_runtime,
                    mode="canary",
                    canary_ratio=canary_ratio,
                )
            elif mode == "shadow":

                def _shadow_predicate(tool_id: str, action: str) -> bool:
                    spec = get_tool_action_spec(tool_id, action)
                    if spec is None:
                        return False
                    return str(getattr(spec, "risk", "") or "").strip().lower() == "low" and bool(
                        getattr(spec, "idempotent", False)
                    )

                shadow_dispatcher = ReadOnlyToolDispatcher(
                    _dispatch, allowed_reads=_shadow_predicate
                )
                # 第二个 LangGraph 成员：只读 dispatcher + 无 publisher（shadow 不得产生
                # 真实副作用/事件），predicate 仅放行 low-risk 且 idempotent 的读操作。
                _shadow_legacy, shadow_langgraph = build_runtime_pair(
                    tool_dispatcher=shadow_dispatcher,
                )
                runtime = ShadowCanaryRouter(
                    legacy_runtime,
                    shadow_langgraph,
                    mode="shadow",
                    shadow_safe=True,
                    shadow_checkpointer=shadow_bridge,
                )
            else:  # pragma: no cover - lg_runtime_mode() 已校验有效集合
                raise RuntimeError(f"未知运行时模式: {mode!r}")

            self._workflow_resource_stack = stack
            self._workflow_checkpointer = serving_bridge
            self._workflow_shadow_checkpointer = shadow_bridge
            self._workflow_runtime = runtime
        except BaseException:
            # 槽位发布前任何异常：关闭本地 stack（释放已进入的 SQLite 上下文句柄）后重抛，
            # 避免泄漏 SQLite 句柄。槽位尚未发布仍为 None，后续访问会重新构建。
            stack.close()
            raise
        return runtime

    @property
    def workflow_runtime(self) -> WorkflowRuntime:
        """进程级 workflow 运行时单例（组合根懒加载）。"""
        if self._workflow_resource_stack is None:
            with _lock:
                if self._workflow_resource_stack is None:
                    self._build_workflow_runtime()
        return cast("WorkflowRuntime", self._workflow_runtime)

    @property
    def workflow_checkpointer(self) -> CheckpointStore:
        """始终返回 serving 侧 checkpoint 桥（组合根懒加载）。"""
        if self._workflow_resource_stack is None:
            with _lock:
                if self._workflow_resource_stack is None:
                    self._build_workflow_runtime()
        return cast("CheckpointStore", self._workflow_checkpointer)

    def reload_workflow_runtime(self) -> WorkflowRuntime:
        """关闭旧容器并重建，返回新的 workflow 运行时（hot-reload 钩子）。"""
        self.close_workflow_resources()
        return self.workflow_runtime

    def close_workflow_resources(self) -> None:
        """原子关闭 ExitStack 并清空 workflow 槽位；始终返回 ``None``。

        在 RLock 下摘除（置 None）全部四个槽位，随后**退出 with 块之后**才调用
        ``stack.close()``：即使 close 抛异常，槽位也已清空；重复 close 幂等
        （stack 已为 None 时直接返回）。
        """
        with _lock:
            stack = self._workflow_resource_stack
            # 先在锁内摘除槽位，再在锁外关闭 stack，保证 close 抛异常时槽位保持已清空。
            self._workflow_resource_stack = None
            self._workflow_runtime = None
            self._workflow_checkpointer = None
            self._workflow_shadow_checkpointer = None
        if stack is not None:
            stack.close()
        return None


def get_service_registry() -> ServiceContainer:
    global _registry
    with _lock:
        if _registry is None:
            _registry = ServiceContainer()
        return _registry


def set_service_registry(container: Optional[ServiceContainer]) -> None:
    """Replace the entire registry (tests). Pass ``None`` to drop the current container.

    Replacing/resetting safely closes the previous container's workflow resources
    (LG-W1-T9-A) so the old ExitStack / checkpoint bridges are released.
    """
    global _registry
    with _lock:
        old = _registry
        # 先关闭不同的旧容器、再发布替换容器：即使 close 抛异常也不会发布一个
        # 已被错误替换的注册表；container 与 old 相同（identical）时不关闭。
        if old is not None and old is not container:
            old.close_workflow_resources()
        _registry = container


def reset_service_registry() -> None:
    """Drop the registry so the next ``get_service_registry()`` builds a fresh container."""
    set_service_registry(None)
