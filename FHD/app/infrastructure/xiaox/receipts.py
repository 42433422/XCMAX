"""Read original scoped business receipts; never dispatch or replay an action."""

from __future__ import annotations

import copy
import hashlib
import re
import time
from typing import Any

from app.application.agent_orchestrator import run_lifecycle
from app.application.agent_orchestrator.run_models import AgentRun, tool_call_from_dict
from app.application.agent_orchestrator.task_models import mod_id_of_run, tenant_id_of_run
from app.application.agent_orchestrator.tool_permission import redact
from app.domain.task_lifecycle.agent_runtime_results import (
    ACTIVE_STATES,
    model_unsettled,
    receipt_state,
)
from app.domain.task_lifecycle.results import (
    execution_result_envelopes,
    execution_result_error,
    execution_result_outcome_unknown,
    execution_result_proven_not_executed,
)
from app.infrastructure.xiaox.binding import (
    XiaoxBinding,
    XiaoxBindingError,
    XiaoxBindingStore,
    canonical_digest,
)


def project_child_calls(run: AgentRun, rows: list[dict[str, Any]]) -> None:
    """Display child receipts while retaining their original verification owner."""
    known = {call.call_id for call in run.tool_calls}
    # Historical display records remain immutable; only exact child provenance
    # can identify a pre-rename projection of the same persisted receipt.
    legacy = {
        (call.call_id, call.metadata.get("child_run_id"), call.metadata.get("child_call_id"))
        for call in run.tool_calls
        if (call.metadata or {}).get("source") == "codex_child_receipt"
    }
    for row in rows:
        child_id = str(row.get("child_run_id") or "")
        receipt = row.get("receipt")
        if not child_id or not isinstance(receipt, dict):
            continue
        for raw in receipt.get("tool_calls") or []:
            if not isinstance(raw, dict) or not raw.get("call_id"):
                continue
            suffix = hashlib.sha256(f"{child_id}:{raw['call_id']}".encode()).hexdigest()[:40]
            projection_id = "xiaox_" + suffix
            if projection_id in known or ("codex_" + suffix, child_id, raw["call_id"]) in legacy:
                continue
            payload = copy.deepcopy(raw)
            payload["call_id"] = projection_id
            child_metadata = payload.get("metadata") or {}
            payload["metadata"] = {
                **{
                    key: value
                    for key, value in child_metadata.items()
                    if not key.startswith("verification")
                },
                "source": "xiaox_child_receipt",
                "child_run_id": child_id,
                "child_call_id": raw["call_id"],
                # The redacted display payload is not the original child's
                # output. Its hash/contract must never become a parent-step
                # verification record. Completion re-reads the original child.
                "child_verification": {
                    "contract_sha256": (child_metadata.get("verification_contract") or {}).get(
                        "contract_sha256"
                    ),
                    "output_sha256": child_metadata.get("verification_output_sha256"),
                    "report_sha256": (child_metadata.get("verification") or {}).get(
                        "report_sha256"
                    ),
                },
            }
            run.tool_calls.append(tool_call_from_dict(payload))
            known.add(projection_id)


def resume_error(
    store: XiaoxBindingStore, binding: XiaoxBinding, rows: list[dict[str, Any]]
) -> str:
    if error := run_lifecycle.continuation_conversation_error(binding.run, binding.context):
        return error
    if model_unsettled(binding.metadata):
        return "原模型请求或计量结果尚待核对，禁止自动恢复"
    for row in rows:
        if receipt_state(row) == "unknown":
            return "业务结果尚未确定，禁止恢复模型执行或重放工具"
        child_id = str(row.get("child_run_id") or "")
        child = store.repository.get(child_id) if child_id else None
        if child is not None and child.status in {"failed", "blocked"}:
            original = binding.metadata.get("calls", {}).get(str(row.get("call_id")))
            no_effect = (
                _failed_execution_receipt(child, child.steps[0], child.tool_calls[0])
                if len(child.steps) == len(child.tool_calls) == 1
                else None
            )
            if (
                no_effect is not None
                and not run_lifecycle.requires_retry_reconciliation(child)
                and receipt_state(row) == "failed"
                and row["receipt"].get("execution") == no_effect
                and isinstance(original, dict)
                and all(
                    original.get(key) == row.get(key)
                    for key in ("fingerprint", "tool_id", "action", "params", "child_task_id")
                )
                and read_call_receipt(store, binding, original) == row["receipt"]
            ):
                # The original rejection proves no write happened. Continuing
                # the parent can plan remaining work without replaying this child.
                continue
            # We never retry a child here; nevertheless enforce the existing
            # continuation guard before allowing a model to propose more work.
            if error := run_lifecycle.safe_continuation_error(child):
                return error
    return ""


