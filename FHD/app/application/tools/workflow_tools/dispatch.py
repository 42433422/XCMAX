"""Ordered dispatch with explicit extension and built-in dependencies."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.application.tools.workflow_tools.contracts import (
    ExtensionHandler,
    JsonTool,
    Payload,
    ToolCall,
    ToolHandler,
)
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS


def parse_arguments(args: Payload | str) -> Payload:
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except RECOVERABLE_ERRORS:
            return {}
    return args if isinstance(args, dict) else {}


@dataclass(frozen=True)
class WorkflowToolDispatcher:
    capability_name: str
    capability: ToolHandler
    employee: ExtensionHandler
    native: ExtensionHandler
    template: ToolHandler
    legacy_employee: ExtensionHandler
    builtins: Mapping[str, ToolHandler]
    business_db: Callable[[str, Payload], Payload | None]
    resolve_crud: Callable[[str], JsonTool | None]
    logger: logging.Logger

    def execute(self, call: ToolCall) -> str:
        if call.name == self.capability_name:
            return self.capability(call)
        for label, handler in (("employee", self.employee), ("planner native", self.native)):
            result = self._extension(label, handler, call)
            if result is not None:
                return result
        if call.name == "template_preview":
            return self.template(call)
        result = self._extension("legacy employee planner", self.legacy_employee, call)
        if result is not None:
            return result
        builtin = self.builtins.get(call.name)
        if builtin is not None:
            return builtin(call)
        payload = self.business_db(call.name, call.args)
        if payload is not None:
            return json.dumps(payload, ensure_ascii=False, default=json_safe)
        crud = self.resolve_crud(call.name)
        if crud is not None:
            try:
                return json.dumps(crud(call.args), ensure_ascii=False, default=json_safe)
            except RECOVERABLE_ERRORS:
                return json.dumps(
                    {"success": False, "error": "tool_dispatch_failed"}, ensure_ascii=False
                )
        return json.dumps(
            {"success": False, "error": "unknown_tool", "tool": call.name}, ensure_ascii=False
        )

    def _extension(self, label: str, handler: ExtensionHandler, call: ToolCall) -> str | None:
        try:
            return handler(call)
        except RECOVERABLE_ERRORS:
            self.logger.debug("%s tool dispatch skipped", label, exc_info=True)
            return None
