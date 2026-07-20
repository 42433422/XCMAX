"""
提取日志应用服务

负责提取日志管理相关的用例编排
"""

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.application.ports.extract_log_store import ExtractLogStorePort


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

    # Compatibility API used by the Excel import routes.  Keep it here so the
    # route layer does not depend on the legacy services package.
    def create_log(
        self,
        file_name: str,
        data_type: str,
        file_path: str | None = None,
        total_rows: int = 0,
        field_mapping: dict | None = None,
    ) -> int:
        result = self.create_extract_log(
            {
                "file_name": file_name,
                "file_path": file_path,
                "data_type": data_type,
                "total_rows": total_rows,
                "field_mapping": field_mapping,
            }
        )
        return int(result.get("log_id") or -1)

    def update_log(self, log_id: int, status: str, **fields: Any) -> bool:
        result = self._store.update(log_id, {"status": status, **fields})
        return bool(result.get("success"))

    def get_log(self, log_id: int) -> dict[str, Any] | None:
        return self._store.find_by_id(log_id)

    def get_logs(
        self,
        data_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        result = self._store.find_all(page=1, per_page=max(offset + limit, 1))
        rows = list(result.get("data") or [])
        if data_type:
            rows = [row for row in rows if row.get("data_type") == data_type]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    def delete_extract_log(self, log_id: int) -> dict[str, Any]:
        return self._store.delete(log_id)

    def clear_old_logs(self, days: int = 30) -> dict[str, Any]:
        return self._store.clear_old(days=days)


from app.neuro_bus.neuro_application_instrumentation import instrument_application_service_class

instrument_application_service_class(ExtractLogApplicationService)

_extract_log_app_service: ExtractLogApplicationService | None = None


def get_extract_log_app_service() -> "ExtractLogApplicationService":
    """获取提取日志应用服务单例"""
    global _extract_log_app_service
    if _extract_log_app_service is None:
        _extract_log_app_service = ExtractLogApplicationService()
    return _extract_log_app_service


def get_extract_log_application_service() -> "ExtractLogApplicationService":
    """获取提取日志应用服务单例 (别名)"""
    return get_extract_log_app_service()


def init_extract_log_application_service(
    store: "ExtractLogStorePort",
) -> "ExtractLogApplicationService":
    """初始化提取日志应用服务 (用于依赖注入)"""
    global _extract_log_app_service
    _extract_log_app_service = ExtractLogApplicationService(store=store)
    return _extract_log_app_service


def init_extract_log_app_service(
    store: "ExtractLogStorePort",
) -> "ExtractLogApplicationService":
    """初始化提取日志应用服务 (用于依赖注入) (别名)"""
    return init_extract_log_application_service(store)