def _safe_output(value: Any) -> Any:
    if isinstance(value, dict):
        return redact({k: _safe_output(v) for k, v in value.items() if not str(k).startswith("_")})
    if isinstance(value, list):
        return [_safe_output(v) for v in value]
    return value


def _unknown(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": False,
        "verified": False,
        "status": "unknown",
        "outcome": "unknown",
        "task_id": call["child_task_id"],
        "run_id": call.get("child_run_id", ""),
        "reconciliation_required": True,
        "retryable": False,
        "message": "原业务调用结果尚未确定；请核对原任务，不可重新提交相同操作",
    }


def _verified_step(run: AgentRun, step: Any, record: Any) -> bool:
    """A successful step needs its independently persisted matching tool call."""
    from app.application.agent_orchestrator.result_verification import verified_step_output

    if step is None or record is None:
        return False
    output = verified_step_output(run, step)
    return bool(
        step.status == record.status == "completed"
        and (record.node_id, record.tool_id, record.action, record.params, record.output)
        == (step.node_id, step.tool_id, step.action, step.params, step.output)
        and output.get("success") is True
        and not execution_result_error(output)
        and not execution_result_outcome_unknown(step.output, include_execution=True)
        and not any(
            isinstance(row.get("status_code"), int) and row["status_code"] >= 400
            for row in execution_result_envelopes(step.output)
        )
    )


