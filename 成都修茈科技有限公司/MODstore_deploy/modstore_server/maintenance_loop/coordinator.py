"""Compose one leased maintenance transaction from explicit runtime services."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from modstore_server import platform_llm_scope
from modstore_server import self_maintenance_remediation_lineage as lineage
from modstore_server import self_maintenance_retort_remediation as retort_remediation
from modstore_server.operational_errors import RECOVERABLE_ERRORS

from . import config, resume
from .runtime_dependencies import (
    RuntimeExecution,
    RuntimePolicy,
    RuntimePrompts,
    RuntimeRecovery,
    RuntimeState,
)


@dataclass
class _RunContext:
    run_id: str
    started_at: datetime
    triggered_by: str
    gate: Dict[str, Any]
    memory: Dict[str, Any]
    user_id: int
    resume_candidate: Optional[Dict[str, Any]]
    para_task_id: Optional[str]
    branch: Optional[str]
    steps: List[Dict[str, Any]] = field(default_factory=list)


class MaintenanceRuntime:
    """Own transaction dependencies; all mutable run state stays in a local context."""

    def __init__(
        self,
        *,
        state: Optional[RuntimeState] = None,
        recovery: Optional[RuntimeRecovery] = None,
        policy: Optional[RuntimePolicy] = None,
        execution: Optional[RuntimeExecution] = None,
        prompts: Optional[RuntimePrompts] = None,
        now: Optional[Callable[[], datetime]] = None,
        new_run_id: Optional[Callable[[], str]] = None,
    ) -> None:
        self.state = state if state is not None else RuntimeState.configured()
        self.recovery = recovery if recovery is not None else RuntimeRecovery.configured()
        self.policy = policy if policy is not None else RuntimePolicy.configured()
        self.execution = execution if execution is not None else RuntimeExecution.configured()
        self.prompts = prompts if prompts is not None else RuntimePrompts.configured()
        self.now = now if now is not None else config._utc_now
        self.new_run_id = new_run_id if new_run_id is not None else lambda: str(uuid.uuid4())

    @platform_llm_scope.platform_llm_scoped
    def run(
        self,
        *,
        triggered_by: str = "manual",
        force: bool = False,
        reason: Optional[str] = None,
        remediation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Acquire the process lease before recovery, admission, or employee dispatch."""
        with self.state.lease() as acquired:
            if acquired:
                return self._run_unlocked(
                    triggered_by=triggered_by,
                    force=force,
                    reason=reason,
                    remediation_context=remediation_context,
                )
            record = {
                "created_at": config._iso(self.now()),
                "force": force,
                "phase": "skip",
                "reason": reason,
                "run_id": self.new_run_id(),
                "status": "skipped_active_lease",
                "triggered_by": triggered_by,
            }
            record.update(lineage.remediation_lineage_fields(remediation_context))
            self.state.append(record)
            return record

    def _run_unlocked(
        self,
        *,
        triggered_by: str,
        force: bool,
        reason: Optional[str],
        remediation_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        self.recovery.stale_runs(exclusive_lease_reacquired=True)
        run_id = self.new_run_id()
        started_at = self.now()
        gate = self.policy.admit(force=force, triggered_by=triggered_by)
        self.state.ensure_baseline()
        if not gate.get("should_run"):
            record = {
                "created_at": config._iso(started_at),
                "force": force,
                "gate": gate,
                "phase": "skip",
                "reason": reason,
                "run_id": run_id,
                "status": f"skipped_{gate.get('reason')}",
                "triggered_by": triggered_by,
            }
            record.update(lineage.remediation_lineage_fields(remediation_context))
            self.state.append(record)
            return record
        user_id = self.policy.actor_user_id()
        memory = self.state.load_memory()
        reconciliations = self._recover_memory(memory)
        candidate = (
            lineage.resume_candidate_from_context(memory, remediation_context)
            if remediation_context
            else resume._resume_review_qa_candidate(memory)
        )
        if remediation_context and candidate is None:
            record = lineage.unavailable_context_record(
                created_at=config._iso(started_at),
                force=force,
                gate=gate,
                remediation_context=remediation_context,
                run_id=run_id,
                triggered_by=triggered_by,
            )
            self.state.append(record)
            return record
        start_record = {
            "created_at": config._iso(started_at),
            "force": force,
            "gate": gate,
            "memory_path": str(self.state.memory_path()),
            "phase": "start",
            "reason": reason,
            "run_id": run_id,
            "started_at": config._iso(started_at),
            "status": "running",
            "triggered_by": triggered_by,
            "user_id": user_id,
            "runtime_provenance": gate.get("runtime_provenance"),
            **reconciliations,
        }
        start_record.update(lineage.remediation_lineage_fields(remediation_context))
        if candidate:
            start_record["resume_candidate"] = candidate
        self.state.append(start_record)
        resume_steps = resume._resume_steps(candidate)
        task_id, branch = resume._resume_dispatch_context(candidate, resume_steps)
        steps_to_run = sorted(resume_steps)
        context = _RunContext(
            run_id=run_id,
            started_at=started_at,
            triggered_by=triggered_by,
            gate=gate,
            memory=memory,
            user_id=user_id,
            resume_candidate=candidate,
            para_task_id=task_id,
            branch=branch,
        )
        plan = self._plan(context, steps_to_run)
        try:
            return self._execute(context, plan)
        except RECOVERABLE_ERRORS as exc:
            config.logger.exception("self-maintenance loop failed")
            return self._finish(context, status="failed", extra={"error": str(exc)})

    def _recover_memory(self, memory: Dict[str, Any]) -> Dict[str, Any]:
        merge = self.recovery.requested_merges(memory)
        retort = self.recovery.retort_scope(memory)
        absorbed = self.recovery.absorbed_merges(
            memory,
            base_branch=os.environ.get("MODSTORE_PARA_BRANCH", "").strip() or "main",
        )
        if merge.get("changed") or retort.get("changed") or absorbed.get("changed"):
            self.state.write_memory(memory)
        evidence = {}
        if any(merge.values()):
            evidence["merge_reconciliation"] = merge
        if retort.get("changed"):
            evidence["retort_scope_reconciliation"] = retort
        if absorbed.get("changed"):
            evidence["absorbed_para_merge_reconciliation"] = absorbed
        return evidence

    def _plan(self, context: _RunContext, steps_to_run: List[str]) -> list:
        plan = []
        if "code" in steps_to_run:
            extra: Dict[str, Any] = {"allow_medium_risk": True, "skip_path_guard": True}
            if context.resume_candidate and context.resume_candidate.get(
                "continue_existing_code_task"
            ):
                extra["branch"] = context.branch
            plan.append(
                (
                    "vibe-coding-maintainer",
                    "code",
                    self.prompts.code(
                        context.run_id,
                        context.gate,
                        context.memory,
                        context.resume_candidate,
                    ),
                    extra,
                )
            )
        for step, employee_id in (
            ("review", "change-request-auditor"),
            ("qa", "test-qa-runner"),
        ):
            if step in steps_to_run:
                extra = {
                    "allow_medium_risk": True,
                    "report_only": True,
                    "wait_timeout_sec": config._env_int(
                        "MODSTORE_SELF_MAINTENANCE_REPORT_TIMEOUT_SEC", 1800
                    ),
                }
                if step == "review":
                    extra["skip_path_guard"] = True
                plan.append((employee_id, step, "", extra))
        return plan

    def _execute(self, context: _RunContext, plan: list) -> Dict[str, Any]:
        for employee_id, step_name, task_text, extra in plan:
            if step_name == "review":
                task_text = self.prompts.review(context.run_id, context.branch, context.memory)
            elif step_name == "qa":
                task_text = self.prompts.qa(context.run_id, context.branch, context.memory)
            if context.para_task_id and step_name == "code":
                extra = {**extra, "para_task_id": context.para_task_id}
            elif context.para_task_id:
                extra = {
                    **extra,
                    "review_base_branch": os.environ.get("MODSTORE_PARA_BRANCH"),
                    "review_repo_url": os.environ.get("MODSTORE_PARA_REPO_URL"),
                    "review_target_branch": context.branch,
                    "review_target_para_task_id": context.para_task_id,
                }
            if step_name == "review":
                stopped = self._retort_stop(context, employee_id)
                if stopped is not None:
                    return stopped
            record = self._dispatch_step(context, employee_id, step_name, task_text, extra)
            if not record["ok"]:
                return self._finish(
                    context,
                    status="failed",
                    extra={"error": record["error"], "failed_step": step_name},
                )
            if step_name == "code" and context.branch:
                try:
                    early_kb = self.execution.validate_knowledge(
                        run_id=context.run_id, branch=context.branch
                    )
                except RECOVERABLE_ERRORS:
                    config.logger.exception(
                        "early KB validation crashed for branch=%s run_id=%s; skipping",
                        context.branch,
                        context.run_id,
                    )
                    early_kb = {"ok": True, "reason": "early_kb_validation_crashed"}
                if (
                    isinstance(early_kb, dict)
                    and not early_kb.get("ok")
                    and early_kb.get("reason") == "kb_json_schema_validation_failed"
                    and isinstance(early_kb.get("kb_validation"), dict)
                ):
                    config.logger.warning(
                        "early KB schema validation failed for branch=%s run_id=%s; rejecting and retrying code step",
                        context.branch,
                        context.run_id,
                    )
                    return self.execution.reject_knowledge(
                        run_id=context.run_id,
                        branch=context.branch,
                        para_task_id=context.para_task_id,
                        kb_validation=early_kb["kb_validation"],
                        steps=context.steps,
                        gate=context.gate,
                        triggered_by=context.triggered_by,
                        started_at=context.started_at,
                    )
        return self._finish(context, status="completed")

    def _retort_stop(self, context: _RunContext, employee_id: str) -> Optional[Dict[str, Any]]:
        gate = self.execution.retort_before_review(
            run_id=context.run_id,
            branch=context.branch,
            para_task_id=str(context.para_task_id or ""),
            memory=context.memory,
        )
        if not gate.get("blocked"):
            return None
        scope_only = retort_remediation.retort_scope_only_clarification(gate)
        error = str(gate.get("reason") or "retort_clarification_pending")
        record = {
            "employee_id": employee_id,
            "error": error,
            "ok": False,
            "para": {},
            "phase": "step",
            "report_excerpt": "",
            "run_id": context.run_id,
            "status": "completed_held_for_remediation" if scope_only else "failed",
            "step": "review",
            "timestamp": config._iso(self.now()),
            "retort_clarification": gate,
        }
        context.steps.append(record)
        self.state.append(record)
        policy_override = None
        if scope_only:
            policy_override = {
                "action": "hold_for_automated_remediation",
                "detail": "Retort requires a smaller clean-base patch before unattended review.",
                "reason": retort_remediation.RETORT_SCOPE_REASON,
                "resume_from_clean_baseline": True,
            }
        return self._finish(
            context,
            status="failed",
            extra={
                "error": error,
                "failed_step": "review",
                "retort_clarification": gate,
            },
            policy_override=policy_override,
        )

    def _dispatch_step(
        self,
        context: _RunContext,
        employee_id: str,
        step_name: str,
        task_text: str,
        extra: dict,
    ) -> Dict[str, Any]:
        base_branch = str(extra.get("branch") or "").strip() if step_name == "code" else ""
        result, ok, failure, para, report, code_retries, marker_retries = self.execution.run_step(
            employee_id=employee_id,
            step_name=step_name,
            task_text=task_text,
            extra=extra,
            user_id=context.user_id,
            run_id=context.run_id,
        )
        if para.get("task_id") and context.para_task_id is None:
            context.para_task_id = str(para["task_id"])
        if step_name == "code" and para.get("branch"):
            context.branch = str(para["branch"])
        validation = None
        if step_name == "code" and ok and base_branch:
            validation = self.execution.validate_branch_delivery(
                base_branch=base_branch, delivered_branch=str(context.branch or "")
            )
            if not validation.get("ok"):
                ok = False
                failure = str(validation.get("reason") or "")
        record = {
            "employee_id": employee_id,
            "error": failure,
            "ok": ok,
            "para": para,
            "phase": "step",
            "report_excerpt": report,
            "retry_attempts": result.get("self_maintenance_retry_attempts"),
            "code_fix_retry_rounds": code_retries,
            "marker_retry_rounds": marker_retries,
            "run_id": context.run_id,
            "status": "success" if ok else "failed",
            "step": step_name,
            "timestamp": config._iso(self.now()),
        }
        if validation is not None:
            record["branch_delivery_validation"] = validation
        context.steps.append(record)
        self.state.append(record)
        return record

    def _finish(
        self,
        context: _RunContext,
        *,
        status: str,
        extra: Optional[Dict[str, Any]] = None,
        policy_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        policy = (
            policy_override
            if policy_override is not None
            else self.policy.decide(
                branch=context.branch,
                gate=context.gate,
                para_task_id=context.para_task_id,
                run_id=context.run_id,
                status=status,
                steps=context.steps,
            )
        )
        final_status = status
        if status == "completed":
            final_status = {
                "auto_merged_low_risk": "completed_merged",
                "auto_merge_requested_low_risk": "completed_merge_requested",
                "hold_for_automated_remediation": "completed_held_for_remediation",
            }.get(str(policy.get("action") or ""), status)
        final = {
            "branch": context.branch,
            "completed_at": config._iso(self.now()),
            "para_task_id": context.para_task_id,
            "phase": "complete",
            "policy_decision": policy,
            "run_id": context.run_id,
            "started_at": config._iso(context.started_at),
            "status": final_status,
            "steps": context.steps,
            "triggered_by": context.triggered_by,
            **(extra or {}),
        }
        if context.resume_candidate:
            final["resume_candidate"] = context.resume_candidate
        self.state.append(final)
        self.state.record_outcome(final, context.gate)
        return final


def run_self_maintenance_loop(
    *,
    triggered_by: str = "manual",
    force: bool = False,
    reason: Optional[str] = None,
    remediation_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run one maintenance transaction with the configured production services."""
    return MaintenanceRuntime().run(
        triggered_by=triggered_by,
        force=force,
        reason=reason,
        remediation_context=remediation_context,
    )
