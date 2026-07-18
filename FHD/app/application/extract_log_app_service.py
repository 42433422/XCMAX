"""
提取日志应用服务

负责提取日志管理相关的用例编排
"""

from typing import TYPE_CHECKING, Any, Optional

from app.di.registry import get_service_registry

if TYPE_CHECKING:
    from app.application.ports.extract_log_store import ExtractLogStorePort
    from app.services.extract_log_service import ExtractLogService


class ExtractLogApplicationService:
    """提取日志应用服务 - 负责提取日志相关的用例编排"""

    def __init__(
        self,
        store: Optional["ExtractLogStorePort"] = None,
    ):
        if store is None:
            from app.infrastructure.persistence.extract_log_store_impl import (
                SQLAlchemyExtractLogStore,
            )

            store = SQLAlchemyExtractLogStore()
        self._store = store

    def get_extract_logs(
        self, page: int = 1, per_page: int = 20, unit_name: str | None = None
    ) -> dict[str, Any]:
        return self._store.find_all(page=page, per_page=per_page, unit_name=unit_name)

    def get_extract_log(self, log_id: int) -> dict[str, Any]:
        result = self._store.find_by_id(log_id)
        if result is None:
            return {"success": False, "message": "日志不存在"}
        return {"success": True, "data": result}

    def create_extract_log(self, log_data: dict[str, Any]) -> dict[str, Any]:
        return self._store.create(log_data)

    def delete_extract_log(self, log_id: int) -> dict[str, Any]:
        return self._store.delete(log_id)

    def clear_old_logs(self, days: int = 30) -> dict[str, Any]:
        return self._store.clear_old(days=days)


from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

instrument_application_service_class(ExtractLogApplicationService)

_extract_log_application_service: ExtractLogApplicationService | None = None


def get_extract_log_app_service() -> "ExtractLogService":
    """返回 Excel 提取路由使用的日志服务。

    这些兼容路由仍使用 ``create_log/update_log/get_logs/get_log`` 契约；
    ``ExtractLogApplicationService`` 则暴露新的 DDD 用例契约。二者之前被
    误接，导致路由在运行时调用不存在的方法。注册表本来就维护了兼容
    ``ExtractLogService``，这里应从注册表取它，而不是另建错误单例。
    """
    return get_service_registry().extract_log_service


def get_extract_log_application_service() -> "ExtractLogApplicationService":
    """获取 DDD 提取日志应用服务单例。"""
    global _extract_log_application_service
    if _extract_log_application_service is None:
        _extract_log_application_service = ExtractLogApplicationService()
    return _extract_log_application_service


def init_extract_log_application_service(
    store: "ExtractLogStorePort",
) -> "ExtractLogApplicationService":
    """初始化提取日志应用服务 (用于依赖注入)"""
    global _extract_log_application_service
    _extract_log_application_service = ExtractLogApplicationService(store=store)
    return _extract_log_application_service


def init_extract_log_app_service(
    store: "ExtractLogStorePort",
) -> "ExtractLogApplicationService":
    """初始化提取日志应用服务 (用于依赖注入) (别名)"""
    return init_extract_log_application_service(store)
