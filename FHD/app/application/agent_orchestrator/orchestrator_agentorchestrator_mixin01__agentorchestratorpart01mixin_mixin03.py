# mypy: disable-error-code="attr-defined, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.orchestrator")


class __AgentOrchestratorPart01MixinPart03Mixin:
    def _mark_budget_exceeded(
        self,
        run: _facade().AgentRun,
        step: _facade().AgentStep,
        payload: dict[str, _facade().Any],
        *,
        node_outputs: dict[str, _facade().Any],
    ) -> None:
        step.status = "failed"
        step.error = str(payload.get("message") or "AI cost budget exceeded")
        run.status = "failed"
        run.error = step.error
        self._refresh_run_cost_metadata(run)
        run.metadata["ai_cost_budget_exceeded"] = True
        self._refresh_repair_metadata(run)
        payload = dict(payload)
        payload["step_id"] = step.step_id
        payload["node_id"] = step.node_id
        payload["tool_id"] = step.tool_id
        payload["action"] = step.action
        run.add_event("budget.exceeded", step.error, payload)
        run.final_output = {
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
            "cost_units_total": run.metadata["cost_units_total"],
            "ai_cost_units_total": run.metadata["ai_cost_units_total"],
            "ai_cost_budget_units": run.metadata.get("ai_cost_budget_units"),
            "ai_cost_budget_remaining_units": run.metadata.get("ai_cost_budget_remaining_units"),
            "ai_cost_budget_exceeded": True,
            "failed_step_id": step.step_id,
            "error": run.error,
            "repair_count": run.metadata.get("repair_count", 0),
        }
        self._append_llm_summary_to_final_output(run)

    def _record_observation(
        self,
        run: _facade().AgentRun,
        step: _facade().AgentStep,
        *,
        tool_call: _facade().ToolCall,
        success: bool,
    ) -> dict[str, _facade().Any]:
        output_message = str(step.output.get("message") or "")
        output_error = str(
            step.output.get("message")
            or step.output.get("error")
            or step.output.get("error_code")
            or ""
        )
        observation = {
            "observation_id": f"obs_{tool_call.call_id}",
            "step_id": step.step_id,
            "node_id": step.node_id,
            "tool_id": step.tool_id,
            "action": step.action,
            "call_id": tool_call.call_id,
            "attempt_count": step.attempt_count,
            "success": success,
            "message": output_message,
            "error": "" if success else output_error,
            "status": "completed" if success else "failed",
        }
        step.observations.append(observation)
        run.metadata["observation_count"] = sum(len(item.observations) for item in run.steps)
        run.add_event("observation.recorded", f"记录 {step.node_id} 执行观察", observation)
        return observation

    @staticmethod
    def _coerce_positive_int(value: _facade().Any) -> int:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)

    def _apply_repair_policy(
        self, run: _facade().AgentRun, plan_metadata: dict[str, _facade().Any]
    ) -> None:
        repair_policy = plan_metadata.get("repair_policy")
        repair_policy = repair_policy if isinstance(repair_policy, dict) else {}
        global_limit = self._coerce_positive_int(
            repair_policy.get("max_attempts") or plan_metadata.get("max_repair_attempts")
        )
        overrides = plan_metadata.get("repair_overrides")
        overrides = overrides if isinstance(overrides, dict) else {}
        for step in run.steps:
            node_policy = repair_policy.get(step.node_id)
            node_policy = node_policy if isinstance(node_policy, dict) else {}
            node_limit = self._coerce_positive_int(node_policy.get("max_attempts"))
            has_override = self._repair_override_for_step(step, overrides) is not None
            has_llm_repair = _facade().is_llm_repair_enabled(run, plan_metadata)
            step.max_repair_attempts = (
                node_limit or global_limit or (1 if has_override or has_llm_repair else 0)
            )

    @staticmethod
    def _repair_override_for_step(
        step: _facade().AgentStep, overrides: dict[str, _facade().Any]
    ) -> dict[str, _facade().Any] | None:
        keys = (step.node_id, f"{step.tool_id}.{step.action}", step.tool_id)
        for key in keys:
            candidate = overrides.get(key)
            if isinstance(candidate, dict):
                return candidate
        return None

    def _repair_sources(
        self, run: _facade().AgentRun, runtime_context: dict[str, _facade().Any]
    ) -> list[tuple[str, dict[str, _facade().Any]]]:
        plan_meta = dict((run.metadata.get("plan") or {}).get("metadata") or {})
        sources: list[tuple[str, dict[str, _facade().Any]]] = []
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
    def _params_patch_from_repair(override: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        for key in ("params", "set_params", "patch_params"):
            candidate = override.get(key)
            if isinstance(candidate, dict):
                return dict(candidate)
        return {}
