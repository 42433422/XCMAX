"""Create post-response traces without interpreting model output as execution."""

from __future__ import annotations

from typing import Any

from .run_models import AgentRun
from .run_repository import AgentRunRepository
from .task_context import apply_task_context
from .trace_payloads import (
    _iter_payload_dicts,
    _payload_data,
    _payload_error_message,
    _payload_status,
    _resolved_user_id,
    _trace_safe_value,
)
from .trace_recording import TraceRecorder


class TraceRunService:
    def __init__(self, repository: AgentRunRepository, recording: TraceRecorder) -> None:
        self.repository = repository
        self.recording = recording

    @staticmethod
    def _contains_unplanned_tool_request(
        payload: dict[str, Any], *, allow_redacted_external_receipt: bool
    ) -> bool:
        for item in _iter_payload_dicts(payload):
            if item.get("action") == "tool_call":
                return True
            if any(
                isinstance(item.get(key), dict)
                for key in ("toolCall", "tool_call", "tool_call_payload")
            ):
                return True
            auto_action = item.get("autoAction") or item.get("auto_action")
            if isinstance(auto_action, dict) and auto_action.get("type") == "tool_call":
                return True
            if not allow_redacted_external_receipt and any(
                isinstance(item.get(key), list) and item.get(key)
                for key in ("legacy_tool_records", "_tool_records", "tool_records")
            ):
                return True
        return False

    def create(
        self,
        payload: dict[str, Any],
        *,
        message: str,
        runtime_context: dict[str, Any] | None = None,
        user_id: str | None = None,
        source: str | None = None,
        channel: str = "compat_chat",
        intent: str = "chat_reply",
    ) -> AgentRun:
        unplanned_tool_request = self._contains_unplanned_tool_request(
            payload, allow_redacted_external_receipt=intent == "aiopen_tool_call"
        )
        if unplanned_tool_request:
            # Tool calls can only be executed from a model plan that passed the
            # deterministic graph checker and entered AgentOrchestrator. A
            # response-side tool_call or legacy record is not an execution receipt.
            message_text = "模型返回了未经计划校验的工具请求，本次未执行；请重新提交具体业务需求。"
            data = _payload_data(payload)
            llm_trace = data.get("llm_trace") if isinstance(data.get("llm_trace"), dict) else None
            payload = {
                "success": False,
                "execution_state": "failed",
                "message": message_text,
                "response": message_text,
                "data": {
                    "text": message_text,
                    "action": "unplanned_tool_call_rejected",
                    "execution_started": False,
                    **({"llm_trace": llm_trace} if llm_trace else {}),
                },
            }

        status = _payload_status(payload)
        resolved_user_id = _resolved_user_id(runtime_context=runtime_context, user_id=user_id)
        response_text = str(payload.get("response") or _payload_data(payload).get("text") or "")
        run = AgentRun(
            user_id=resolved_user_id,
            message=str(message or ""),
            status=status,
            intent=str(intent or "chat_reply").strip() or "chat_reply",
            metadata={
                "channel": channel,
                "source": str(source or "").strip(),
                "trace_mode": "post_execution",
                "runtime_context": _trace_safe_value(runtime_context or {}),
            },
            final_output={"chat_payload": _trace_safe_value(payload)},
        )
        apply_task_context(run, runtime_context)
        run.add_event(
            "run.created",
            "Chat 请求已进入 AgentRun 追踪",
            {"channel": channel, "source": str(source or "").strip()},
        )
        self.recording.enrich(run, payload, query=message)
        self.recording.finalize(run)

        if unplanned_tool_request:
            run.status = "failed"
            run.error = "unplanned_tool_call_rejected"
            run.add_event(
                "tool.request_rejected",
                "未校验的模型工具请求未执行",
                {"execution_started": False},
            )
        else:
            from app.application.agent_orchestrator.business_harness import (
                mark_unexecuted_order_run,
            )

            if mark_unexecuted_order_run(run, message):
                from app.application.agent_orchestrator.business_harness import (
                    guard_unexecuted_payload,
                )

                status = "failed"
                payload = guard_unexecuted_payload(run, payload)
                response_text = str(payload.get("response") or "")
                run.final_output["chat_payload"] = _trace_safe_value(payload)
                run.status = status

        if run.status == "waiting_user":
            run.add_event(
                "step.waiting_user",
                str(payload.get("message") or "等待用户授权"),
                {
                    "token_name": payload.get("token_name")
                    or _payload_data(payload).get("token_name"),
                    "token_description": payload.get("token_description")
                    or _payload_data(payload).get("token_description"),
                },
            )
        elif run.status == "failed":
            run.error = run.error or _payload_error_message(payload)
            run.add_event("run.failed", run.error, {"response_preview": response_text[:500]})
        elif run.status == "completed":
            run.add_event(
                "run.completed", "Chat 响应已完成", {"response_preview": response_text[:500]}
            )
        else:
            self._record_unfinished(run, payload)
        return self.repository.save(run)

    @staticmethod
    def _record_unfinished(run: AgentRun, payload: dict[str, Any]) -> None:
        if run.status == "blocked":
            run.metadata["non_retryable"] = True
            run.metadata["recovery"] = {
                **dict(run.metadata.get("recovery") or {}),
                "state": "manual_reconciliation_required",
                "error_code": "chat_result_unconfirmed",
            }
        run.add_event(
            f"run.{run.status}",
            str(payload.get("message") or "任务尚未完成，请查询原执行结果"),
            {"status": run.status},
        )
