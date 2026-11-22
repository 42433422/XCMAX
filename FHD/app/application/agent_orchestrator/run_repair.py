"""Bounded repair policy for replay-safe steps, using explicit storage and accounting."""

from __future__ import annotations

import copy
from typing import Any

from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import AgentRunRepository
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.runtime_dependencies import RuntimeDependencies
from app.domain.task_lifecycle.results import (
    execution_result_envelopes,
    execution_result_requires_reconciliation,
    execution_result_states,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


def _requires_frozen_parameters(
    run: AgentRun, runtime_context: dict[str, Any] | None, *, repository: Any = None
) -> bool:
    """Codex owns replanning; its child graph cannot mint a second model loop."""
    contexts = (run.metadata.get("runtime_context") or {}, runtime_context or {})
    if run.metadata.get("runtime_type") == "codex" or any(
        context.get("source") == "codex_runtime" for context in contexts
    ):
        return True
    parent_ids = {str(context.get("parent_run_id") or "") for context in contexts} - {""}
    if not parent_ids:
        return False
    try:
        if repository is None:
            from app.application.agent_orchestrator.run_repository import get_agent_run_repository

            repository = get_agent_run_repository()
        for parent_id in parent_ids:
            parent = repository.get(parent_id)
            if parent is None or parent.metadata.get("runtime_type") == "codex":
                return True
    except RECOVERABLE_ERRORS:
        # Missing ancestry is never authority to change a persisted request.
        return True
    return False


_MAX_REPAIR_ATTEMPTS = 4


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
        if self.requires_reconciliation(run, step):
            return False
        if not self.can_auto_execute(step):
            return False
        for source_name, overrides in self.repair_sources(run, runtime_context):
            override = self.repair_override_for_step(step, overrides)
            if override is None:
                continue
            limit = min(
                _MAX_REPAIR_ATTEMPTS,
                self.coerce_positive_int(override.get("max_attempts"))
                or step.max_repair_attempts
                or 1,
            )
            limit = self._limit_from_tool_spec(step, limit)
            if limit <= 0 or len(step.repair_history) >= limit:
                return False
            params_patch = self.params_patch_from_repair(override)
            retry_without_patch = bool(
                override.get("retry") or override.get("retry_without_param_change")
            )
            if not params_patch and (not retry_without_patch):
                return False
            previous_params = copy.deepcopy(step.params)
            candidate_params = copy.deepcopy(previous_params)
            if params_patch:
                candidate_params.update(copy.deepcopy(params_patch))
                if candidate_params != previous_params and _requires_frozen_parameters(
                    run, runtime_context, repository=self.repository
                ):
                    return False
                validation = self.dependencies.validate(step.tool_id, step.action, candidate_params)
                if not validation.ok:
                    run.add_event(
                        "step.repair_rejected",
                        "受控修复未通过 ToolSpec 校验",
                        {
                            "step_id": step.step_id,
                            "node_id": step.node_id,
                            "tool_id": step.tool_id,
                            "action": step.action,
                            "error_code": validation.error_code,
                            "message": validation.message,
                        },
                    )
                    return False
            if previous_params == candidate_params and (not retry_without_patch):
                return False
            step.params = candidate_params
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
        return False

    @staticmethod
    def requires_reconciliation(run: AgentRun, step: AgentStep) -> bool:
        output = step.output or {}
        return bool(
            requires_retry_reconciliation(run)
            or output.get("retryable") is False
            or output.get("error_code") == "tool_billing_blocked"
            or execution_result_requires_reconciliation(output)
            or any(
                execution_result_states(item) & {"timeout", "timed_out"}
                or "unknown" in str(item.get("error_code") or "").lower()
                for item in execution_result_envelopes(output)
            )
        )

    @staticmethod
    def coerce_positive_int(value: Any) -> int:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)

    def _limit_from_tool_spec(self, step: AgentStep, limit: int) -> int:
        """Cap existing repair ownership; never create another retry loop/counter."""
        if limit <= 0 or len(step.repair_history) >= limit:
            return 0
        spec = self.dependencies.action_spec(step.tool_id, step.action)
        if spec is None:
            return limit
        policy = spec.retry
        if not isinstance(policy, dict):
            return 0
        total = policy.get("max_attempts", 0)
        # Only the historical integer zero means unspecified. Malformed explicit
        # server policies fail closed, without coercing booleans or fractions.
        if type(total) is not int or total < 0:
            return 0
        if total == 0:
            return limit
        if step.attempt_count >= total:
            return 0
        return min(limit, total - 1)

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
            step.max_repair_attempts = self._limit_from_tool_spec(
                step,
                min(
                    _MAX_REPAIR_ATTEMPTS,
                    node_limit or global_limit or (1 if has_override else 0),
                ),
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
