"""Build tool contracts and compose optional employee capabilities."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

from app.application.tools.workflow_tools.contracts import Payload
from app.utils.operational_errors import RECOVERABLE_ERRORS


def tool_spec(
    name: str,
    description: str,
    properties: Payload,
    required: list[str] | None = None,
    *,
    risk_level: Literal["low", "medium", "high"] | None = None,
) -> Payload:
    parameters: Payload = {"type": "object", "properties": properties}
    if required is not None:
        parameters["required"] = required
    spec: Payload = {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }
    if risk_level is not None:
        spec["risk_level"] = risk_level
    return spec


def compose_registry(
    base: list[Payload],
    extend: Callable[[list[Payload]], list[Payload]],
    employee_tools: Callable[[], list[Payload]],
    logger: logging.Logger,
) -> list[Payload]:
    registry = extend(base)
    try:
        employees = employee_tools()
        if employees:
            registry = registry + employees
    except RECOVERABLE_ERRORS:
        logger.debug("employee pack tools merge skipped", exc_info=True)
    registry.append(
        tool_spec(
            "products_bulk_import",
            "批量导入产品数据到数据库。",
            {
                "file_path": {"type": "string", "description": "Excel 文件路径"},
                "sheet_name": {"type": "string", "description": "工作表名称"},
                "mapping": {"type": "object", "description": "列名映射配置"},
            },
            ["file_path"],
        )
    )
    return registry
