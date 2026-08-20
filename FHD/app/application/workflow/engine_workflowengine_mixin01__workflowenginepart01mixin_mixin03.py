# mypy: disable-error-code="valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.workflow.engine")


class __WorkflowEnginePart01MixinPart03Mixin:
    @staticmethod
    def _attempt_summary(
        attempt: int, success: bool, error: str, started_perf: float
    ) -> dict[str, _facade().Any]:
        return {
            "attempt": attempt,
            "success": bool(success),
            "error": str(error or "")[:240],
            "duration_ms": _facade().WorkflowEngine._elapsed_ms(started_perf),
        }

    @staticmethod
    def _node_allows_auto_retry(node: _facade().WorkflowNode) -> bool:
        return bool(node.idempotent) or node.risk == "low"

    @staticmethod
    def _agentic_tool_allows_auto_retry(
        tool_registry: dict[str, _facade().Any], tool_id: str, action: str
    ) -> bool:
        spec = tool_registry.get(tool_id) if isinstance(tool_registry, dict) else None
        if not isinstance(spec, dict):
            return True
        actions = spec.get("actions") if isinstance(spec.get("actions"), dict) else {}
        meta = actions.get(action) if isinstance(actions, dict) else None
        if not isinstance(meta, dict):
            return True
        return bool(meta.get("idempotent")) or str(meta.get("risk") or "low") == "low"

    @staticmethod
    def _recovery_hint(
        *,
        tool_id: str,
        action: str,
        error: str,
        output: dict[str, _facade().Any] | None,
        retryable: bool,
    ) -> str:
        out = output if isinstance(output, dict) else {}
        message = str(error or out.get("message") or out.get("error") or "").strip()
        if out.get("pending_approval") or out.get("approval_required"):
            return "写操作已进入审批流；在审批工作台通过后重试或继续执行。"
        if out.get("requires_token"):
            token_name = str(out.get("token_name") or "DB_WRITE_TOKEN").strip()
            return f"缺少写库令牌 {token_name}；配置令牌或在受信任工作区内重试。"
        if out.get("available_employee_ids"):
            return "请从返回的 available_employee_ids 中选择员工 ID 后重新执行。"
        if "缺少 employee_id" in message:
            return "先执行 employee.list 查看可用员工，再带 employee_id 调用 employee.execute。"
        if "缺少" in message or "required" in message.lower():
            return "补齐提示中的必填参数后重新执行。"
        if not retryable:
            return "该节点可能产生副作用，系统未自动重试；请核对员工空间或数据库状态后手动重试。"
        if tool_id == "business_db" and action == "write":
            return "数据库写入失败；确认 entity/operation/payload 后重试，避免重复写入。"
        if message:
            return "可重试节点已耗尽自动重试；请检查参数、外部服务连接或稍后重试。"
        return ""

    @staticmethod
    def _merge_state_schema(
        runtime_context: dict[str, _facade().Any],
        result: _facade().NodeExecutionResult,
        schema: _facade().StateSchema,
    ) -> None:
        """用 StateSchema 校验/归并 runtime_context；校验失败记录到节点结果，不中断执行。"""
        try:
            _facade().apply_state_schema(runtime_context, schema)
        except ValueError as exc:
            msg = str(exc)
            result.error = (result.error + "; " if result.error else "") + msg
            _facade().logger.warning("StateSchema 校验失败 node=%s: %s", result.node_id, msg)
