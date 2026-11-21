from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, cast

from app.application.agent_orchestrator.execution_lease import DurableExecutionLeaseMixin
from app.application.agent_orchestrator.run_models import AgentRun, utc_now_iso
from app.application.agent_orchestrator.runtime_context import merge_runtime_context


def requires_retry_reconciliation(run: AgentRun) -> bool:
    recovery = run.metadata.get("recovery")
    return bool(run.metadata.get("non_retryable")) or (
        isinstance(recovery, dict) and recovery.get("state") == "manual_reconciliation_required"
    )


def continuation_conversation_error(run: AgentRun, context: dict[str, Any]) -> str:
    """Never revive old history from a native checkpoint after clear/delete/rebinding."""
    conversation = str(context.get("conversation_id") or "").strip()
    session = str(context.get("session_id") or "").strip()
    if not (conversation or session):
        return ""
    if conversation and session and conversation != session:
        return "恢复任务的会话标识不一致，拒绝使用旧上下文"
    from app.application.workflow.workflow_types import plan_from_dict

    plan = plan_from_dict(run.metadata.get("plan"))
    history_required = bool(
        plan and any(node.tool_id == "conversation_history" for node in plan.nodes)
    )
    task = run.metadata.get("task_context") or {}
    # The unified task API creates an addressable workspace even for non-chat
    # work. Its server-owned request/plan metadata distinguishes that identity
    # from a real conversation; caller/model runtime flags cannot opt out.
    task_workspace = (
        plan is not None
        and plan.metadata.get("source") == "unified_task_api"
        and bool(run.metadata.get("task_request"))
        and bool(task.get("task_id"))
        and str(task["task_id"]) == str(context.get("workspace_id") or "")
    )
    if task_workspace and not (session or history_required or "_conversation_revision" in context):
        return ""
    if not (
        "_conversation_revision" in context
        or history_required
        or run.metadata.get("checkpoint")
        or run.metadata.get("recovery")
        or run.metadata.get("control")
        or any(step.status == "completed" for step in run.steps)
    ):
        return ""
    revision = context.get("_conversation_revision")
    if type(revision) is not int or revision < 0:
        return "恢复任务缺少原会话版本，不能使用旧上下文"
    from app.application.task_conversation_store import durable_user_id
    from app.db.session import get_db
    from app.domain.shared_services.conversation_service import (
        begin_conversation_write,
        lock_conversation_session,
    )
    from app.http.request_context import reset_current_http_request, set_current_http_request
    from app.infrastructure.auth.agent_mod_scope import _bound_actor, agent_mod_execution_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    try:
        owner = durable_user_id(context.get("local_user_id") or context.get("actor_id"))
        identities = [context.get("local_user_id"), context.get("actor_id")]
        if str(run.user_id).isdigit():
            identities.append(run.user_id)
        if (
            owner is None
            or any(
                value not in (None, "") and durable_user_id(value) != owner for value in identities
            )
            or int(_bound_actor(context).id) != owner
        ):
            raise ValueError("conversation owner changed")
        # History lives in the authenticated Mod database. A background worker
        # must restore that scope, including clearing unrelated ambient scopes.
        token = set_request_active_mod_id("")
        request_token = set_current_http_request(None)
        try:
            with agent_mod_execution_scope(context.get("_mod_authorization")), get_db() as db:
                begin_conversation_write(db)
                lock_conversation_session(
                    db,
                    session_id=conversation or session,
                    user_id=owner,
                    expected_revision=revision,
                    create=False,
                )
        finally:
            reset_current_http_request(request_token)
            reset_request_active_mod_id(token)
    except (PermissionError, ValueError):
        return "原会话已变更、删除或授权失效，拒绝恢复旧上下文"
    return ""


