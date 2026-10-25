"""AI copilot drafts for the client-side 客来来 customer inbox.

The service deliberately stops at an approved manual-send draft.  It has no
customer-message write capability and stores no copy of the source transcript.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.desktop_runtime.paths import ensure_desktop_dirs
from app.services.kellai_copilot_llm import (
    KellaiCopilotError,
)
from app.services.kellai_copilot_llm import (
    content_from_completion as _content_from_completion,
)
from app.services.kellai_copilot_llm import (
    conversation_input as _conversation_input,
)
from app.services.kellai_copilot_llm import (
    now_iso as _now_iso,
)
from app.services.kellai_copilot_llm import (
    parse_json_content as _parse_json_content,
)
from app.services.kellai_copilot_store import (
    read_store,
    write_store,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

_LOCK = threading.Lock()
_MAX_STORED_DRAFTS = 200
_ALLOWED_RISKS = {"low", "medium", "high", "critical"}
_TERMINAL_STATUSES = {"approved_for_manual_send", "rejected"}


def _store_path() -> Path:
    root = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))["root"]
    path = root / "config" / "kellai-copilot-drafts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read() -> dict[str, Any]:
    return read_store(_store_path())


def _write(value: dict[str, Any]) -> None:
    write_store(_store_path(), value)


def _public_draft(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "draft_id": str(value.get("draft_id") or ""),
        "customer_id": int(value.get("customer_id") or 0),
        "summary": str(value.get("summary") or ""),
        "intent": str(value.get("intent") or ""),
        "risk_level": str(value.get("risk_level") or "medium"),
        "next_action": str(value.get("next_action") or ""),
        "reply_draft": str(value.get("reply_draft") or ""),
        "evidence_message_ids": list(value.get("evidence_message_ids") or []),
        "status": str(value.get("status") or "pending_approval"),
        "created_at": str(value.get("created_at") or ""),
        "decided_at": str(value.get("decided_at") or ""),
        "decision_note": str(value.get("decision_note") or ""),
        "model": str(value.get("model") or ""),
    }


def _public_follow_up_task(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "task_id": str(value.get("task_id") or ""),
        "customer_id": int(value.get("customer_id") or 0),
        "source_draft_id": str(value.get("source_draft_id") or ""),
        "title": str(value.get("title") or ""),
        "description": str(value.get("description") or ""),
        "priority": str(value.get("priority") or "normal"),
        "status": str(value.get("status") or "open"),
        "due_at": str(value.get("due_at") or ""),
        "created_at": str(value.get("created_at") or ""),
        "completed_at": str(value.get("completed_at") or ""),
        "cancelled_at": str(value.get("cancelled_at") or ""),
        "outcome_result": str(value.get("outcome_result") or ""),
    }


def _audit(*, actor: int | str | None, action: str, payload: dict[str, Any]) -> None:
    try:
        from app.mod_sdk.audit import write_audit_event

        write_audit_event(actor=actor, action=action, payload=payload)
    except RECOVERABLE_ERRORS:
        # Draft persistence remains authoritative even if the shared audit DB
        # is temporarily unavailable during desktop fast-start.
        return


async def generate_draft(
    *,
    customer_id: int,
    customer: dict[str, Any],
    messages: list[dict[str, Any]],
    actor: int | str | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    transcript, evidence_ids, fingerprint = _conversation_input(messages)
    recent_outcomes = [
        {
            "previous_action": task["description"],
            "outcome": task["outcome_result"],
        }
        for task in list_follow_up_tasks(customer_id)[:5]
        if task.get("outcome_result")
    ]
    customer_context = {
        "stage": str(customer.get("stage_label") or customer.get("stage") or ""),
        "channels": list(customer.get("channel_sources") or []),
        "recent_follow_up_outcomes": recent_outcomes,
    }
    system_prompt = """你是企业客户沟通副驾驶。请只基于给定会话生成结构化结果，不编造价格、承诺、库存、交期或公司政策。
