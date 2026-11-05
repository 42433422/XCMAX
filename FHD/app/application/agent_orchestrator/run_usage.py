"""Tool/model charges, compensation and run usage summaries.

This component owns no execution or planner state. Its only mutable inputs are
explicit AgentRun/ToolCall records, so accounting can be exercised independently.
"""

from __future__ import annotations

from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, LLMCall, ToolCall
from app.application.agent_orchestrator.runtime_dependencies import RuntimeDependencies
from app.utils.operational_errors import RECOVERABLE_ERRORS


class RunUsageLedger:
    def __init__(self, dependencies: RuntimeDependencies) -> None:
        self.dependencies = dependencies

    def record_tool_usage_entry(self, run: AgentRun, tool_call: ToolCall) -> bool:
        if tool_call.cost_units <= 0:
            tool_call.metadata["usage_ledger"] = {"status": "not_required", "cost_units": 0}
            return True
        if isinstance(tool_call.metadata.get("usage_ledger"), dict):
            return True
        try:
            from app.infrastructure.billing.model_usage import record_tool_usage

            entry = record_tool_usage(
                run_id=run.run_id,
                user_id=run.user_id,
                tool_id=tool_call.tool_id,
                action=tool_call.action,
                call_id=tool_call.call_id,
                permission=tool_call.permission,
                status="pre_execution",
                cost_units=tool_call.cost_units,
                source="agent_orchestrator.tool_call",
                usage_key=f"{run.run_id}:{tool_call.call_id}:tool_call",
                metadata={
                    "step_id": tool_call.step_id,
                    "node_id": tool_call.node_id,
                    "attempt_count": tool_call.metadata.get("attempt_count"),
                    "risk": tool_call.metadata.get("risk"),
                    "idempotent": tool_call.metadata.get("idempotent"),
                },
            )
        except RECOVERABLE_ERRORS as exc:
            tool_call.metadata["usage_ledger"] = {"status": "failed", "message": str(exc)}
            run.metadata["tool_usage_ledger_status"] = "failed"
            run.add_event(
                "billing.record_failed",
                "工具调用用量账本写入失败",
                {
                    "call_id": tool_call.call_id,
                    "tool_id": tool_call.tool_id,
                    "action": tool_call.action,
                    "cost_units": tool_call.cost_units,
                    "error": str(exc),
                },
            )
            return True
        tool_call.metadata["usage_ledger"] = {
            "usage_id": entry.get("usage_id"),
            "usage_key": entry.get("usage_key"),
            "entry_type": entry.get("entry_type"),
            "status": "recorded",
        }
        wallet_debit = (
            entry.get("wallet_debit") if isinstance(entry.get("wallet_debit"), dict) else {}
        )
        if wallet_debit:
            tool_call.metadata["wallet_debit"] = wallet_debit
        tool_call.metadata["billing_status"] = entry.get("billing_status")
        tool_call.metadata["billing_source"] = entry.get("billing_source")
        self.refresh_tool_usage_metadata(run, entry)
        event_payload = {
            "usage_id": entry.get("usage_id"),
            "call_id": tool_call.call_id,
            "tool_id": tool_call.tool_id,
            "action": tool_call.action,
            "cost_units": entry.get("cost_units"),
            "billing_status": entry.get("billing_status"),
            "billing_source": entry.get("billing_source"),
            "wallet_debit": wallet_debit,
            "source": "agent_orchestrator.tool_call",
        }
        billing_status = str(entry.get("billing_status") or "")
        wallet_payload: dict[str, Any] = (
            dict(wallet_debit) if isinstance(wallet_debit, dict) else {}
        )
        if billing_status == "debited":
            self.refresh_wallet_balance_metadata(run, wallet_payload)
            run.add_event("billing.debited", "工具调用用量已从 AI 钱包扣减", event_payload)
            return True
        if billing_status == "insufficient_balance":
            self.refresh_wallet_balance_metadata(run, wallet_payload)
            run.status = "failed"
            run.error = "AI tool wallet balance insufficient"
            run.add_event("billing.insufficient_balance", run.error, event_payload)
            return False
        if billing_status == "market_debit_failed":
            run.status = "failed"
            run.error = "AI tool market wallet debit failed"
            run.add_event("billing.debit_failed", run.error, event_payload)
            return False
        run.add_event("billing.recorded", "工具调用用量已写入 AI 账本", event_payload)
        return True

    def record_tool_usage_refund(self, run: AgentRun, tool_call: ToolCall, *, reason: str) -> None:
        usage_ledger = (
            tool_call.metadata.get("usage_ledger")
            if isinstance(tool_call.metadata.get("usage_ledger"), dict)
            else {}
        )
        if not isinstance(usage_ledger, dict):
            usage_ledger = {}
        usage_key = str(usage_ledger.get("usage_key") or "")
        if not usage_key or isinstance(tool_call.metadata.get("wallet_refund"), dict):
            return
        try:
            from app.infrastructure.billing.model_usage import refund_tool_usage

            entry = refund_tool_usage(
                usage_key=usage_key, refund_key=f"{usage_key}:refund", reason=reason
            )
        except RECOVERABLE_ERRORS as exc:
            tool_call.metadata["wallet_refund"] = {"status": "failed", "message": str(exc)}
            run.add_event(
                "billing.refund_failed",
                "工具调用失败补偿记录失败",
                {
                    "call_id": tool_call.call_id,
                    "tool_id": tool_call.tool_id,
                    "action": tool_call.action,
                    "usage_key": usage_key,
                    "error": str(exc),
                },
            )
            return
        refund = entry.get("refund") if isinstance(entry.get("refund"), dict) else {}
        if not refund:
            return
        tool_call.metadata["wallet_refund"] = refund
        self.refresh_tool_refund_metadata(run, refund)
        self.refresh_wallet_balance_metadata(run, refund)
        status = str(refund.get("status") or "")
        event_type = (
            "billing.refunded"
            if status == "refunded"
            else "billing.refund_pending"
            if status == "refund_pending"
            else "billing.refund_recorded"
        )
        run.add_event(
            event_type,
            "工具调用失败已记录补偿",
            {
                "call_id": tool_call.call_id,
                "tool_id": tool_call.tool_id,
                "action": tool_call.action,
                "usage_key": usage_key,
                "refund_status": status,
                "cost_units": refund.get("cost_units"),
                "wallet_refund": refund,
            },
        )

    @staticmethod
    def refresh_wallet_balance_metadata(run: AgentRun, wallet_debit: dict[str, Any]) -> None:
        if "balance_after_units" in wallet_debit:
            run.metadata["model_wallet_balance_units"] = wallet_debit.get("balance_after_units", 0)
            run.metadata["ai_wallet_balance_units"] = wallet_debit.get("balance_after_units", 0)
        if "balance_after_yuan" in wallet_debit:
            run.metadata["model_wallet_balance_yuan"] = wallet_debit.get("balance_after_yuan")
            run.metadata["ai_wallet_balance_yuan"] = wallet_debit.get("balance_after_yuan")

    @staticmethod
    def refresh_tool_usage_metadata(run: AgentRun, entry: dict[str, Any]) -> None:
        run.metadata["tool_usage_entry_count"] = (
            int(run.metadata.get("tool_usage_entry_count") or 0) + 1
        )
        run.metadata["tool_usage_cost_units_total"] = int(
            run.metadata.get("tool_usage_cost_units_total") or 0
        ) + int(entry.get("cost_units") or 0)
        run.metadata["tool_usage_ledger_status"] = "recorded"

    @staticmethod
    def refresh_tool_refund_metadata(run: AgentRun, refund: dict[str, Any]) -> None:
        run.metadata["tool_usage_refund_count"] = (
            int(run.metadata.get("tool_usage_refund_count") or 0) + 1
        )
        if str(refund.get("status") or "") == "refunded":
            run.metadata["tool_usage_refund_cost_units_total"] = int(
                run.metadata.get("tool_usage_refund_cost_units_total") or 0
            ) + int(refund.get("cost_units") or 0)
        run.metadata["tool_usage_refund_status"] = str(refund.get("status") or "")

    @staticmethod
    def cost_units_total(run: AgentRun) -> int:
        return sum(int(call.cost_units or 0) for call in run.tool_calls)

    def step_cost_units(self, step: AgentStep) -> int:
        spec = self.dependencies.action_spec(step.tool_id, step.action)
        try:
            return int(getattr(spec, "cost_units", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def refresh_run_cost_metadata(self, run: AgentRun) -> None:
        run.metadata["tool_call_count"] = len(run.tool_calls)
        run.metadata["cost_units_total"] = self.cost_units_total(run)
        run.metadata["ai_cost_units_total"] = int(run.metadata["cost_units_total"]) + int(
            run.metadata.get("llm_cost_units_total") or 0
        )
        self.dependencies.refresh_budget(run)

    def record_repair_llm_call(
        self, run: AgentRun, step: AgentStep, advice: dict[str, Any]
    ) -> bool:
        call = advice.get("llm_call")
        if not isinstance(call, LLMCall):
            return True
        call.metadata = {
            **dict(call.metadata or {}),
            "run_id": run.run_id,
            "step_id": step.step_id,
            "node_id": step.node_id,
            "tool_id": step.tool_id,
            "action": step.action,
            "repair_attempt": len(step.repair_history) + 1,
        }
        run.llm_calls.append(call)
        run.add_event(
            "llm.completed" if call.status == "completed" else "llm.failed",
            "LLM 修复建议已生成" if call.status == "completed" else "LLM 修复建议生成失败",
            {
                "llm_call_id": call.call_id,
                "provider_id": call.provider_id,
                "provider": call.provider,
                "model": call.model,
                "total_tokens": call.total_tokens,
                "cost_units": call.cost_units,
                "source": "agent_orchestrator.llm_repair",
            },
        )
        if call.status == "failed":
            self.refresh_llm_metadata(run)
            return False
        try:
            from app.infrastructure.billing.model_usage import record_model_usage

            entry = record_model_usage(
                run_id=run.run_id,
                user_id=run.user_id,
                provider_id=call.provider_id,
                provider=call.provider,
                model=call.model,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                total_tokens=call.total_tokens,
                cost_units=call.cost_units,
                billing_status=call.billing_status,
                billing_source=call.billing_source,
                source="agent_orchestrator.llm_repair",
                usage_key=f"{run.run_id}:{step.step_id}:{step.attempt_count}:llm_repair",
                metadata=call.metadata,
            )
            call.metadata["usage_ledger"] = {
                "usage_id": entry.get("usage_id"),
                "usage_key": entry.get("usage_key"),
                "status": "recorded",
            }
            call.billing_status = str(entry.get("billing_status") or call.billing_status)
            call.billing_source = str(entry.get("billing_source") or call.billing_source)
            call.metadata["wallet_debit"] = entry.get("wallet_debit")
            self.refresh_model_usage_metadata(run, entry)
            billing_event = (
                "billing.debited"
                if call.billing_status == "debited"
                else "billing.insufficient_balance"
                if call.billing_status == "insufficient_balance"
                else "billing.recorded"
            )
            run.add_event(
                billing_event,
                "LLM 修复模型用量已记录",
                {
                    "llm_call_id": call.call_id,
                    "usage_id": entry.get("usage_id"),
                    "cost_units": call.cost_units,
                    "billing_status": call.billing_status,
                    "billing_source": call.billing_source,
                    "source": "agent_orchestrator.llm_repair",
                },
            )
        except RECOVERABLE_ERRORS as exc:
            call.metadata["usage_ledger"] = {"status": "failed", "message": str(exc)}
            run.add_event(
                "billing.record_failed",
                "LLM 修复模型用量记录失败",
                {"llm_call_id": call.call_id, "error": str(exc)},
            )
        self.refresh_llm_metadata(run)
        return call.billing_status != "insufficient_balance"

    @staticmethod
    def refresh_model_usage_metadata(run: AgentRun, entry: dict[str, Any]) -> None:
        run.metadata["model_usage_entry_count"] = (
            int(run.metadata.get("model_usage_entry_count") or 0) + 1
        )
        run.metadata["model_usage_cost_units_total"] = int(
            run.metadata.get("model_usage_cost_units_total") or 0
        ) + int(entry.get("cost_units") or 0)
        run.metadata["model_usage_ledger_status"] = "recorded"

    def refresh_llm_metadata(self, run: AgentRun) -> None:
        run.metadata["llm_call_count"] = len(run.llm_calls)
        run.metadata["llm_prompt_tokens_total"] = sum(
            int(call.prompt_tokens or 0) for call in run.llm_calls
        )
        run.metadata["llm_completion_tokens_total"] = sum(
            int(call.completion_tokens or 0) for call in run.llm_calls
        )
        run.metadata["llm_token_total"] = sum(int(call.total_tokens or 0) for call in run.llm_calls)
        run.metadata["llm_cost_units_total"] = sum(
            int(call.cost_units or 0) for call in run.llm_calls
        )
        if run.llm_calls:
            last = run.llm_calls[-1]
            run.metadata["llm_provider"] = last.provider or last.provider_id
            run.metadata["llm_model"] = last.model
        self.refresh_run_cost_metadata(run)

    @staticmethod
    def append_llm_summary_to_final_output(run: AgentRun) -> None:
        final_output = dict(run.final_output or {})
        if run.llm_calls:
            final_output["llm_calls"] = [call.to_dict() for call in run.llm_calls]
            final_output["llm_token_total"] = run.metadata.get("llm_token_total", 0)
            final_output["llm_cost_units_total"] = run.metadata.get("llm_cost_units_total", 0)
        if "tool_usage_entry_count" in run.metadata:
            final_output["tool_usage_entry_count"] = run.metadata.get("tool_usage_entry_count", 0)
            final_output["tool_usage_cost_units_total"] = run.metadata.get(
                "tool_usage_cost_units_total", 0
            )
            final_output["tool_usage_ledger_status"] = run.metadata.get(
                "tool_usage_ledger_status", ""
            )
        if "tool_usage_refund_count" in run.metadata:
            final_output["tool_usage_refund_count"] = run.metadata.get("tool_usage_refund_count", 0)
            final_output["tool_usage_refund_cost_units_total"] = run.metadata.get(
                "tool_usage_refund_cost_units_total", 0
            )
            final_output["tool_usage_refund_status"] = run.metadata.get(
                "tool_usage_refund_status", ""
            )
        final_output["ai_cost_units_total"] = run.metadata.get("ai_cost_units_total", 0)
        run.final_output = final_output

    @staticmethod
    def refresh_repair_metadata(run: AgentRun) -> None:
        run.metadata["observation_count"] = sum(len(step.observations) for step in run.steps)
        run.metadata["repair_count"] = sum(len(step.repair_history) for step in run.steps)
