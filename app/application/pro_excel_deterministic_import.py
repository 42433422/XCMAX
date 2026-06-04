"""专业版 Excel 规则入库写库循环门面。"""

from __future__ import annotations

from typing import Any


def run_deterministic_excel_import(
    service: Any,
    user_message: str,
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """调用服务内规则入库分支（与 _try_handle_dynamic_workflow 中 import_pipeline 路径一致）。"""
    return service._try_handle_dynamic_workflow(user_message, context, source="pro")
