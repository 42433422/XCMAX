"""报表 V1 应用服务：HTTP 唯一入口。"""

from __future__ import annotations

from typing import Any

_report_app_service: "ReportApplicationService | None" = None


class ReportApplicationService:
    """报表用例编排（迁移期委托 ``ReportService``）。"""

    def __init__(self) -> None:
        from app.infrastructure.gateways.report_legacy import ReportService

        self._inner = ReportService()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def get_report_app_service() -> ReportApplicationService:
    global _report_app_service
    if _report_app_service is None:
        _report_app_service = ReportApplicationService()
    return _report_app_service
