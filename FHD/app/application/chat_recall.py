"""Recall a transcript suffix after its proven business effects are reversed."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.application.agent_orchestrator.business_harness import (
    business_write_requested,
    extract_payload_business_result,
    harness_event_context,
)
from app.application.agent_orchestrator.run_repository import get_agent_run_repository
from app.application.agent_orchestrator.task_models import mod_id_of_run, tenant_id_of_run
from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
from app.application.task_conversation_store import (
    ConversationRevisionError,
    task_conversation_store,
)
from app.db.session import get_db
from app.domain.task_lifecycle.results import execution_result_outcome_unknown
from app.infrastructure.tenant_scope import tenant_scope

_UNVERIFIED = "这段对话有无法证实归属或撤销范围的业务操作，请在原任务中核对。会话记录已保留。"
_ACTIVE = "当前会话仍有任务在执行或等待处理，请先到原任务核对，再撤回。"


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _metadata(row: dict) -> dict:
    try:
        return _object(json.loads(row["metadata"] or "{}"))
    except (TypeError, ValueError):
        return {}


def _at(timestamp: str | None) -> float:
    try:
        return datetime.fromisoformat(timestamp or "").timestamp()
    except ValueError:
        return 0.0


def _read_only(tool_id: str, action: str) -> bool:
    spec = get_tool_action_spec(tool_id, action)
    return bool(spec and spec.read_only) or (tool_id, action) == ("elt_import", "preview")


def _deleted_turn_is_compensated(
    run, harness, *, user_id: str, tenant_id: str, mod_id: str
) -> bool:
    from app.application.elt.chat_recall import imports_already_rolled_back
    from app.application.elt.errors import EltConflict

    if not user_id.isdecimal() or not tenant_id.isdecimal() or int(tenant_id) <= 0:
        return False
    candidates = []
    for step in run.steps:
        if _read_only(step.tool_id, step.action):
            continue
        if (step.tool_id, step.action) != ("elt_import", "execute") or step.status != "completed":
            return False
        candidates.append(({**harness, "step_id": step.step_id, "mod_id": mod_id}, step.output))
    if not candidates:
        return False
    try:
        with tenant_scope(int(tenant_id)), get_db() as db:
            return imports_already_rolled_back(
                db, candidates=candidates, owner_user_id=int(user_id), tenant_id=int(tenant_id)
            )
    except EltConflict:
        return False


def _undo_candidates(
    rows: list[dict],
    *,
    session_id: str,
    user_id: str,
    tenant_id: str,
    mod_id: str,
) -> list[tuple[dict, dict]]:
    known_turns: set[str] = set()
    bound_runs: dict[str, set[str]] = {}
    recorded_runs: set[str] = set()
    unbound_write = False
    cutoff = _at(rows[0]["timestamp"])
    for row in rows:
        metadata = _metadata(row)
        binding = _object(metadata.get("business_harness"))
        summary = _object(metadata.get("summary"))
        ui = _object(metadata.get("ui"))
        turn = str(binding.get("turn_id") or ui.get("turnId") or "")
        rid = str(binding.get("run_id") or "")
        if turn:
            known_turns.add(turn)
        if rid:
            recorded_runs.add(rid)
        if (
            binding.get("recall_bound") is True
            and rid
            and turn
            and binding.get("conversation_id") == session_id
        ):
            bound_runs.setdefault(rid, set()).add(turn)
        elif not rid and (
            ui.get("businessResult")
            or ui.get("approvalCard")
            or summary.get("toolCall")
            or summary.get("plan_id")
            or summary.get("status") in {"unknown", "waiting_approval"}
            or (row["role"] == "user" and business_write_requested(row["content"]))
        ):
            unbound_write = True

    runs = get_agent_run_repository().list_task_runs_for_user(user_id=user_id)
    candidates: list[tuple[dict, dict]] = []
    matched: set[str] = set()
    for run in sorted(runs, key=lambda item: (item.created_at, item.run_id), reverse=True):
        harness = harness_event_context(run)
        if (
            harness["conversation_id"] != session_id
            or tenant_id_of_run(run) != tenant_id
            or mod_id_of_run(run) != mod_id
        ):
            continue
        if run.status not in {"completed", "failed", "cancelled", "rejected"}:
            raise ConversationRevisionError(_ACTIVE)
        if (
            run.run_id not in recorded_runs
            and harness["turn_id"] not in known_turns
            and _at(run.updated_at) < cutoff
        ):
            continue
        matched.add(run.run_id)
        payload = _object(run.final_output.get("chat_payload"))
        if execution_result_outcome_unknown(run.final_output) or execution_result_outcome_unknown(
            payload
        ):
            raise ConversationRevisionError(_UNVERIFIED)
        for audit in run.metadata.get("stream_tool_audit") or []:
            record = _object(_object(audit).get("record"))
            if not _read_only(str(record.get("tool_id") or ""), str(record.get("action") or "")):
                raise ConversationRevisionError(_UNVERIFIED)
        if not run.steps and (
            business_write_requested(run.message)
            or extract_payload_business_result(payload)
            or any(not _read_only(call.tool_id, call.action) for call in run.tool_calls)
        ):
            raise ConversationRevisionError(_UNVERIFIED)
        if (
            run.run_id not in recorded_runs
            and harness["turn_id"] not in known_turns
            and run.status == "completed"
            and _deleted_turn_is_compensated(
                run, harness, user_id=user_id, tenant_id=tenant_id, mod_id=mod_id
            )
        ):
            continue
        for step in reversed(run.steps):
            if _read_only(step.tool_id, step.action) or (
                step.status in {"pending", "skipped"}
                and not step.started_at
                and not step.attempt_count
                and not step.output
            ):
                continue
            if (
                (step.tool_id, step.action) != ("elt_import", "execute")
                or run.status != "completed"
                or step.status != "completed"
                or harness["turn_id"] not in bound_runs.get(run.run_id, ())
            ):
                raise ConversationRevisionError(_UNVERIFIED)
            candidates.append(({**harness, "step_id": step.step_id, "mod_id": mod_id}, step.output))
    if unbound_write or recorded_runs - matched:
        raise ConversationRevisionError(_UNVERIFIED)
    return candidates


def recall_messages(
    *,
    session_id: str,
    user_id: int,
    message_id: int,
    tenant_id: str,
    mod_id: str,
    business_confirmed: bool,
    require_rollback_permission: Callable[[], None],
) -> dict:
    from app.application.ai_chat.dialogue_memory import chat_recall_guard
    from app.application.elt.chat_recall import prepare_import_rollback, rollback_imports

    with chat_recall_guard(
        {
            "session_id": session_id,
            "local_user_id": user_id,
            "tenant_id": tenant_id,
            "mod_id": mod_id,
        }
    ):
        revision, rows = task_conversation_store.recall_snapshot(
            session_id=session_id, user_id=user_id, message_id=message_id
        )
        candidates = _undo_candidates(
            rows,
            session_id=session_id,
            user_id=str(user_id),
            tenant_id=tenant_id,
            mod_id=mod_id,
        )
        rolled_back = 0
        if candidates:
            if not business_confirmed:
                raise ConversationRevisionError(
                    "这段对话有已执行的业务操作，请使用新版撤回功能确认范围。"
                )
            require_rollback_permission()
            if not tenant_id.isdecimal() or int(tenant_id) <= 0:
                raise PermissionError("缺少可验证的业务归属")
            scope = {"owner_user_id": user_id, "tenant_id": int(tenant_id)}
            with tenant_scope(int(tenant_id)):
                with get_db() as db:
                    plan = prepare_import_rollback(db, candidates=candidates, **scope)
                if task_conversation_store.recall_snapshot(
                    session_id=session_id, user_id=user_id, message_id=message_id
                ) != (revision, rows):
                    raise ConversationRevisionError("会话已有新消息，请重新核对撤回范围")
                with get_db() as db:
                    rolled_back = rollback_imports(db, plan, **scope)
        deleted = task_conversation_store.delete_messages_from(
            session_id=session_id,
            user_id=user_id,
            message_id=message_id,
            expected_revision=revision,
            expected_ids=tuple(row["id"] for row in rows),
        )
        return {"success": True, "deleted": deleted, "rolled_back": rolled_back}