def safe_continuation_error(
    run: AgentRun, *, approved_unsubmitted_step_id: str = "", elt_checkpoint_step_id: str = ""
) -> str:
    """Check persisted receipts and today's registry before any automatic replay."""
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.workflow.workflow_types import plan_from_dict, validate_plan_graph

    if requires_retry_reconciliation(run):
        return "任务执行结果尚需人工核对，不能恢复执行"
    if str(run.metadata.get("trace_mode") or "").startswith("legacy_planner_run"):
        return "旧执行观察记录不能自动续跑，需要人工核对"
    plan = plan_from_dict(run.metadata.get("plan"))
    if plan is None or not plan.nodes or validate_plan_graph(plan) or plan.plan_id != run.plan_id:
        return "持久化计划缺失或无效，不能自动恢复"
    steps = {step.node_id: step for step in run.steps}
    if len(steps) != len(run.steps) or set(steps) != {node.node_id for node in plan.nodes}:
        return "计划与执行步骤不一致，不能恢复"
    approval_ids = plan.metadata.get("approval_required_node_ids") or []
    if not isinstance(approval_ids, list) or any(str(value) not in steps for value in approval_ids):
        return "持久化审批节点清单无效，不能恢复"
    for node in plan.nodes:
        step = steps[node.node_id]
        if (
            step.output.get("outcome") == "unknown"
            or step.output.get("execution_outcome") == "unknown"
            or step.output.get("outcome_unknown")
            or step.output.get("reconciliation_required")
            or step.output.get("requires_reconciliation")
        ):
            return "步骤执行结果尚需人工核对，不能恢复执行"
        if (node.tool_id, node.action, node.params, node.depends_on) != (
            step.tool_id,
            step.action,
            step.params,
            step.depends_on,
        ):
            return "原计划与执行步骤已变化，不能恢复"
        if step.status == "completed":
            if step.output.get("success") is not True:
                return "已完成步骤缺少成功回执，需要人工核对"
            continue
        if step.status == "skipped":
            continue
        spec = get_tool_action_spec(step.tool_id, step.action)
        if (
            step.risk == "high"
            and spec is not None
            and (
                (
                    approved_unsubmitted_step_id
                    and step.step_id == approved_unsubmitted_step_id
                    and step.status == "pending"
                )
                or (
                    elt_checkpoint_step_id
                    and step.step_id == elt_checkpoint_step_id
                    and step.status in {"running", "pending"}
                )
            )
        ):
            continue
        if (
            node.node_id in approval_ids
            or step.status not in {"pending", "running", "failed"}
            or not (
                node.idempotent
                and step.idempotent
                and spec is not None
                and spec.idempotent
                and spec.read_only
                and node.risk == step.risk == spec.risk == "low"
            )
        ):
            return "剩余步骤需要审批或结果核对，请通过原任务审批流程处理"
    return ""


def prepare_safe_continuation(
    run: AgentRun,
    *,
    requested_by: str,
    reason: str,
    approved_unsubmitted_step_id: str = "",
    elt_checkpoint_step_id: str = "",
) -> None:
    if error := safe_continuation_error(
        run,
        approved_unsubmitted_step_id=approved_unsubmitted_step_id,
        elt_checkpoint_step_id=elt_checkpoint_step_id,
    ):
        raise ValueError(error)
    for step in run.steps:
        if step.status in {"failed", "running"}:
            step.status, step.error, step.output = "pending", "", {}
    for call in run.tool_calls:
        if call.status == "running":
            call.status, call.error, call.finished_at = (
                "failed",
                "worker_lease_expired",
                utc_now_iso(),
            )
    run.status, run.error = "queued", ""
    approved_step_id = elt_checkpoint_step_id or approved_unsubmitted_step_id
    run.metadata["dispatch"] = {
        **(dict(run.metadata.get("dispatch") or {}) if approved_step_id else {}),
        "state": "queued",
        "approved_step_id": approved_step_id,
        "requested_by": requested_by,
        "queued_at": utc_now_iso(),
    }
    run.metadata["recovery"] = {"state": "safe_checkpoint_resume", "reason": reason}
    run.add_event(
        "run.continuation_queued",
        "保留已完成步骤，等待继续执行剩余安全步骤",
        {
            "requested_by": requested_by,
            "reason": reason,
            "completed_step_ids": [s.step_id for s in run.steps if s.status == "completed"],
        },
    )


