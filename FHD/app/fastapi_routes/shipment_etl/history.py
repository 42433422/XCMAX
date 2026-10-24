"""Read extraction history through its own query interface."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.responses import JSONResponse

from app.fastapi_routes.shipment_etl.ports import ExtractionHistory
from app.fastapi_routes.shipment_etl.responses import EtlResponses
from app.utils.operational_errors import RECOVERABLE_ERRORS


class HistoryViews:
    def __init__(self, history: Callable[[], ExtractionHistory], responses: EtlResponses) -> None:
        self._history = history
        self._responses = responses

    def list(
        self, data_type: str | None, status: str | None, limit: int, offset: int
    ) -> JSONResponse:
        try:
            logs = self._history().get_logs(
                data_type=data_type, status=status, limit=limit, offset=offset
            )
            return JSONResponse({"success": True, "logs": logs, "total": len(logs)})
        except RECOVERABLE_ERRORS:
            return self._responses.unavailable("获取提取日志失败", "获取失败，请稍后重试")

    def detail(self, log_id: int, *, preview: bool = False) -> JSONResponse:
        try:
            log = self._history().get_log(log_id)
            if not log:
                return JSONResponse({"success": False, "message": "日志不存在"}, status_code=404)
            result = {"success": True, "log": log}
            if preview:
                result["message"] = "预览数据需要从提取源获取"
            return JSONResponse(result)
        except RECOVERABLE_ERRORS:
            return self._responses.unavailable(
                "获取预览失败" if preview else "获取提取日志详情失败", "获取失败，请稍后重试"
            )
