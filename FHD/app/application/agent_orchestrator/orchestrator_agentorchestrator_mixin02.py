# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.orchestrator")


class _AgentOrchestratorPart02Mixin:
    def _prepare_repair_or_retry(
        self,
        run: _facade().AgentRun,
        step: _facade().AgentStep,
        *,
        runtime_context: dict[str, _facade().Any],
    ) -> bool:
        if str((step.output or {}).get("error_code") or "") == "tool_billing_blocked":
            return False
        if not self._can_auto_execute(step):
            return False
        for source_name, overrides in self._repair_sources(run, runtime_context):
            override = self._repair_override_for_step(step, overrides)
            if override is None:
                continue
            limit = (
                self._coerce_positive_int(override.get("max_attempts"))
                or step.max_repair_attempts
                or 1
            )
            if limit <= 0 or len(step.repair_history) >= limit:
                return False
            params_patch = self._params_patch_from_repair(override)
            retry_without_patch = bool(
                override.get("retry") or override.get("retry_without_param_change")
            )
            if not params_patch and (not retry_without_patch):
                return False
            previous_params = _facade().copy.deepcopy(step.params)
            if params_patch:
                step.params.update(_facade().copy.deepcopy(params_patch))
            if previous_params == step.params and (not retry_without_patch):
                return False
            repair_record = {
                "attempt_count": step.attempt_count,
                "source": source_name,
                "error": step.error,
                "params_patch": params_patch,
                "previous_params": previous_params,
                "next_params": _facade().copy.deepcopy(step.params),
                "reason": str(override.get("reason") or override.get("message") or ""),
            }
            step.repair_history.append(repair_record)
            step.status = "pending"
            step.output = {}
            step.error = ""
            run.status = "retrying"
            self._refresh_repair_metadata(run)
            run.add_event(
                "step.repair_applied",
                f"步骤 {step.node_id} 已应用受控修复",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "tool_id": step.tool_id,
                    "action": step.action,
                    "source": source_name,
                    "attempt_count": step.attempt_count,
                    "repair_count": len(step.repair_history),
                    "params_patch": params_patch,
                },
            )
            run.add_event(
                "step.retry_scheduled",
                f"步骤 {step.node_id} 将按修复参数重试",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "tool_id": step.tool_id,
                    "action": step.action,
                    "attempt_count": step.attempt_count + 1,
                    "max_repair_attempts": limit,
                },
            )
            self._repo.save(run)
            return True
        return self._prepare_llm_repair_or_retry(run, step, runtime_context=runtime_context)

    def _prepare_llm_repair_or_retry(
        self,
        run: _facade().AgentRun,
        step: _facade().AgentStep,
        *,
        runtime_context: dict[str, _facade().Any],
    ) -> bool:
        if not _facade().is_llm_repair_enabled(run, runtime_context):
            return False
        limit = _facade().llm_repair_attempt_limit(run, step, runtime_context)
        if limit <= 0 or len(step.repair_history) >= limit:
            return False
        run.add_event(
            "step.llm_repair_requested",
            f"步骤 {step.node_id} 请求 LLM 修复",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "tool_id": step.tool_id,
                "action": step.action,
                "attempt_count": step.attempt_count,
                "max_repair_attempts": limit,
            },
        )
        try:
            advice = _facade().request_llm_repair(run, step, runtime_context)
        except _facade().RECOVERABLE_ERRORS as exc:
            run.add_event(
                "step.llm_repair_failed",
                "LLM 修复请求失败",
                {"step_id": step.step_id, "node_id": step.node_id, "error": str(exc)},
            )
            return False
        if not self._record_repair_llm_call(run, step, advice):
            return False
        if not advice.get("success"):
            run.add_event(
                "step.llm_repair_failed",
                str(advice.get("message") or "LLM 未给出可用修复"),
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "message": str(advice.get("message") or ""),
                },
            )
            return False
        params_patch = dict(advice.get("params_patch") or {})
        if not params_patch:
            return False
        previous_params = _facade().copy.deepcopy(step.params)
        next_params = _facade().copy.deepcopy(step.params)
        next_params.update(_facade().copy.deepcopy(params_patch))
        validation = _facade().validate_tool_call(step.tool_id, step.action, next_params)
        if not validation.ok:
            run.add_event(
                "step.repair_rejected",
                "LLM 修复未通过 ToolSpec 校验",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "tool_id": step.tool_id,
                    "action": step.action,
                    "params_patch": params_patch,
                    "error_code": validation.error_code,
                    "message": validation.message,
                },
            )
            return False
        if previous_params == next_params:
            return False
        step.params = next_params
        repair_record = {
            "attempt_count": step.attempt_count,
            "source": "llm_repair",
            "error": step.error,
            "params_patch": params_patch,
            "previous_params": previous_params,
            "next_params": _facade().copy.deepcopy(step.params),
            "reason": str(advice.get("reason") or ""),
            "confidence": advice.get("confidence"),
        }
        step.repair_history.append(repair_record)
        step.status = "pending"
        step.output = {}
        step.error = ""
        run.status = "retrying"
        self._refresh_repair_metadata(run)
        run.add_event(
            "step.repair_applied",
            f"步骤 {step.node_id} 已应用 LLM 修复",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "tool_id": step.tool_id,
                "action": step.action,
                "source": "llm_repair",
                "attempt_count": step.attempt_count,
                "repair_count": len(step.repair_history),
                "params_patch": params_patch,
            },
        )
        run.add_event(
            "step.retry_scheduled",
            f"步骤 {step.node_id} 将按 LLM 修复参数重试",
            {
                "step_id": step.step_id,
                "node_id": step.node_id,
                "tool_id": step.tool_id,
                "action": step.action,
                "attempt_count": step.attempt_count + 1,
                "max_repair_attempts": limit,
            },
        )
        self._repo.save(run)
        return True

    def _record_repair_llm_call(
        self, run: _facade().AgentRun, step: _facade().AgentStep, advice: dict[str, _facade().Any]
    ) -> bool:
        call = advice.get("llm_call")
        if not isinstance(call, _facade().LLMCall):
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
            self._refresh_llm_metadata(run)
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
            self._refresh_model_usage_metadata(run, entry)
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
        except _facade().RECOVERABLE_ERRORS as exc:
            call.metadata["usage_ledger"] = {"status": "failed", "message": str(exc)}
            run.add_event(
                "billing.record_failed",
                "LLM 修复模型用量记录失败",
                {"llm_call_id": call.call_id, "error": str(exc)},
            )
        self._refresh_llm_metadata(run)
        return call.billing_status != "insufficient_balance"

    @staticmethod
    def _refresh_model_usage_metadata(
        run: _facade().AgentRun, entry: dict[str, _facade().Any]
    ) -> None:
        run.metadata["model_usage_entry_count"] = (
            int(run.metadata.get("model_usage_entry_count") or 0) + 1
        )
        run.metadata["model_usage_cost_units_total"] = int(
            run.metadata.get("model_usage_cost_units_total") or 0
        ) + int(entry.get("cost_units") or 0)
        run.metadata["model_usage_ledger_status"] = "recorded"

    def _refresh_llm_metadata(self, run: _facade().AgentRun) -> None:
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
        self._refresh_run_cost_metadata(run)

    @staticmethod
    def _append_llm_summary_to_final_output(run: _facade().AgentRun) -> None:
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
    def _refresh_repair_metadata(run: _facade().AgentRun) -> None:
        run.metadata["observation_count"] = sum(len(step.observations) for step in run.steps)
        run.metadata["repair_count"] = sum(len(step.repair_history) for step in run.steps)