def validate_safe_retry_update(run: AgentRun, previous: AgentRun) -> None:
    """Dedicated terminal-to-queued transition; ordinary saves remain monotonic."""
    if previous.status not in {"failed", "blocked"} or run.status != "queued":
        raise ValueError("任务状态不允许安全续跑")
    if error := safe_continuation_error(previous):
        raise ValueError(error)
    if error := safe_continuation_error(run):
        raise ValueError(error)
    if (run.run_id, run.user_id, run.created_at, run.metadata.get("plan")) != (
        previous.run_id,
        previous.user_id,
        previous.created_at,
        previous.metadata.get("plan"),
    ):
        raise ValueError("续跑不能更改原任务或计划")
    candidate = {s.step_id: s for s in run.steps}
    if set(candidate) != {s.step_id for s in previous.steps} or any(
        (s.node_id, s.tool_id, s.action, s.params, s.depends_on, s.risk, s.idempotent)
        != (
            candidate[s.step_id].node_id,
            candidate[s.step_id].tool_id,
            candidate[s.step_id].action,
            candidate[s.step_id].params,
            candidate[s.step_id].depends_on,
            candidate[s.step_id].risk,
            candidate[s.step_id].idempotent,
        )
        or (s.status in {"completed", "skipped"} and candidate[s.step_id].to_dict() != s.to_dict())
        for s in previous.steps
    ):
        raise ValueError("续跑不能重置已完成步骤的回执")


