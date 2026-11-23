"""Project terminal Business Harness results back into their conversation."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application.agent_orchestrator.business_harness import (
    BUSINESS_HARNESS_PROTOCOL,
    ensure_terminal_business_result,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_FACT_LABELS = {
    "id": "记录 ID",
    "customer_id": "客户 ID",
    "product_id": "产品 ID",
    "material_id": "原材料 ID",
    "order_id": "订单 ID",
    "record_id": "记录 ID",
    "request_id": "请求 ID",
    "request_no": "请求单号",
    "order_number": "业务单号",
    "document_id": "文档 ID",
    "doc_name": "文档",
    "name": "名称",
    "created": "新增",
    "updated": "更新",
    "deleted": "删除",
    "deleted_documents": "删除文档",
    "deleted_chunks": "删除分块",
    "deleted_templates": "删除模板",
    "deleted_memories": "删除记忆",
    "skipped_templates": "跳过模板",
    "count": "数量",
    "total": "合计",
    "row_count": "明细行数",
    "amount_total": "金额合计",
}


def _text(value: Any, limit: int = 160) -> str:
    return str(value if value is not None else "")[:limit]


def _metadata_json(payload: dict[str, Any]) -> str:
    """Bound presentation fields before encoding; never cut serialized JSON."""
    encoded = json.dumps(payload, ensure_ascii=False, default=str)
    if len(encoded) <= 12000:
        return encoded
    harness = payload.get("business_harness") or {}
    ui = payload.get("ui") or {}
    result = ui.get("businessResult") or {}
    evidence = result.get("evidence") or {}
    compact: dict[str, Any] = {
        "role_hint": "assistant",
        "idempotency_key": _text(payload.get("idempotency_key"), 256),
        "business_harness": {
            key: _text(harness.get(key))
            for key in ("protocol", "event", "task_id", "turn_id", "run_id", "approval_request_id")
        },
        "ui": {
            "workflowAction": _text(ui.get("workflowAction"), 64),
            "businessResult": {
                **{
                    key: _text(result.get(key))
                    for key in (
                        "protocol",
                        "status",
                        "task_id",
                        "turn_id",
                        "conversation_id",
                        "run_id",
                    )
                },
                "success": result.get("success") is True,
                "pending_approval": result.get("pending_approval") is True,
                "summary": _text(result.get("summary"), 800),
                "facts": {
                    key: _text(value, 128)
                    for key, value in list((result.get("facts") or {}).items())[:12]
                },
                "evidence": {
                    "event_count": _text(evidence.get("event_count"), 20),
                    "completed_tool_count": _text(evidence.get("completed_tool_count"), 20),
                    "artifact_ids": [
                        _text(value, 96) for value in (evidence.get("artifact_ids") or [])[:8]
                    ],
                },
            },
            "thinkingSteps": _text(ui.get("thinkingSteps"), 1600),
        },
        "metadata_truncated": True,
        "evidence_ref": {"source": "agent_run", "run_id": _text(harness.get("run_id"), 96)},
    }
    encoded = json.dumps(compact, ensure_ascii=False)
    if len(encoded) > 12000:
        compact["ui"]["thinkingSteps"] = ""
        compact["ui"]["businessResult"]["facts"] = {}
        compact["ui"]["businessResult"]["evidence"] = {}
        encoded = json.dumps(compact, ensure_ascii=False)
    return encoded


def _enterprise_summary(observation: dict[str, Any], event_id: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        key: _text(observation.get(key))
        for key in (
            "observation_id",
            "run_id",
            "task_id",
            "goal_id",
            "entity_type",
            "entity_id",
            "metric",
            "unit",
            "delta",
            "status",
            "memory_id",
            "memory_scope",
            "memory_status",
        )
    }
    for name in ("before", "after"):
        sample = observation.get(name) or {}
        summary[name] = {
            key: _text(sample.get(key))
            for key in ("value", "unit", "source", "source_version", "observed_at", "expires_at")
        }
    summary.update(
        observation_verified=True,
        business_success=None,
        attribution="unproven",
        target_met=observation.get("target_met")
        if isinstance(observation.get("target_met"), bool)
        else None,
        evidence_ref={
            "source": "agent_run.events",
            "run_id": summary["run_id"],
            "event_id": event_id,
            "event_type": "enterprise.outcome_observed",
            "observation_id": summary["observation_id"],
        },
        action_count=len(observation.get("actions") or []),
    )
    return summary


def _enterprise_content(summary: dict[str, Any]) -> str:
    before, after = summary["before"], summary["after"]
    change = {"improved": "改善", "worsened": "恶化", "no_change": "未变化"}.get(
        summary["status"], "已观察"
    )
    memory = {
        "pending": "待确认",
        "active": "已确认",
        "rejected": "已拒绝",
        "deleted": "已删除，未重新创建",
        "retry_required": "写入待重试",
        "not_written": "尚未写入",
    }.get(summary["memory_status"], "待核对")
    return (
        f"经营指标核验：{summary['entity_type']} {summary['entity_id']} 的 {summary['metric']} "
        f"从 {before['value']} 变为 {after['value']} {summary['unit']}（变化 {summary['delta']}，{change}）。"
        f"\n来源：{after['source']}；前后查询时间：{before['observed_at']} → {after['observed_at']}。"
        "\n权威数据已回查，动作与指标变化的因果关系仍未证实。"
        f"\n任务：{summary['task_id']}；核验回执：{summary['observation_id']}。"
        f"\n对应个人记忆记录状态：{memory}。"
    )


def project_enterprise_outcome_to_conversation(
    run_id: str, observation: dict[str, Any], *, repository=None
) -> int | None:
    """Project a committed observation separately from the immutable task receipt."""
    if not observation or observation.get("observation_verified") is not True:
        return None
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.agent_orchestrator.business_action_ledger import canonical_hash
        from app.application.agent_orchestrator.run_audit_scope import _result_scope
        from app.services import get_conversation_service

        run = (
            repository.get(run_id)
            if repository is not None
            else AgentOrchestrator().get_run(run_id)
        )
        if (
            run is None
            or run.status != "completed"
            or _result_scope(run)
            != (
                observation.get("actor_id"),
                observation.get("tenant_id"),
                observation.get("mod_id"),
            )
        ):
            return None
        result = ensure_terminal_business_result(run)
        if result.get("task_id") != observation.get("task_id") or run_id != observation.get(
            "run_id"
        ):
            return None
        event = next(
            (
                event
                for event in run.events
                if event.event_type == "enterprise.outcome_observed"
                and (event.data.get("observation") or {}).get("observation_id")
                == observation.get("observation_id")
            ),
            None,
        )
        frozen = event.data["observation"] if event else {}
        if (
            not event
            or any(observation.get(key) != value for key, value in frozen.items())
            or (
                frozen.get("observation_id")
                != canonical_hash(
                    {key: value for key, value in frozen.items() if key != "observation_id"}
                )
            )
        ):
            return None
        runtime = run.metadata.get("runtime_context") or {}
        session_id = str(
            result.get("conversation_id")
            or runtime.get("conversation_id")
            or runtime.get("session_id")
            or ""
        )
        if not session_id:
            return None
        summary = _enterprise_summary(observation, event.event_id)
        key = f"enterprise_outcome:{summary['observation_id']}:{summary['memory_status']}"
        metadata = _metadata_json(
            {
                "role_hint": "assistant",
                "idempotency_key": key,
                "business_harness": {
                    "protocol": BUSINESS_HARNESS_PROTOCOL,
                    "event": "task.outcome_observed",
                    "task_id": result["task_id"],
                    "run_id": run_id,
                    "turn_id": result.get("turn_id"),
                },
                "ui": {"workflowAction": "enterprise_outcome", "enterpriseOutcome": summary},
            }
        )
        revision = runtime.get("_conversation_revision")
        return get_conversation_service().save_message(
            session_id=session_id,
            user_id=run.user_id,
            role="assistant",
            content=_enterprise_content(summary),
            intent="enterprise_outcome",
            metadata=metadata,
            idempotency_key=key,
            expected_revision=revision if type(revision) is int else None,
        )
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "enterprise outcome projection requires retry run_id=%s type=%s",
            run_id,
            type(exc).__name__,
        )
        return None


def completed_deliverable_lines(run: Any) -> list[str]:
    """已完成节点产出的可下载文件；必须写进回复，否则用户拿不到真实文件。"""
    lines: list[str] = []
    seen: set[str] = set()
    for step in getattr(run, "steps", []) or []:
        if str(getattr(step, "status", "") or "") != "completed":
            continue
        output = getattr(step, "output", None)
        if not isinstance(output, dict):
            continue
        url = str(output.get("download_url") or "").strip()
        name = str(output.get("file_name") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        lines.append(
            f"- 已生成《{name}》：[{name}]({url})（一次性有效，请及时下载）"
            if name
            else f"- [下载文件]({url})（一次性有效，请及时下载）"
        )
    return lines


def _thinking_steps(run: Any) -> str:
    """把已执行的工具节点还原成「思考过程」行，避免只回一句通用完成语。"""
    lines: list[str] = []
    for step in getattr(run, "steps", []) or []:
        tool = str(getattr(step, "tool_id", "") or "").strip()
        action = str(getattr(step, "action", "") or "").strip()
        if not tool:
            continue
        name = f"{tool}.{action}" if action else tool
        status = str(getattr(step, "status", "") or "")
        if status == "failed":
            lines.append(f"[工具未成功:{name}]")
            continue
        lines.append(f"[正在调用工具:{name}]")
        if status == "completed":
            lines.append("[工具已返回]")
    unique: list[str] = []
    for line in lines:
        if line not in unique:
            unique.append(line)
    return "\n".join(unique)


def _message_for_result(result: dict[str, Any], approval_request_id: str) -> str:
    status = str(result.get("status") or "")
    summary = str(result.get("summary") or "").strip()
    if status == "completed":
        prefix = "审批已完成，业务操作执行成功"
    elif status == "cancelled":
        prefix = "审批已拒绝，业务任务已取消，未继续执行"
    else:
        prefix = "审批流程已结束，但业务操作执行失败"
    parts = [prefix]
    if summary and summary not in prefix:
        parts.append(summary)
    facts = result.get("facts")
    if isinstance(facts, dict):
        rendered = [
            f"{_FACT_LABELS.get(key, key)}：{value}"
            for key, value in facts.items()
            if value not in ("", None)
        ]
        if rendered:
            parts.append("；".join(rendered))
    if approval_request_id:
        parts.append(f"审批单：{approval_request_id}")
    return "。".join(part.rstrip("。") for part in parts if part).strip() + "。"


def _owns_original_plan(
    saved: dict[str, Any], run: Any, session_id: str, result: dict[str, Any]
) -> bool:
    stored = saved.get("runtime_context") or {}
    runtime = run.metadata.get("runtime_context") or {}
    user_id = str(run.user_id or "")
    owner = str(saved.get("user_id") or "")
    alias = owner == f"web_normal_{session_id}"
    if not user_id or saved.get("session_id") != session_id:
        return False
    if alias and (stored.get("user_id") != owner or not stored.get("local_user_id")):
        return False
    actors = {
        str(value)
        for value in (
            None if alias else owner,
            stored.get("local_user_id"),
            stored.get("actor_id"),
            runtime.get("local_user_id"),
            runtime.get("actor_id"),
        )
        if value not in (None, "")
    }
    if actors != {user_id}:
        return False
    if any(
        value and value != session_id
        for context in (stored, runtime)
        for value in (context.get("session_id"), context.get("conversation_id"))
    ):
        return False
    if str(stored.get("tenant_id") or "") != str(runtime.get("tenant_id") or ""):
        return False
    task_id = str(stored.get("task_id") or "")
    if task_id and task_id != str(result.get("task_id") or ""):
        return False
    return not alias or bool(stored.get("tenant_id") and task_id)


def _original_plan_terminal(
    store: Any, orchestrator: Any, run: Any, session_id: str, result: dict[str, Any]
) -> tuple[str, str] | None:
    metadata = (run.metadata.get("plan") or {}).get("metadata") or {}
    parent_id = str(metadata.get("approval_parent_plan_id") or "")
    plan_id = parent_id or run.plan_id
    saved = store.load(plan_id)
    if not saved or not _owns_original_plan(saved, run, session_id, result):
        return None
    terminal = {"completed": "succeeded", "failed": "failed", "cancelled": "cancelled"}
    if not parent_id:
        return (plan_id, terminal[result["status"]])
    nodes = (saved.get("plan") or {}).get("nodes") or []
    if not nodes or len({node["node_id"] for node in nodes}) != len(nodes):
        return None
    candidates = {run.run_id: run}
    if len(nodes) > 1:
        candidates.update(
            {
                item.run_id: item
                for item in orchestrator.list_task_runs(
                    user_id=str(run.user_id), task_id=str(result.get("task_id") or "")
                )
            }
        )
    outcomes = []
    for node in nodes:
        matches = []
        for candidate in candidates.values():
            link = (candidate.metadata.get("plan") or {}).get("metadata") or {}
            if (
                link.get("approval_parent_plan_id") != parent_id
                or link.get("approval_parent_node_id") != node["node_id"]
                or candidate.plan_id != f"{parent_id}:{node['node_id']}"
                or len(candidate.steps) != 1
            ):
                continue
            step = candidate.steps[0]
            if (step.node_id, step.tool_id, step.action, step.params) != (
                node["node_id"],
                node["tool_id"],
                node["action"],
                node.get("params") or {},
            ):
                continue
            outcome = ensure_terminal_business_result(candidate)
            if outcome and _owns_original_plan(saved, candidate, session_id, outcome):
                matches.append(outcome.get("status"))
        if len(matches) != 1 or matches[0] not in terminal:
            return None
        outcomes.extend(matches)
    status = (
        "failed"
        if "failed" in outcomes
        else "cancelled"
        if "cancelled" in outcomes
        else "completed"
    )
    return plan_id, terminal[status]


def project_terminal_run_to_conversation(
    run_id: str,
    *,
    approval_request_id: str = "",
) -> int | None:
    """Write one idempotent terminal assistant message for an approval-backed run."""
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return None
    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.services import get_conversation_service

        orchestrator = AgentOrchestrator()
        run = orchestrator.get_run(normalized_run_id)
        if run is None:
            return None
        result = ensure_terminal_business_result(run)
        if not result:
            return None
        runtime = run.metadata.get("runtime_context")
        runtime = runtime if isinstance(runtime, dict) else {}
        session_id = str(
            result.get("conversation_id")
            or runtime.get("conversation_id")
            or runtime.get("session_id")
            or ""
        ).strip()
        if not session_id:
            return None
        plan_status = {"completed": "succeeded", "failed": "failed", "cancelled": "cancelled"}.get(
            str(result.get("status") or "")
        )
        if run.plan_id and plan_status:
            from app.application.workflow.plan_store import WorkflowPlanStore

            store = WorkflowPlanStore()
            original = _original_plan_terminal(store, orchestrator, run, session_id, result)
            saved = store.load(original[0]) if original else None
            if (
                original
                and saved
                and str(saved.get("status") or "")
                in {
                    "running",
                    "pending_awaiting",
                }
            ):
                # Approval handlers call this after commit; never execute a tool here.
                store.update_status(original[0], original[1], str(result.get("summary") or ""))
        projection_key = str(result.get("projection_key") or "").strip()
        metadata = _metadata_json(
            {
                "role_hint": "assistant",
                "idempotency_key": projection_key,
                "business_harness": {
                    "protocol": BUSINESS_HARNESS_PROTOCOL,
                    "event": "task.terminal_result",
                    "task_id": result.get("task_id"),
                    "turn_id": result.get("turn_id"),
                    "run_id": result.get("run_id"),
                    "approval_request_id": approval_request_id,
                },
                "ui": {
                    "workflowAction": "business_harness_terminal",
                    "businessResult": result,
                    "thinkingSteps": _thinking_steps(run),
                },
            },
        )
        content = _message_for_result(result, approval_request_id)
        if runtime.get("enterprise_cognition"):
            content += "\n经营指标另附核验回执；执行完成本身不代表目标达成。"
        deliverables = completed_deliverable_lines(run)
        if deliverables and str(result.get("status") or "") == "completed":
            content = "\n".join([content, *deliverables])
        message_id = get_conversation_service().save_message(
            session_id=session_id,
            user_id=str(run.user_id or ""),
            role="assistant",
            content=content[:8000],
            intent="business_harness_result",
            metadata=metadata,
            idempotency_key=projection_key,
        )
        if runtime.get("enterprise_cognition"):
            from app.application.enterprise_cognition.outcomes import recover_terminal_outcome

            try:
                recover_terminal_outcome(run.run_id)
            except RECOVERABLE_ERRORS as exc:
                logger.warning(
                    "enterprise outcome remains pending run_id=%s type=%s",
                    run.run_id,
                    type(exc).__name__,
                )
        return message_id
    except RECOVERABLE_ERRORS as exc:
        logger.warning(
            "business harness result projection failed run_id=%s type=%s",
            normalized_run_id,
            type(exc).__name__,
        )
        return None


__all__ = ["project_enterprise_outcome_to_conversation", "project_terminal_run_to_conversation"]