def _pending_step(run: AgentRun, step: Any, record: Any) -> bool:
    """An acknowledged effect can wait while its host is parked for readback."""
    from app.application.agent_orchestrator.result_verification import (
        _binding_valid,
        pending_execution_receipt,
    )

    if (
        run.status != "blocked"
        or step is None
        or record is None
        or step.status != "completed"
        or record.status != "completed"
        or not pending_execution_receipt(record.output)
        or (record.metadata.get("verification") or {}).get("status")
        not in {"pending", "inconclusive", "verified"}
        or (
            (run.metadata.get("recovery") or {}).get("state") != "result_pending"
            and not _verified_step(run, step, record)
        )
        or any(
            isinstance(row.get("status_code"), int) and row["status_code"] >= 400
            for row in execution_result_envelopes(record.output)
        )
    ):
        return False
    try:
        return _binding_valid(
            run,
            step,
            record,
            run.metadata.get("runtime_context") or {},
            record.metadata.get("verification_contract"),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _failed_execution_receipt(child: Any, step: Any, record: Any) -> dict[str, Any] | None:
    """Project only the bound, frozen original rejection; never infer from failure."""
    from app.application.agent_orchestrator.result_verification import _binding_valid

    if (
        record is None
        or child.status != "failed"
        # Additional attempts are not this bridge's single frozen action receipt;
        # the latest rejection must not hide earlier effects or unbound history.
        or len(child.tool_calls) != 1
        or bool(child.artifacts)
        or step.status != "failed"
        or record.status != "failed"
        or not execution_result_proven_not_executed(record.output)
    ):
        return None
    try:
        if not _binding_valid(
            child,
            step,
            record,
            child.metadata.get("runtime_context") or {},
            record.metadata.get("verification_contract"),
        ):
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    execution = record.output["execution"]
    return {key: execution[key] for key in ("outcome", "committed", "effect") if key in execution}


def _failed_step_detail(child: Any) -> str:
    """Return the concrete tool error so the next turn can repair the plan."""
    for step in getattr(child, "steps", None) or []:
        output = getattr(step, "output", None)
        if not isinstance(output, dict):
            continue
        payload = output.get("data")
        if not isinstance(payload, dict):
            continue
        result = payload.get("result")
        if not isinstance(result, dict):
            continue
        for row in result.get("outputs") or []:
            if not isinstance(row, dict):
                continue
            inner = row.get("output")
            detail = inner.get("error") if isinstance(inner, dict) else None
            if detail:
                return str(detail)
    return ""


def read_call_receipt(
    store: XiaoxBindingStore, binding: XiaoxBinding, call: dict[str, Any]
) -> dict[str, Any]:
    """Read business truth, never turn completion or MCP transport success."""
    store._validate_goal(binding.run, binding.metadata)
    if (call.get("tool_id"), call.get("action")) == ("xcmax_workflow", "execute"):
        return {**_unknown(call), "error_code": "retired_runtime_contract"}
    child_run_id = str(call.get("child_run_id") or "")
    child = store.repository.get(child_run_id) if child_run_id else None
    if child is None and not child_run_id:
        task = store.repository.get_task(
            user_id=binding.run.user_id,
            task_id=call["child_task_id"],
            tenant_id=tenant_id_of_run(binding.run),
        )
        if task is not None:
            # A lost binding ACK may adopt only the sole original admission.
            # A later active attempt cannot supply this call's original proof.
            if task.attempt != 1 or task.run_count != 1:
                return _unknown(call)
            child = store.repository.get(task.active_run_id)
    if child is None:
        metadata = binding.metadata
        if (
            not child_run_id
            and call.get("state") == "claimed"
            and call.get("generation") == metadata.get("generation")
            and metadata.get("coordinator_active")
            and not metadata.get("revoked")
            and float(metadata.get("expires_at", 0)) > time.time()
        ):
            return {
                "success": False,
                "verified": False,
                "status": "claimed",
                "task_id": call["child_task_id"],
                "run_id": "",
                "in_progress": True,
                "retryable": False,
                "message": "原调用正在登记业务任务，请读取原调用状态",
            }
        return _unknown(call)
    context = child.metadata.get("runtime_context") or {}
    if (
        child.user_id != binding.run.user_id
        or tenant_id_of_run(child) != tenant_id_of_run(binding.run)
        or mod_id_of_run(child) != mod_id_of_run(binding.run)
        or context.get("parent_run_id") != binding.run_id
        or (child.metadata.get("task_context") or {}).get("task_id") != call["child_task_id"]
    ):
        raise XiaoxBindingError("owner_changed", "业务回执不属于当前运行范围")
    outputs = [step.output for step in child.steps] + [record.output for record in child.tool_calls]
    total_cost = max(
        int(child.metadata.get("ai_cost_units_total") or 0),
        sum(int(record.cost_units or 0) for record in child.tool_calls)
        + sum(int(record.cost_units or 0) for record in child.llm_calls),
    )
    from app.application.agent_orchestrator.result_verification import summarize_verification

    verification = summarize_verification(child)
    execution = (
        _failed_execution_receipt(child, child.steps[0], child.tool_calls[0])
        if len(child.steps) == len(child.tool_calls) == 1
        else None
    )
    steps = {step.step_id: step for step in child.steps}
    pending_calls = {
        record.call_id
        for record in child.tool_calls
        if _pending_step(child, steps.get(record.step_id), record)
    }
    # The executor commits its raw receipt before independent QC. The original
    # active child still owns that verification; an actual unknown outcome below
    # remains blocking, and abandoned workers are settled by lease/restart recovery.
    unverified_effect = (
        child.status not in ACTIVE_STATES
        and not verification["accepted"]
        and any(
            (record.metadata.get("verification_contract") or {}).get("read_only") is not True
            and record.call_id not in pending_calls
            and (
                record.output.get("success") is True
                or (child.status in {"blocked", "failed"} and execution is None)
            )
            for record in child.tool_calls
        )
    )
    unknown = (
        bool(child.metadata.get("non_retryable"))
        and (child.metadata.get("recovery") or {}).get("state") == "manual_reconciliation_required"
    )
    if (
        unknown
        or unverified_effect
        or any(
            execution_result_outcome_unknown(output, include_execution=True) for output in outputs
        )
    ):
        return {
            **_unknown(call),
            "run_id": child.run_id,
            "child_updated_at": child.updated_at,
            "ai_cost_units_total": total_cost,
            "verification": _safe_output(verification),
            "tool_calls": [_safe_output(record.to_dict()) for record in child.tool_calls],
        }
    nodes = (child.metadata.get("plan") or {}).get("nodes") or []
    if len(nodes) != 1 or len(child.steps) != 1:
        raise XiaoxBindingError("evidence_mismatch", "业务任务已偏离原调用动作")
    node, step = nodes[0], child.steps[0]
    if (
        canonical_digest({key: node.get(key) for key in ("tool_id", "action", "params")})
        != call["fingerprint"]
        or node.get("node_id") != step.node_id
        or node.get("tool_id") != step.tool_id
        or node.get("action") != step.action
        or node.get("params") != step.params
        or list(node.get("depends_on") or []) != step.depends_on
    ):
        raise XiaoxBindingError("evidence_mismatch", "业务任务已偏离原调用动作")
    latest = {record.step_id: record for record in child.tool_calls}
    completed_steps = [step for step in child.steps if step.status != "skipped"]
    verified = (
        child.status == "completed"
        and bool(completed_steps)
        and verification["accepted"]
        and all(_verified_step(child, step, latest.get(step.step_id)) for step in completed_steps)
    )
    status = child.status
    if status == "blocked" and any(record.call_id in pending_calls for record in latest.values()):
        status = "running"
    if status == "completed" and not verified:
        status = "failed"
    execution = _failed_execution_receipt(child, step, latest.get(step.step_id))
    approval_card = None
    clarification = None
    if status == "waiting_user":
        from app.application.workflow.approval_card import build_approval_card_payload

        waiting = [step for step in child.steps if step.status == "waiting_user"]
        question = next(
            (step for step in waiting if (step.tool_id, step.action) == ("clarify", "ask")), None
        )
        if question is not None:
            clarification = {
                **_safe_output(question.output),
                "run_id": child.run_id,
                "step_id": question.step_id,
            }
        waiting = [step for step in waiting if (step.tool_id, step.action) != ("clarify", "ask")]
        approval_card = (
            build_approval_card_payload(
                action="approval_pending",
                inner={
                    "run_id": child.run_id,
                    "plan_id": child.plan_id,
                    "intent": child.intent,
                    "blocking_nodes": [step.node_id for step in waiting],
                    "approval_required": True,
                    "approval_nodes": [
                        {
                            "step_id": step.step_id,
                            "node_id": step.node_id,
                            "tool_id": step.tool_id,
                            "action": step.action,
                            "params": _safe_output(step.params),
                        }
                        for step in waiting
                    ],
                    "todo": [
                        step.description or f"{step.tool_id}.{step.action}" for step in waiting
                    ],
                    "reason": "原任务的冻结业务操作需要用户审批",
                },
            )
            if waiting
            else None
        )
    message = str(child.error or ("业务回执已核验" if verified else "业务任务尚未完成"))
    if execution is not None:
        message = _failed_step_detail(child) or message
    return {
        "success": verified,
        "verified": verified,
        "status": status,
        "run_id": child.run_id,
        "task_id": call["child_task_id"],
        "child_updated_at": child.updated_at,
        "verification": _safe_output(verification),
        "ai_cost_units_total": total_cost,
        "pending_approval": approval_card is not None,
        "approval_card": approval_card,
        "needs_user_input": clarification is not None,
        "clarification": clarification,
        "retryable": False,
        "reconciliation_required": False,
        **({"execution": execution} if execution is not None else {}),
        "message": message,
        "tool_calls": [_safe_output(record.to_dict()) for record in latest.values()],
        "artifacts": [_safe_output(artifact.to_dict()) for artifact in child.artifacts],
    }


def action_parent(context: dict[str, Any]) -> tuple[XiaoxBindingStore, XiaoxBinding, Any] | None:
    """Resolve a child through host-owned SQL identity and the original call ledger."""
    if context.get("source") == "codex_runtime":
        raise PermissionError("原运行回执尚待迁移，不可绕过任务来源校验")
    if context.get("source") != "xiaox_runtime" or not context.get("parent_run_id"):
        return None
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository

    repository = get_agent_run_repository()
    if not isinstance(repository, SQLAlchemyAgentRunRepository):
        raise PermissionError("当前动作缺少原始持久任务登记")
    current = repository.get(str(context.get("run_id") or ""))
    parent = repository.get(str(context["parent_run_id"]))
    stored = (current.metadata.get("runtime_context") or {}) if current else {}
    if (
        current is None
        or parent is None
        or parent.metadata.get("runtime_type") != "xiaox"
        or current.user_id != parent.user_id
        or parent.user_id != str(context.get("user_id"))
        or tenant_id_of_run(current) != tenant_id_of_run(parent)
        or str(tenant_id_of_run(parent)) != str(context.get("tenant_id"))
        or mod_id_of_run(current) != mod_id_of_run(parent)
        or mod_id_of_run(current)
        != str(context.get("mod_id") or context.get("active_mod_id") or "")
        or stored.get("parent_run_id") != parent.run_id
        or any(
            stored.get(key) != context.get(key)
            for key in ("_actor_authorization", "_mod_authorization")
        )
    ):
        raise PermissionError("当前动作不属于原账号、租户与 Mod 任务")
    binding = XiaoxBinding(parent)
    if binding.metadata.get("goal_digest") != XiaoxBindingStore._validate_goal(
        parent, binding.metadata
    ):
        raise PermissionError("原任务目标绑定已变化")
    calls = list((binding.metadata.get("calls") or {}).values())
    if not any(
        call.get("child_run_id") == current.run_id
        and call.get("child_task_id") == (current.metadata.get("task_context") or {}).get("task_id")
        for call in calls
    ):
        raise PermissionError("当前动作没有原任务登记凭据")
    return XiaoxBindingStore(repository), binding, current


def browser_action_receipts(context: dict, tool_id: str) -> list[dict[str, Any]]:
    """Only verified prior actions may supply session generations or page evidence."""
    parent = action_parent(context)
    if parent is None:
        return []
    store, binding, current = parent
    records: dict[str, dict] = {}
    for identity, call in (binding.metadata.get("calls") or {}).items():
        child_id = str(call.get("child_run_id") or "")
        if call.get("tool_id") != tool_id or not child_id or child_id == current.run_id:
            continue
        if child_id in records:
            records[child_id]["call_ids"].append(identity)
            continue
        receipt = read_call_receipt(store, binding, call)
        if receipt.get("verified") is not True:
            continue
        child = store.repository.get(child_id)
        if child is None:
            raise PermissionError("已核验浏览器动作的原始任务不可用")
        step = child.steps[0]
        record = next(
            record for record in reversed(child.tool_calls) if record.step_id == step.step_id
        )
        records[child_id] = {
            "call_ids": [identity],
            "child": child,
            "step": step,
            "record": record,
            "created_at": call["created_at"],
        }
    return sorted(records.values(), key=lambda item: item["created_at"])


def read_action_artifact(file_path: str, context: dict[str, Any]) -> tuple[bytes, str] | None:
    """Open a verified prior child artifact through the same parent's durable calls."""
    match = re.fullmatch(
        r"/api/agent/runs/([A-Za-z0-9_-]{1,160})/artifacts/([A-Za-z0-9_-]{1,160})",
        file_path,
    )
    if match is None or not context.get("parent_run_id"):
        return None
    from app.application.agent_orchestrator.artifact_files import (
        artifact_path,
        read_verified_run_file,
    )
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    _bound_actor(context)
    parent = action_parent(context)
    if parent is None:
        return None
    store, binding, _current = parent
    calls = list((binding.metadata.get("calls") or {}).values())
    source = next((call for call in calls if call.get("child_run_id") == match[1]), None)
    if source is None:
        raise PermissionError("产物来源不属于原任务的已登记动作")
    receipt = read_call_receipt(store, binding, source)
    if receipt.get("verified") is not True:
        raise PermissionError("原动作产物尚未核验，不可作为新动作输入")
    artifact = next(
        (row for row in receipt["artifacts"] if row.get("artifact_id") == match[2]), None
    )
    if artifact is None or artifact.get("uri") != file_path:
        raise PermissionError("产物引用与原动作回执不一致")
    return read_verified_run_file(match[1], artifact), artifact_path(match[1], match[2]).suffix