class RunLifecycleMixin(DurableExecutionLeaseMixin):
    """Cooperative pause, resume, and cancellation for an agent orchestrator."""

    if TYPE_CHECKING:
        execute_dispatched_run: Any

    _repo: Any

    def _persist_control(
        self, expected: AgentRun, control: str, *, requested_by: str, command_id: str
    ) -> AgentRun | None:
        """Rebase control changes on the latest same-generation audit snapshot."""
        import copy

        from app.application.agent_orchestrator.run_sql_repository import same_run_generation

        for _attempt in range(8):
            previous = self._repo.get(expected.run_id)
            if previous is None:
                return None
            if not same_run_generation(previous, expected):
                return cast("AgentRun", previous)
            if previous.status in {"completed", "failed", "cancelled", "rejected"}:
                return cast("AgentRun", previous)
            run = copy.deepcopy(previous)
            self._mark_controlled(run, control, requested_by=requested_by, command_id=command_id)
            if control == "pause":
                run.metadata["control"]["resume_status"] = (
                    "waiting_user" if previous.status == "waiting_user" else "running"
                )
            if self._repo.save_control_if_unchanged(run, previous):
                stored = cast("AgentRun", self._repo.get(run.run_id))
                self._release_browser_run_resources(stored)
                return stored
        raise RuntimeError("agent run changed repeatedly while recording control")

    def pause_run(self, run_id: str, *, requested_by: str = "") -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status in {"completed", "failed", "cancelled"}:
            return cast("AgentRun | None", run)
        command = self._repo.request_task_control(run_id, "pause", requested_by=requested_by)
        execution = run.metadata.get("execution")
        execution_active = isinstance(execution, dict) and execution.get("state") == "active"
        if execution_active:
            run.metadata["control_request"] = {
                "action": "pause",
                "status": "requested",
                "requested_by": requested_by,
                "command_id": command.command_id,
            }
            return cast("AgentRun | None", run)
        stored = self._persist_control(
            run, "pause", requested_by=requested_by, command_id=command.command_id
        )
        self._repo.mark_task_control(
            command.command_id,
            "applied"
            if stored is not None
            and (stored.metadata.get("control") or {}).get("state") == "paused"
            else "rejected",
            applied_at=utc_now_iso(),
        )
        return cast("AgentRun | None", stored)

    def cancel_run(self, run_id: str, *, requested_by: str = "") -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status in {"completed", "failed", "cancelled", "rejected"}:
            return cast("AgentRun | None", run)
        command = self._repo.request_task_control(run_id, "cancel", requested_by=requested_by)
        execution = run.metadata.get("execution")
        execution_active = isinstance(execution, dict) and execution.get("state") == "active"
        if execution_active:
            run.metadata["control_request"] = {
                "action": "cancel",
                "status": "requested",
                "requested_by": requested_by,
                "command_id": command.command_id,
            }
            return cast("AgentRun | None", run)
        stored = self._persist_control(
            run, "cancel", requested_by=requested_by, command_id=command.command_id
        )
        if stored is not None and stored.status == "cancelled":
            self._cancel_queued_execution(run_id)
        self._repo.mark_task_control(
            command.command_id,
            "applied"
            if stored is not None
            and (stored.metadata.get("control") or {}).get("state") == "cancelled"
            else "rejected",
            applied_at=utc_now_iso(),
        )
        return cast("AgentRun | None", stored)

    def resume_run(
        self,
        run_id: str,
        *,
        requested_by: str = "",
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        if run.status != "paused":
            return cast("AgentRun | None", run)
        if requires_retry_reconciliation(run):
            raise ValueError("任务执行结果尚需人工核对，不能恢复执行")
        control = run.metadata.get("control")
        resume_status = str(control.get("resume_status") or "") if isinstance(control, dict) else ""
        context = merge_runtime_context(run, runtime_context)
        command = self._repo.request_task_control(run_id, "resume", requested_by=requested_by)
        run.metadata["runtime_context"] = context
        run.metadata["control"] = {
            "state": "running",
            "requested_by": requested_by,
            "command_id": command.command_id,
        }
        run.status = "waiting_user" if resume_status == "waiting_user" else "running"
        run.add_event(
            "run.resumed",
            "Agent run 已恢复",
            {"requested_by": requested_by, "command_id": command.command_id},
        )
        self._repo.save(run)
        self._repo.mark_task_control(command.command_id, "applied", applied_at=utc_now_iso())
        if run.status == "waiting_user":
            return cast("AgentRun | None", self._repo.save(run))
        self._execute_with_durable_lease(run, runtime_context=context)
        return cast("AgentRun | None", self._repo.save(run))

    def retry_run(
        self,
        run_id: str,
        *,
        requested_by: str = "",
        runtime_context: dict[str, Any] | None = None,
        auto_execute: bool = True,
        authenticated_binding: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        previous = self._repo.get(run_id)
        if previous is None:
            return None
        if requires_retry_reconciliation(previous):
            raise ValueError("任务执行结果尚需人工核对，不能恢复执行")
        if previous.status == "cancelled":
            raise ValueError("已取消任务不能自动重做，请明确发起新的业务任务")
        if previous.status not in {"failed", "blocked"}:
            return cast("AgentRun | None", previous)
        from app.application.agent_orchestrator.resume_transaction import retry_and_enqueue
        from app.application.agent_orchestrator.run_sql_repository import (
            SQLAlchemyAgentRunRepository,
        )

        if isinstance(self._repo, SQLAlchemyAgentRunRepository):
            return retry_and_enqueue(
                self._repo,
                run_id=run_id,
                principal_id=requested_by,
                runtime_context=runtime_context or {},
                authenticated_binding=authenticated_binding,
            )
        run = copy.deepcopy(previous)
        run.metadata["runtime_context"] = merge_runtime_context(run, runtime_context)
        prepare_safe_continuation(run, requested_by=requested_by, reason="explicit_retry")
        if not self._repo.save_retry_if_unchanged(run, previous):
            raise ValueError("任务状态已变化，请刷新后重试")
        if auto_execute:
            return cast("AgentRun | None", self.execute_dispatched_run(run_id))
        return cast("AgentRun", self._repo.get(run_id))

    def _apply_requested_control(self, run: AgentRun) -> bool:
        command = self._repo.latest_task_control(run.run_id)
        if (
            command is None
            or command.status != "requested"
            or command.action not in {"pause", "cancel"}
        ):
            return False
        if run.status not in {"completed", "failed", "cancelled"}:
            # Preserve execution facts held only by this worker before rebasing
            # the control delta on the current same-generation snapshot.
            self._repo.save(run)
        stored = self._persist_control(
            run, command.action, requested_by=command.requested_by, command_id=command.command_id
        )
        if stored is None:
            return False
        import copy

        run.__dict__.update(copy.deepcopy(stored.__dict__))
        control = run.metadata.get("control") or {}
        applied = control.get("command_id") == command.command_id and run.status == (
            "cancelled" if command.action == "cancel" else "paused"
        )
        self._repo.mark_task_control(
            command.command_id, "applied" if applied else "rejected", applied_at=utc_now_iso()
        )
        return True

    @staticmethod
    def _cancel_queued_execution(run_id: str) -> None:
        from app.application.agent_orchestrator.task_execution_repository import (
            get_task_execution_repository,
        )

        queue = get_task_execution_repository()
        current = queue.get(run_id)
        if current is None or current.state not in {
            "queued",
            "waiting_approval",
            "paused",
            "blocked",
        }:
            return
        queue.transition(run_id, "cancelled", error_code="cancelled")

    @staticmethod
    def _mark_controlled(
        run: AgentRun,
        control: str,
        *,
        requested_by: str = "",
        command_id: str = "",
    ) -> None:
        channel = str(run.metadata.get("channel") or "").strip().lower()
        if (
            run.metadata.get("trace_mode")
            in {"legacy_planner_run", "legacy_planner_run_with_tools"}
            or channel in {"compat_chat_stream", "compat_chat_stream_langgraph"}
        ) and run.status in {"planning", "running", "retrying"}:
            # The observation callback may not have run yet. Persist the replay
            # gate atomically with control while the original stream can write.
            run.metadata["non_retryable"] = True
            run.metadata["recovery"] = {
                **(run.metadata.get("recovery") or {}),
                "state": "manual_reconciliation_required",
                "error_code": "legacy_stream_control_unsettled",
            }
        if control == "cancel":
            for step in run.steps:
                if step.status in {"pending", "retrying", "waiting_user"}:
                    step.status = "skipped"
                    step.error = "run cancelled before execution"
            run.status = "cancelled"
            run.error = (
                "任务已停止继续执行；已有调用结果仍需人工核对"
                if requires_retry_reconciliation(run)
                else "run cancelled"
            )
            run.metadata["control"] = {
                "state": "cancelled",
                "requested_by": requested_by,
                "command_id": command_id,
            }
            run.final_output = {
                **dict(run.final_output or {}),
                "cancelled": True,
                "completed_step_ids": [
                    step.step_id for step in run.steps if step.status == "completed"
                ],
            }
            if not any(event.event_type == "run.cancelled" for event in run.events):
                run.add_event(
                    "run.cancelled",
                    "Agent run 已取消",
                    {
                        "requested_by": requested_by,
                        "execution_status": "cancelled",
                        "task_id": str(
                            (run.metadata.get("runtime_context") or {}).get("task_id") or run.run_id
                        ),
                        "tenant_id": str(
                            (run.metadata.get("runtime_context") or {}).get("tenant_id") or ""
                        ),
                        "trace_id": run.run_id,
                    },
                )
            return
        run.status = "paused"
        run.metadata["control"] = {
            "state": "paused",
            "requested_by": requested_by,
            "command_id": command_id,
        }
        if not any(event.event_type == "run.paused" for event in run.events):
            run.add_event("run.paused", "Agent run 已暂停", {"requested_by": requested_by})
