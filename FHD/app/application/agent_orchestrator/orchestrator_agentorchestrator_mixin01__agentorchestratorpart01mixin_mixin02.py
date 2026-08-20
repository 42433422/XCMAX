# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.orchestrator")


class __AgentOrchestratorPart01MixinPart02Mixin:
    def _execute_step(
        self,
        run: _facade().AgentRun,
        step: _facade().AgentStep,
        *,
        runtime_context: dict[str, _facade().Any],
        node_outputs: dict[str, _facade().Any],
    ) -> None:
        started = _facade().time.perf_counter()
        step.attempt_count += 1
        step.status = "running"
        step.started_at = _facade().utc_now_iso()
        run.status = "running"
        attempt_count = step.attempt_count
        spec = _facade().get_tool_action_spec(step.tool_id, step.action)
        tool_call = _facade().ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=_facade().copy.deepcopy(step.params or {}),
            cost_units=int(getattr(spec, "cost_units", 0) or 0),
            permission=str(getattr(spec, "permission", "") or ""),
            metadata={
                "risk": step.risk,
                "idempotent": step.idempotent,
                "timeout_seconds": int(getattr(spec, "timeout_seconds", 0) or 0),
                "attempt_count": attempt_count,
            },
        )
        run.tool_calls.append(tool_call)
        self._refresh_run_cost_metadata(run)
        run.add_event(
            "tool.started",
            f"开始执行 {step.tool_id}.{step.action}",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": tool_call.call_id,
                "cost_units": tool_call.cost_units,
                "permission": tool_call.permission,
                "attempt_count": attempt_count,
            },
        )
        self._repo.save(run)
        ctx = dict(runtime_context or {})
        ctx.update(
            {
                "run_id": run.run_id,
                "step_id": step.step_id,
                "node_id": step.node_id,
                "message": run.message,
                "user_id": run.user_id,
                "node_outputs": dict(node_outputs),
                **_facade().task_execution_context(run, step),
            }
        )
        tool_call.metadata["idempotency_key"] = ctx["idempotency_key"]
        validation = _facade().validate_tool_call(step.tool_id, step.action, step.params)
        if not validation.ok:
            output = {
                "success": False,
                "error_code": validation.error_code,
                "message": validation.message,
                "tool_id": validation.tool_id,
                "action": validation.action,
            }
        elif not self._record_tool_usage_entry(run, tool_call):
            output = {
                "success": False,
                "error_code": "tool_billing_blocked",
                "message": run.error or "AI tool billing failed",
                "tool_id": step.tool_id,
                "action": step.action,
            }
        else:
            try:
                output = self._tool_executor.execute(step, runtime_context=ctx)
            except _facade().RECOVERABLE_ERRORS as exc:
                output = {"success": False, "error_code": "tool_exception", "message": str(exc)}
        step.output = dict(output or {})
        step.finished_at = _facade().utc_now_iso()
        step.duration_ms = int((_facade().time.perf_counter() - started) * 1000)
        tool_call.output = _facade().copy.deepcopy(step.output)
        tool_call.finished_at = step.finished_at
        tool_call.duration_ms = step.duration_ms
        self._attach_artifacts_from_payload(
            run,
            step.output,
            source=f"{step.tool_id}.{step.action}",
            extra_metadata={"step_id": step.step_id, "call_id": tool_call.call_id},
        )
        success = bool(step.output.get("success", False))
        observation = self._record_observation(run, step, tool_call=tool_call, success=success)
        if success:
            step.status = "completed"
            tool_call.status = "completed"
            self._refresh_run_cost_metadata(run)
            node_outputs[step.node_id] = step.output
            run.add_event(
                "tool.completed",
                f"完成 {step.tool_id}.{step.action}",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": tool_call.call_id,
                    "duration_ms": step.duration_ms,
                    "cost_units": tool_call.cost_units,
                    "attempt_count": attempt_count,
                    "observation_id": observation.get("observation_id"),
                },
            )
            return
        step.status = "failed"
        step.error = str(step.output.get("message") or step.output.get("error") or "tool failed")
        tool_call.status = "failed"
        tool_call.error = step.error
        if str(step.output.get("error_code") or "") != "tool_billing_blocked":
            self._record_tool_usage_refund(run, tool_call, reason=step.error)
        self._refresh_run_cost_metadata(run)
        run.add_event(
            "tool.failed",
            f"{step.tool_id}.{step.action} 执行失败",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "call_id": tool_call.call_id,
                "error": step.error,
                "duration_ms": step.duration_ms,
                "cost_units": tool_call.cost_units,
                "attempt_count": attempt_count,
                "observation_id": observation.get("observation_id"),
            },
        )

    def _record_tool_usage_entry(
        self, run: _facade().AgentRun, tool_call: _facade().ToolCall
    ) -> bool:
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
        except _facade().RECOVERABLE_ERRORS as exc:
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
        self._refresh_tool_usage_metadata(run, entry)
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
        wallet_payload: dict[str, _facade().Any] = (
            dict(wallet_debit) if isinstance(wallet_debit, dict) else {}
        )
        if billing_status == "debited":
            self._refresh_wallet_balance_metadata(run, wallet_payload)
            run.add_event("billing.debited", "工具调用用量已从 AI 钱包扣减", event_payload)
            return True
        if billing_status == "insufficient_balance":
            self._refresh_wallet_balance_metadata(run, wallet_payload)
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

    def _record_tool_usage_refund(
        self, run: _facade().AgentRun, tool_call: _facade().ToolCall, *, reason: str
    ) -> None:
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
        except _facade().RECOVERABLE_ERRORS as exc:
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
        self._refresh_tool_refund_metadata(run, refund)
        self._refresh_wallet_balance_metadata(run, refund)
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
    def _refresh_wallet_balance_metadata(
        run: _facade().AgentRun, wallet_debit: dict[str, _facade().Any]
    ) -> None:
        if "balance_after_units" in wallet_debit:
            run.metadata["model_wallet_balance_units"] = wallet_debit.get("balance_after_units", 0)
            run.metadata["ai_wallet_balance_units"] = wallet_debit.get("balance_after_units", 0)
        if "balance_after_yuan" in wallet_debit:
            run.metadata["model_wallet_balance_yuan"] = wallet_debit.get("balance_after_yuan")
            run.metadata["ai_wallet_balance_yuan"] = wallet_debit.get("balance_after_yuan")

    @staticmethod
    def _refresh_tool_usage_metadata(
        run: _facade().AgentRun, entry: dict[str, _facade().Any]
    ) -> None:
        run.metadata["tool_usage_entry_count"] = (
            int(run.metadata.get("tool_usage_entry_count") or 0) + 1
        )
        run.metadata["tool_usage_cost_units_total"] = int(
            run.metadata.get("tool_usage_cost_units_total") or 0
        ) + int(entry.get("cost_units") or 0)
        run.metadata["tool_usage_ledger_status"] = "recorded"

    @staticmethod
    def _refresh_tool_refund_metadata(
        run: _facade().AgentRun, refund: dict[str, _facade().Any]
    ) -> None:
        run.metadata["tool_usage_refund_count"] = (
            int(run.metadata.get("tool_usage_refund_count") or 0) + 1
        )
        if str(refund.get("status") or "") == "refunded":
            run.metadata["tool_usage_refund_cost_units_total"] = int(
                run.metadata.get("tool_usage_refund_cost_units_total") or 0
            ) + int(refund.get("cost_units") or 0)
        run.metadata["tool_usage_refund_status"] = str(refund.get("status") or "")

    @staticmethod
    def _cost_units_total(run: _facade().AgentRun) -> int:
        return sum(int(call.cost_units or 0) for call in run.tool_calls)

    @staticmethod
    def _step_cost_units(step: _facade().AgentStep) -> int:
        spec = _facade().get_tool_action_spec(step.tool_id, step.action)
        try:
            return int(getattr(spec, "cost_units", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _refresh_run_cost_metadata(self, run: _facade().AgentRun) -> None:
        run.metadata["tool_call_count"] = len(run.tool_calls)
        run.metadata["cost_units_total"] = self._cost_units_total(run)
        run.metadata["ai_cost_units_total"] = int(run.metadata["cost_units_total"]) + int(
            run.metadata.get("llm_cost_units_total") or 0
        )
        _facade().refresh_ai_budget_metadata(run)
