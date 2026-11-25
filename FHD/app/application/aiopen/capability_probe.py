"""Verify discovery → controlled read → original task receipt without business writes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.types import ASGIApp

from .protocols import CursorHub, ToolCall
from .runtime import RuntimeState


class CapabilityProbe:
    def __init__(
        self,
        state: RuntimeState,
        catalog: Callable[[], dict[str, Any]],
        operation_call: ToolCall,
        cursor: Callable[[], CursorHub],
    ) -> None:
        self._state = state
        self._catalog = catalog
        self._operation_call = operation_call
        self._cursor = cursor

    def run(self, app: ASGIApp, args: dict[str, Any]) -> dict[str, Any]:
        catalog = self._catalog()
        entries = [row for row in catalog.get("capabilities") or [] if isinstance(row, dict)]
        requested = str(args.get("operation_id") or "")
        candidates = [
            row for row in entries if row.get("read_only") is True and row.get("risk") == "low"
        ]
        selected = (
            next((row for row in candidates if row.get("operation_id") == requested), None)
            if requested
            else next((row for row in candidates if not row.get("required_params")), None)
        )
        steps: list[dict[str, Any]] = [
            {
                "step": "api_catalog",
                "ok": catalog.get("success") is True,
                "capability_count": len(entries),
            }
        ]
        receipt: dict[str, Any] = {}
        if selected is not None and catalog.get("success") is True:
            receipt = self._operation_call(
                app,
                {
                    "operation_id": selected["operation_id"],
                    "params": args.get("params", {}),
                    "request_id": args.get("request_id"),
                },
            )
        verified = (
            receipt.get("success") is True
            and receipt.get("execution_state") == "completed"
            and bool(receipt.get("run_id"))
        )
        steps.append(
            {
                "step": "operation_call",
                "ok": verified,
                "operation_id": selected.get("operation_id") if selected else None,
                "run_id": receipt.get("run_id"),
                "task_id": receipt.get("task_id"),
                "execution_state": receipt.get("execution_state", "not_started"),
                "message": receipt.get("message")
                or "仅探测当前账号可用的明确只读能力；写动作不能用作自检。",
            }
        )
        sessions = self._cursor().sessions_info()
        ready = self._state.remote_control_enabled and bool(sessions)
        return {
            "success": verified,
            "closed_loop": verified,
            "verification_scope": "capability_discovery_read_execution_receipt",
            "ui_loop_ready": ready,
            "steps": steps,
            "hint": "只读能力执行回执已核验"
            if verified
            else "能力自检未完成，请检查当前账号授权和原任务回执。",
        }