输出严格 JSON，字段如下：
{"summary":"不超过120字的事实摘要","intent":"客户当前意图","risk_level":"low|medium|high|critical","next_action":"建议的下一步","reply_draft":"可供人工审核的中文回复草稿"}
要求：回复草稿不得声称已经执行任何动作；涉及退款、合同、价格、付款、法律、安全或明确承诺时 risk_level 至少为 high。"""
    system_prompt += (
        "\n若提供 recent_follow_up_outcomes，请参考结果调整建议，避免重复已失败或无效的动作。"
    )
    user_prompt = json.dumps(
        {"customer_context": customer_context, "conversation": json.loads(transcript)},
        ensure_ascii=False,
    )
    try:
        from app.infrastructure.llm.invoke import chat_completion_openai_format

        result = await chat_completion_openai_format(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=700,
            profile="customer_copilot",
            request=request,
        )
    except RECOVERABLE_ERRORS as exc:
        raise KellaiCopilotError("当前 AI 模型暂时不可用，请检查模型配置后重试") from exc
    content = _content_from_completion(result)
    if not content:
        raise KellaiCopilotError("当前没有可用的 AI 模型，请先完成模型配置")
    parsed = _parse_json_content(content)

    summary = str(parsed.get("summary") or "").strip()[:600]
    intent = str(parsed.get("intent") or "").strip()[:200]
    next_action = str(parsed.get("next_action") or "").strip()[:600]
    reply_draft = str(parsed.get("reply_draft") or "").strip()[:4000]
    risk_level = str(parsed.get("risk_level") or "medium").strip().lower()
    if risk_level not in _ALLOWED_RISKS:
        risk_level = "medium"
    if not summary or not reply_draft:
        raise KellaiCopilotError("AI 没有生成完整摘要与回复草稿，请重试")

    now = _now_iso()
    draft_id = secrets.token_urlsafe(18)
    record = {
        "draft_id": draft_id,
        "customer_id": int(customer_id),
        "conversation_fingerprint": fingerprint,
        "summary": summary,
        "intent": intent,
        "risk_level": risk_level,
        "next_action": next_action,
        "reply_draft": reply_draft,
        "evidence_message_ids": evidence_ids,
        "status": "pending_approval",
        "created_at": now,
        "created_by": str(actor or ""),
        "decided_at": "",
        "decided_by": "",
        "decision_note": "",
        "model": str(result.get("model") or "") if isinstance(result, dict) else "",
    }
    with _LOCK:
        state = _read()
        raw_drafts = state.get("drafts")
        drafts: dict[str, Any] = dict(raw_drafts) if isinstance(raw_drafts, dict) else {}
        drafts[draft_id] = record
        ordered = sorted(
            (drafts or {}).values(),
            key=lambda item: str(item.get("created_at") or "") if isinstance(item, dict) else "",
            reverse=True,
        )[:_MAX_STORED_DRAFTS]
        state["drafts"] = {
            str(item.get("draft_id")): item for item in ordered if isinstance(item, dict)
        }
        _write(state)
    _audit(
        actor=actor,
        action="kellai.copilot_draft.generated",
        payload={
            "draft_id": draft_id,
            "customer_id": int(customer_id),
            "risk_level": risk_level,
            "status": "pending_approval",
            "evidence_count": len(evidence_ids),
        },
    )
    return _public_draft(record) or {}


def latest_draft(customer_id: int) -> dict[str, Any] | None:
    with _LOCK:
        state = _read()
        drafts = state.get("drafts") if isinstance(state.get("drafts"), dict) else {}
        matching = [
            item
            for item in (drafts or {}).values()
            if isinstance(item, dict) and int(item.get("customer_id") or 0) == int(customer_id)
        ]
    if not matching:
        return None
    latest = max(matching, key=lambda item: str(item.get("created_at") or ""))
    return _public_draft(latest)


def decide_draft(
    *,
    draft_id: str,
    decision: str,
    actor: int | str | None = None,
    note: str = "",
) -> dict[str, Any]:
    target_status = "approved_for_manual_send" if decision == "approve" else "rejected"
    with _LOCK:
        state = _read()
        drafts = state.get("drafts") if isinstance(state.get("drafts"), dict) else {}
        if not isinstance(drafts, dict):
            drafts = {}
        record = drafts.get(draft_id)
        if not isinstance(record, dict):
            raise KellaiCopilotError("回复草稿不存在或已被清理")
        current = str(record.get("status") or "pending_approval")
        if current in _TERMINAL_STATUSES and current != target_status:
            raise KellaiCopilotError("该草稿已经完成审批，不能重复变更")
        if current not in {"pending_approval", target_status}:
            raise KellaiCopilotError("该草稿当前不能审批")
        if current == "pending_approval":
            record["status"] = target_status
            record["decided_at"] = _now_iso()
            record["decided_by"] = str(actor or "")
            record["decision_note"] = str(note or "").strip()[:500]
            drafts[draft_id] = record
            state["drafts"] = drafts
            _write(state)
    _audit(
        actor=actor,
        action=(
            "kellai.copilot_draft.approved"
            if decision == "approve"
            else "kellai.copilot_draft.rejected"
        ),
        payload={
            "draft_id": draft_id,
            "customer_id": int(record.get("customer_id") or 0),
            "risk_level": str(record.get("risk_level") or ""),
            "status": target_status,
        },
    )
    return _public_draft(record) or {}


def create_follow_up_task(
    *,
    draft_id: str,
    actor: int | str | None = None,
) -> dict[str, Any]:
    """Approve and execute the bounded internal action proposed by a draft.

    The draft id is the idempotency key: retries always return the same task.
    This action only creates a local follow-up item; it cannot message a customer
    or mutate the source CRM.
    """

    with _LOCK:
        state = _read()
        drafts = state.get("drafts") if isinstance(state.get("drafts"), dict) else {}
        if not isinstance(drafts, dict):
            drafts = {}
        draft = drafts.get(str(draft_id))
        if not isinstance(draft, dict):
            raise KellaiCopilotError("回复草稿不存在或已被清理")
        if str(draft.get("status") or "") == "rejected":
            raise KellaiCopilotError("已拒绝的草稿不能创建跟进任务")

        raw_tasks = state.get("follow_up_tasks")
        tasks: dict[str, Any] = dict(raw_tasks) if isinstance(raw_tasks, dict) else {}
        existing = next(
            (
                item
                for item in (tasks or {}).values()
                if isinstance(item, dict)
                and str(item.get("source_draft_id") or "") == str(draft_id)
            ),
            None,
        )
        if isinstance(existing, dict):
            return _public_follow_up_task(existing) or {}

        customer_id = int(draft.get("customer_id") or 0)
        if customer_id <= 0:
            raise KellaiCopilotError("草稿没有有效客户，无法创建跟进任务")
        next_action = str(draft.get("next_action") or "").strip()
        if not next_action:
            raise KellaiCopilotError("AI 尚未给出可执行的下一步")

        risk = str(draft.get("risk_level") or "medium")
        due_hours = {"critical": 4, "high": 8, "medium": 24, "low": 48}.get(risk, 24)
        priority = "urgent" if risk == "critical" else "high" if risk == "high" else "normal"
        created_at = datetime.now(UTC)
        task_id = secrets.token_urlsafe(18)
        intent = str(draft.get("intent") or "客户事项").strip()[:80] or "客户事项"
        record = {
            "task_id": task_id,
            "customer_id": customer_id,
            "source_draft_id": str(draft_id),
            "title": f"客户跟进 · {intent}",
            "description": next_action[:1000],
            "priority": priority,
            "status": "open",
            "due_at": (created_at + timedelta(hours=due_hours)).isoformat(),
            "created_at": created_at.isoformat(),
            "created_by": str(actor or ""),
            "completed_at": "",
            "completed_by": "",
            "cancelled_at": "",
            "cancelled_by": "",
            "outcome_result": "",
        }
        tasks[task_id] = record
        state["version"] = 2
        state["follow_up_tasks"] = tasks
        _write(state)

    _audit(
        actor=actor,
        action="kellai.follow_up_task.created",
        payload={
            "task_id": task_id,
            "customer_id": customer_id,
            "source_draft_id": str(draft_id),
            "priority": priority,
            "status": "open",
        },
    )
    return _public_follow_up_task(record) or {}


def list_follow_up_tasks(customer_id: int) -> list[dict[str, Any]]:
    with _LOCK:
        state = _read()
        tasks = (
            state.get("follow_up_tasks") if isinstance(state.get("follow_up_tasks"), dict) else {}
        )
        matching = [
            item
            for item in (tasks or {}).values()
            if isinstance(item, dict) and int(item.get("customer_id") or 0) == int(customer_id)
        ]
    matching.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return [public for item in matching if (public := _public_follow_up_task(item)) is not None]


def follow_up_metrics(customer_id: int) -> dict[str, Any]:
    tasks = list_follow_up_tasks(customer_id)
    outcome_counts = {
        "success": sum(task.get("outcome_result") == "success" for task in tasks),
        "no_result": sum(task.get("outcome_result") == "no_result" for task in tasks),
        "failed": sum(task.get("outcome_result") == "failed" for task in tasks),
    }
    evaluated = sum(outcome_counts.values())
    return {
        "total": len(tasks),
        "open": sum(task.get("status") == "open" for task in tasks),
        "completed": sum(task.get("status") == "completed" for task in tasks),
        "failed": sum(task.get("status") == "failed" for task in tasks),
        "cancelled": sum(task.get("status") == "cancelled" for task in tasks),
        "outcomes": outcome_counts,
        "success_rate": round(outcome_counts["success"] / evaluated, 4) if evaluated else None,
    }


def decide_follow_up_task(
    *,
    task_id: str,
    decision: str,
    actor: int | str | None = None,
    outcome_result: str = "",
) -> dict[str, Any]:
    if decision not in {"complete", "cancel"}:
        raise KellaiCopilotError("不支持的跟进任务操作")
    if decision == "complete" and outcome_result not in {"success", "no_result", "failed"}:
        raise KellaiCopilotError("完成任务时必须记录有效、无结果或失败")
    target_status = (
        "failed"
        if decision == "complete" and outcome_result == "failed"
        else "completed"
        if decision == "complete"
        else "cancelled"
    )
    timestamp_field = "completed_at" if decision == "complete" else "cancelled_at"
    actor_field = "completed_by" if decision == "complete" else "cancelled_by"
    changed = False
    with _LOCK:
        state = _read()
        tasks = (
            state.get("follow_up_tasks") if isinstance(state.get("follow_up_tasks"), dict) else {}
        )
        if not isinstance(tasks, dict):
            tasks = {}
        record = tasks.get(str(task_id))
        if not isinstance(record, dict):
            raise KellaiCopilotError("跟进任务不存在或已被清理")
        current = str(record.get("status") or "open")
        if current == target_status:
            return _public_follow_up_task(record) or {}
        if current != "open":
            raise KellaiCopilotError("该跟进任务已经结束，不能重复变更")
        record["status"] = target_status
        record[timestamp_field] = _now_iso()
        record[actor_field] = str(actor or "")
        if decision == "complete":
            record["outcome_result"] = outcome_result
        tasks[str(task_id)] = record
        state["follow_up_tasks"] = tasks
        _write(state)
        changed = True

    if changed:
        _audit(
            actor=actor,
            action=(
                "kellai.follow_up_task.failed"
                if decision == "complete" and outcome_result == "failed"
                else "kellai.follow_up_task.completed"
                if decision == "complete"
                else "kellai.follow_up_task.cancelled"
            ),
            payload={
                "task_id": str(task_id),
                "customer_id": int(record.get("customer_id") or 0),
                "source_draft_id": str(record.get("source_draft_id") or ""),
                "status": target_status,
                "outcome_result": outcome_result if decision == "complete" else "",
            },
        )
    return _public_follow_up_task(record) or {}


def purge_all(*, actor: int | str | None = None) -> dict[str, int]:
    """Delete every locally derived customer artifact after binding revocation."""

    with _LOCK:
        state = _read()
        raw_drafts = state.get("drafts")
        drafts: dict[str, Any] = dict(raw_drafts) if isinstance(raw_drafts, dict) else {}
        raw_tasks = state.get("follow_up_tasks")
        tasks: dict[str, Any] = dict(raw_tasks) if isinstance(raw_tasks, dict) else {}
        counts = {"drafts_deleted": len(drafts), "tasks_deleted": len(tasks)}
        path = _store_path()
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise KellaiCopilotError("无法清理本地客户派生数据，请重试解除连接") from exc
    _audit(
        actor=actor,
        action="kellai.customer_artifacts.purged",
        payload=counts,
    )
    return counts
