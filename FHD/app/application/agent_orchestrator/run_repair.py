"""Bounded repair policy for replay-safe steps, using explicit storage and accounting."""

from __future__ import annotations

import copy
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import AgentRunRepository
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.runtime_dependencies import RuntimeDependencies
from app.utils.operational_errors import RECOVERABLE_ERRORS


class RunRepair:
    def __init__(
        self,
        repository: AgentRunRepository,
        usage: RunUsageLedger,
        dependencies: RuntimeDependencies,
    ) -> None:
        self.repository = repository
        self.usage = usage
        self.dependencies = dependencies

    def prepare_repair_or_retry(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
    ) -> bool:
        if run.metadata.get("non_retryable") or (step.output or {}).get("retryable") is False:
            return False
        if str((step.output or {}).get("error_code") or "") == "tool_billing_blocked":
            return False
        if not self.can_auto_execute(step):
            return False
        for source_name, overrides in self.repair_sources(run, runtime_context):
            override = self.repair_override_for_step(step, overrides)
            if override is None:
                continue
            limit = (
                self.coerce_positive_int(override.get("max_attempts"))
                or step.max_repair_attempts
                or 1
            )
            if limit <= 0 or len(step.repair_history) >= limit:
                return False
            params_patch = self.params_patch_from_repair(override)
            retry_without_patch = bool(
                override.get("retry") or override.get("retry_without_param_change")
            )
            if not params_patch and (not retry_without_patch):
                return False
            previous_params = copy.deepcopy(step.params)
            if params_patch:
                step.params.update(copy.deepcopy(params_patch))
            if previous_params == step.params and (not retry_without_patch):
                return False
            repair_record = {
                "attempt_count": step.attempt_count,
                "source": source_name,
                "error": step.error,
                "params_patch": params_patch,
                "previous_params": previous_params,
                "next_params": copy.deepcopy(step.params),
                "reason": str(override.get("reason") or override.get("message") or ""),
            }
            step.repair_history.append(repair_record)
            step.status = "pending"
            step.output = {}
            step.error = ""
            run.status = "retrying"
            self.usage.refresh_repair_metadata(run)
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
            self.repository.save(run)
            return True
        return self.prepare_llm_repair_or_retry(run, step, runtime_context=runtime_context)

    def prepare_llm_repair_or_retry(
        self,
        run: AgentRun,
        step: AgentStep,
        *,
        runtime_context: dict[str, Any],
    ) -> bool:
        if not self.dependencies.repair_enabled(run, runtime_context):
            return False
        limit = self.dependencies.repair_limit(run, step, runtime_context)
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
            advice = self.dependencies.request_repair(run, step, runtime_context)
        except RECOVERABLE_ERRORS as exc:
            run.add_event(
                "step.llm_repair_failed",
                "LLM 修复请求失败",
                {"step_id": step.step_id, "node_id": step.node_id, "error": str(exc)},
            )
            return False
        if not self.usage.record_repair_llm_call(run, step, advice):
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
        previous_params = copy.deepcopy(step.params)
        next_params = copy.deepcopy(step.params)
        next_params.update(copy.deepcopy(params_patch))
        validation = self.dependencies.validate(step.tool_id, step.action, next_params)
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
            "next_params": copy.deepcopy(step.params),
            "reason": str(advice.get("reason") or ""),
            "confidence": advice.get("confidence"),
        }
        step.repair_history.append(repair_record)
        step.status = "pending"
        step.output = {}
        step.error = ""
        run.status = "retrying"
        self.usage.refresh_repair_metadata(run)
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
        self.repository.save(run)
        return True

    @staticmethod
    def coerce_positive_int(value: Any) -> int:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)

    def apply_repair_policy(self, run: AgentRun, plan_metadata: dict[str, Any]) -> None:
        repair_policy = plan_metadata.get("repair_policy")
        repair_policy = repair_policy if isinstance(repair_policy, dict) else {}
        global_limit = self.coerce_positive_int(
            repair_policy.get("max_attempts") or plan_metadata.get("max_repair_attempts")
        )
        overrides = plan_metadata.get("repair_overrides")
        overrides = overrides if isinstance(overrides, dict) else {}
        for step in run.steps:
            node_policy = repair_policy.get(step.node_id)
            node_policy = node_policy if isinstance(node_policy, dict) else {}
            node_limit = self.coerce_positive_int(node_policy.get("max_attempts"))
            has_override = self.repair_override_for_step(step, overrides) is not None
            has_llm_repair = self.dependencies.repair_enabled(run, plan_metadata)
            step.max_repair_attempts = (
                node_limit or global_limit or (1 if has_override or has_llm_repair else 0)
            )

    @staticmethod
    def repair_override_for_step(
        step: AgentStep, overrides: dict[str, Any]
    ) -> dict[str, Any] | None:
        keys = (step.node_id, f"{step.tool_id}.{step.action}", step.tool_id)
        for key in keys:
            candidate = overrides.get(key)
            if isinstance(candidate, dict):
                return candidate
        return None

    def repair_sources(
        self, run: AgentRun, runtime_context: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        plan_meta = dict((run.metadata.get("plan") or {}).get("metadata") or {})
        sources: list[tuple[str, dict[str, Any]]] = []
        for source_name, container in (
            ("plan.metadata", plan_meta),
            ("runtime_context", dict(runtime_context or {})),
        ):
            for key in ("repair_overrides", "agent_repair_overrides"):
                overrides = container.get(key)
                if isinstance(overrides, dict):
                    sources.append((f"{source_name}.{key}", overrides))
        return sources

    @staticmethod
    def params_patch_from_repair(override: dict[str, Any]) -> dict[str, Any]:
        for key in ("params", "set_params", "patch_params"):
            candidate = override.get(key)
            if isinstance(candidate, dict):
                return dict(candidate)
        return {}

    @staticmethod
    def can_auto_execute(step: AgentStep) -> bool:
        return str(step.risk or "").lower() == "low" and bool(step.idempotent)
