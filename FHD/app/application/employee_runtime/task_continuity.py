"""Durable multi-turn task continuity for employee handoff and recovery.

Business success is taken only from tool and handoff execution records.
Dialogue, model text, and compression summaries are not execution results.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.application.agent_orchestrator.context_window_manager import (
    ContextWindowManager,
    estimate_messages_tokens,
)

SOURCE = "employee_runtime.task_continuity"
CONTINUE_TEXT = "继续执行剩余任务"
_TERMINAL_OK = "completed"
_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[str, threading.RLock] = {}
_ACTIONS = {
    "start",
    "pause",
    "resume",
    "append_requirements",
    "leave",
    "reenter",
    "read",
    "handoff",
    "retry_handoff",
    "split",
    "child_return",
    "run_tools",
    "retry_step",
    "append_turn",
    "compress",
    "continue_compressed",
    "restart",
    "chain",
    "metrics",
}
_EMPLOYEE_FLAGS = ("available", "timeout", "crash", "unrecoverable")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _empty_state() -> dict[str, Any]:
    return {
        "tasks": {},
        "handoffs": {},
        "tool_calls": {},
        "events": [],
        "recoveries": [],
        "restarts": [],
        "side_effects": {},
        "conversations": {},
    }


class _SummaryCache:
    def __init__(self) -> None:
        self.conversation_history: list[dict[str, str]] = []
        self.summary = ""
        self.summary_covered_until = -1
        self.summary_fingerprint = ""


class TaskContinuityRuntime:
    """Process runtime with a JSON ledger. Restart drops memory and reloads the file."""

    def __init__(self, path: str | Path, *, workspace: str | Path | None = None) -> None:
        self.path = Path(path)
        self.workspace = Path(workspace) if workspace is not None else self.path.parent
        self.state = _empty_state()

    def dispatch(
        self,
        employee_id: str,
        text: str,
        payload: dict[str, Any],
        *,
        user_id: Any = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        op = str(payload.get("op") or "").strip()
        actor = str(employee_id or "").strip()
        user = str(payload["user_id"] if payload.get("user_id") is not None else user_id)
        tenant = str(payload.get("tenant_id") or "")
        session = str(payload.get("session_id") or session_id or "")
        with _path_lock(self.path), self._exclusive():
            self._read()
            handler = {
                "start": self._start,
                "pause": self._pause,
                "resume": self._resume,
                "append_requirements": self._append_requirements,
                "leave": self._leave,
                "reenter": self._reenter,
                "read": self._read_task,
                "handoff": self._handoff,
                "retry_handoff": self._retry_handoff,
                "split": self._split,
                "child_return": self._child_return,
                "run_tools": self._run_tools,
                "retry_step": self._retry_step,
                "append_turn": self._append_turn,
                "compress": self._compress,
                "continue_compressed": self._continue_compressed,
                "restart": self._restart,
                "chain": self._chain,
                "metrics": self._metrics_op,
            }.get(op)
            if handler is None:
                return self._fail(None, "unknown_op", f"不支持的连续性操作: {op}")
            return handler(actor, text, payload, user=user, tenant=tenant, session=session)

    def pollution_findings(self) -> list[dict[str, str]]:
        tasks = list(self.state["tasks"].values())
        findings: list[dict[str, str]] = []
        for task in tasks:
            blob = json.dumps(
                {
                    "business_data": task["business_data"],
                    "conditions": task["conditions"],
                    "requirements": task["requirements"],
                    "steps": [
                        {"params": step.get("params"), "result": step.get("result_payload")}
                        for step in task["steps"]
                    ],
                    "snapshot": task["context_snapshot"],
                },
                ensure_ascii=False,
                default=str,
            )
            for other in tasks:
                if other["task_id"] == task["task_id"]:
                    continue
                marker = str(other["business_data"].get("isolation_marker") or "")
                if not marker or marker not in blob:
                    continue
                same_owner = (
                    other["tenant_id"] == task["tenant_id"]
                    and other["user_id"] == task["user_id"]
                    and other.get("root_task_id") == task.get("root_task_id")
                )
                if not same_owner:
                    findings.append(
                        {
                            "task_id": task["task_id"],
                            "foreign_task_id": other["task_id"],
                            "marker": marker,
                        }
                    )
        return findings

    def duplicate_side_effects(self) -> list[str]:
        return [
            key
            for key, item in self.state["side_effects"].items()
            if int(item.get("invocations") or 0) > 1
        ]

    def orphans(self) -> list[str]:
        ids = set(self.state["tasks"])
        bad: list[str] = []
        for task in self.state["tasks"].values():
            parent = str(task.get("parent_task_id") or "")
            if parent and parent not in ids:
                bad.append(task["task_id"])
            for child_id in task.get("child_task_ids") or []:
                if child_id not in ids:
                    bad.append(str(child_id))
        return bad

    def _start(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task_id = _new_id("task")
        steps = [
            _step_from(task_id, raw, index) for index, raw in enumerate(payload.get("steps") or [])
        ]
        task: dict[str, Any] = {
            "task_id": task_id,
            "parent_task_id": str(payload.get("parent_task_id") or ""),
            "root_task_id": str(payload.get("root_task_id") or task_id),
            "child_task_ids": [],
            "conversation_id": str(payload.get("conversation_id") or _new_id("conv")),
            "tenant_id": scope["tenant"],
            "user_id": scope["user"],
            "session_id": scope["session"],
            "owner_employee": actor,
            "holder_employee": actor,
            "authorized_employees": [actor],
            "grants": {actor: ["*"]},
            "goal": str(payload.get("goal") or text or ""),
            "conditions": dict(payload.get("conditions") or {}),
            "constraints": list(payload.get("constraints") or []),
            "business_data": dict(payload.get("business_data") or {}),
            "requirements": list(payload.get("requirements") or []),
            "steps": steps,
            "status": "running",
            "error_code": "",
            "error_message": "",
            "retry_count": 0,
            "context_version": 1,
            "context_snapshot": {},
            "completed_steps": [],
            "remaining_steps": [step["step_id"] for step in steps],
            "messages": [],
            "confirmed_facts": {},
            "speculative": [],
            "rejected_claims": [],
            "prior_results": [],
            "result_payload": {},
            "aggregate": {},
            "completion_condition": str(payload.get("completion_condition") or "all_steps_success"),
            "handoff_ids": [],
            "compression_strategy": "",
            "compression_count": 0,
            "compressed_summary": "",
            "facts_after_first_compression": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        if task["goal"]:
            task["confirmed_facts"]["goal"] = task["goal"]
        if payload.get("fact_params") is not None:
            task["confirmed_facts"]["params"] = payload["fact_params"]
        if task["constraints"]:
            task["confirmed_facts"]["constraints"] = list(task["constraints"])
        self.state["tasks"][task_id] = task
        key = _conv_key(task)
        self.state["conversations"][key] = {"task_id": task_id, "active": True}
        self._touch(task)
        limit = payload.get("execute_limit")
        if limit is not None:
            self._execute_pending(task, actor, limit=int(limit))
            self._touch(task)
        self._event("task_created", task)
        self._write()
        return self._envelope(task)

    def _pause(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        task["status"] = "paused"
        self._touch(task)
        self._event("task_paused", task)
        self._write()
        return self._envelope(task, business=False)

    def _resume(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        phrase = str(payload.get("text") or text or "").strip()
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        if phrase != CONTINUE_TEXT:
            return self._fail(task, "resume_phrase_mismatch", "恢复必须使用「继续执行剩余任务」")
        if task["status"] != "paused":
            return self._fail(task, "not_paused", "只有暂停中的原任务可以继续")
        task["status"] = "running"
        self._execute_pending(task, actor, limit=None)
        self._touch(task)
        self._event("task_resumed", task)
        self._write()
        return self._envelope(task)

    def _append_requirements(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        for req in payload.get("requirements") or []:
            item = str(req)
            if item and item not in task["requirements"]:
                task["requirements"].append(item)
                task["steps"].append(
                    _step_from(
                        task["task_id"],
                        {"name": item, "tool": str(payload.get("tool") or "note"), "params": {}},
                        len(task["steps"]),
                    )
                )
        if isinstance(payload.get("conditions"), dict):
            task["conditions"] = _merge_conditions(task["conditions"], payload["conditions"])
        for constraint in payload.get("constraints") or []:
            if constraint not in task["constraints"]:
                task["constraints"].append(constraint)
        if any(step["status"] != "success" for step in task["steps"]):
            task["status"] = "paused"
        self._touch(task)
        self._event("requirements_merged", task)
        self._write()
        return self._envelope(task, business=False)

    def _leave(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=False)
        if not _is_task(task):
            return task
        key = _conv_key(task)
        record = self._conversation(key) or {"task_id": task["task_id"], "active": True}
        record["active"] = False
        self.state["conversations"][key] = record
        self._event("conversation_left", task)
        self._write()
        return self._envelope(task, business=False)

    def _reenter(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        key = f"{scope['tenant']}:{scope['user']}:{payload.get('conversation_id') or ''}"
        record = self._conversation(key)
        if record is not None and record.get("active"):
            return self._fail(None, "session_still_active", "会话尚未离开")
        task = self.state["tasks"].get("" if record is None else str(record.get("task_id") or ""))
        if task is None or not self._allows(task, actor, scope):
            return self._fail(None, "conversation_not_found", "找不到可恢复的原会话任务")
        self.state["conversations"][key] = {"task_id": task["task_id"], "active": True}
        self._event("conversation_reentered", task)
        self._write()
        return self._envelope(task, business=task["status"] == _TERMINAL_OK)

    def _read_task(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=False)
        if not _is_task(task):
            return task
        self._event("context_read", task)
        return self._envelope(task, business=task["status"] == _TERMINAL_OK)

    def _handoff(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        target = str(payload.get("target_employee") or "")
        if not target:
            return self._fail(task, "missing_target", "交接必须指定目标员工")
        record = self._perform_handoff(
            task,
            source=actor,
            target=target,
            permissions=list(payload.get("permissions") or []),
            new_conditions=dict(payload.get("conditions") or {}),
            idempotency_key=str(
                payload.get("idempotency_key") or f"{task['task_id']}:handoff:{actor}:{target}"
            ),
            effect=dict(payload.get("effect") or {"action": "execute"}),
            policy=str(payload.get("policy") or "retry"),
            target_tenant_id=str(payload.get("target_tenant_id") or ""),
            delegated_tool=str(payload.get("delegated_tool") or ""),
            delegated_action=str(payload.get("delegated_action") or ""),
            delegated_params=dict(payload.get("delegated_params") or {})
            if isinstance(payload.get("delegated_params"), dict)
            else None,
        )
        self._event("handoff_recorded", task)
        self._write()
        return self._envelope(task, extra={"handoff": _presented_handoff(record)})

    def _retry_handoff(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        previous_id = str(
            payload.get("handoff_id") or (task["handoff_ids"][-1] if task["handoff_ids"] else "")
        )
        previous = self.state["handoffs"].get(previous_id)
        if previous is None:
            return self._fail(task, "handoff_not_found", "没有可重试的交接")
        task["retry_count"] = int(task["retry_count"]) + 1
        inherited = _clone(previous["context_snapshot"])
        policy = str(payload.get("policy") or previous.get("policy") or "retry")
        if policy == "rollback":
            key = str(previous["idempotency_key"])
            effect = self.state["side_effects"].get(key)
            if effect is not None:
                effect["rolled_back"] = True
                self.state["side_effects"].pop(key, None)
            task["status"] = "failed"
            task["error_code"] = "rolled_back"
            task["error_message"] = "交接已按策略回滚，未重复执行副作用"
            recovery = self._recovery(task, previous_id, "rollback", task["error_message"])
            self._event("handoff_rolled_back", task)
            self._write()
            return self._envelope(
                task, business=False, extra={"recovery_record": recovery, "inherited": inherited}
            )
        flags = self._flags(str(previous["target_employee"]))
        if flags.get("unrecoverable"):
            task["status"] = "failed"
            task["error_code"] = str(previous.get("error_code") or "employee_unrecoverable")
            task["error_message"] = str(previous.get("error_message") or "目标员工不可恢复")
            recovery = self._recovery(task, previous_id, "unrecoverable", task["error_message"])
            self._event("handoff_unrecoverable", task)
            self._write()
            return self._envelope(
                task, business=False, extra={"recovery_record": recovery, "inherited": inherited}
            )
        record = self._perform_handoff(
            task,
            source=str(previous["source_employee"]),
            target=str(previous["target_employee"]),
            permissions=list(previous.get("permissions") or []),
            new_conditions={},
            idempotency_key=str(previous["idempotency_key"]),
            effect=dict(previous.get("effect") or {}),
            policy=policy,
            retry_of=previous_id,
            inherited=inherited,
        )
        record["retry_count"] = int(task["retry_count"])
        self._event("handoff_retried", task)
        self._write()
        return self._envelope(task, extra={"handoff": record, "inherited": inherited})

    def _split(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        parent = self._authorized(payload, actor, scope, write=True)
        if not _is_task(parent):
            return parent
        specs = list(payload.get("children") or [])
        if len(specs) < 3:
            return self._fail(parent, "insufficient_children", "父任务至少要拆成 3 个子任务")
        for spec in specs:
            if not isinstance(spec, dict):
                continue
            child_id = _new_id("task")
            employee = str(spec.get("employee_id") or "")
            child = {
                **_clone(parent),
                "task_id": child_id,
                "parent_task_id": parent["task_id"],
                "root_task_id": parent["root_task_id"],
                "child_task_ids": [],
                "conversation_id": f"{parent['conversation_id']}:{child_id}",
                "owner_employee": employee,
                "holder_employee": employee,
                "authorized_employees": [employee, parent["owner_employee"]],
                "grants": {employee: ["*"], parent["owner_employee"]: ["*"]},
                "steps": [
                    _step_from(
                        child_id,
                        {
                            "step_id": "work",
                            "tool": str(spec.get("tool") or "child_work"),
                            "params": dict(spec.get("params") or {}),
                        },
                        0,
                    )
                ],
                "status": "running",
                "error_code": "",
                "error_message": "",
                "business_data": dict(spec.get("business_data") or {}),
                "result_payload": {},
                "aggregate": {},
                "handoff_ids": [],
                "messages": [],
                "prior_results": [],
                "created_at": _now(),
            }
            child["business_data"]["isolation_marker"] = str(
                spec.get("isolation_marker") or child_id
            )
            self._touch(child)
            self.state["tasks"][child_id] = child
            parent["child_task_ids"].append(child_id)
            self._event("child_created", child)
        parent["status"] = "running"
        self._touch(parent)
        self._event("task_split", parent)
        self._write()
        return self._envelope(parent, business=False)

    def _child_return(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        child = self._authorized(payload, actor, scope, write=True)
        if not _is_task(child):
            return child
        if not child["parent_task_id"]:
            return self._fail(child, "not_a_child", "只有子任务可以回传")
        self._execute_pending(child, actor, limit=None)
        step = child["steps"][0] if child["steps"] else None
        ok = step is not None and step["status"] == "success"
        child["result_payload"] = {} if step is None else _clone(step.get("result_payload") or {})
        child["status"] = _TERMINAL_OK if ok else "failed"
        child["error_code"] = "" if ok else str((step or {}).get("error_code") or "child_failed")
        child["error_message"] = (
            "" if ok else str((step or {}).get("error_message") or "子任务失败")
        )
        self._touch(child)
        parent = self.state["tasks"].get(child["parent_task_id"])
        if parent is not None:
            self._aggregate_parent(parent)
            self._touch(parent)
        self._event("child_returned", child)
        self._write()
        business = child["status"] == _TERMINAL_OK
        return self._envelope(child, business=business)

    def _run_tools(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        probe = str(payload.get("probe_tool") or "")
        probe_denied = False
        if probe:
            grant = list(task["grants"].get(actor) or [])
            probe_denied = "*" not in grant and probe not in grant
        if payload.get("model_text"):
            task["messages"].append(
                {
                    "role": "assistant",
                    "content": str(payload["model_text"]),
                    "fact": {"confidence": "speculative", "kind": "model_text"},
                }
            )
            task["speculative"].append(str(payload["model_text"]))
        only = set(payload["only_steps"]) if "only_steps" in payload else None
        if probe and only is None:
            only = set()
        self._execute_pending(task, actor, limit=None, only=only)
        self._touch(task)
        self._event("tools_executed", task)
        self._write()
        return self._envelope(
            task,
            extra={"execution_summary": _summary(task), "probe_denied": probe_denied},
        )

    def _retry_step(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        step = _find_step(task, str(payload.get("step_id") or ""))
        if step is None:
            return self._fail(task, "step_not_found", "没有该步骤")
        task["retry_count"] = int(task["retry_count"]) + 1
        if step["status"] == "success":
            self._event("retry_skipped_completed", task)
            self._write()
            return self._envelope(task, business=False, extra={"skipped": step["step_id"]})
        if step["status"] not in {"failed", "blocked"}:
            return self._fail(task, "retry_not_failed", "只能重试失败步骤")
        if not _deps_ok(task, step):
            step["status"] = "blocked"
            step["error_code"] = "dependency_not_met"
            self._rollup_steps(task)
            self._write()
            return self._envelope(task, business=False)
        step["status"] = "pending"
        step["error_code"] = ""
        self._invoke(task, step, actor)
        self._rollup_steps(task)
        self._touch(task)
        self._event("step_retried", task)
        self._write()
        return self._envelope(task, extra={"execution_summary": _summary(task)})

    def _append_turn(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        fact = dict(payload.get("fact") or {})
        message = {
            "role": str(payload.get("role") or "user"),
            "content": str(payload.get("content") or text or ""),
            "fact": fact,
        }
        task["messages"].append(message)
        self._apply_fact(task, fact)
        self._touch(task)
        self._event("turn_recorded", task)
        self._write()
        return self._envelope(task, business=False)

    def _compress(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        before = _clone(task["confirmed_facts"])
        messages = [
            {"role": str(item.get("role") or "user"), "content": str(item.get("content") or "")}
            for item in task["messages"]
        ]
        estimated = estimate_messages_tokens(messages)
        # Sit just under the framed history so the real summarizer runs, while the
        # summary request (a single prompt) still fits. Facts are not taken from it.
        budget = int(payload.get("token_budget") or max(estimated - 1, 1))
        manager = ContextWindowManager(
            token_budget=budget,
            recent_keep=2,
            summarize_threshold=4,
            enabled=True,
        )
        compressed = _await(
            manager.compress(
                messages,
                user_id=str(task["user_id"]),
                trace_id=task["task_id"],
                context=_SummaryCache(),
            )
        )
        summary = ""
        for item in compressed.messages:
            content = str(item.get("content") or "")
            if item.get("role") == "system" and content.startswith("对话历史摘要："):
                summary = content
        task["compressed_summary"] = summary
        task["compression_strategy"] = compressed.strategy
        task["compression_count"] = int(task["compression_count"]) + 1
        task["confirmed_facts"] = before
        if task["compression_count"] == 1:
            task["facts_after_first_compression"] = _clone(before)
        stable = task["facts_after_first_compression"] == task["confirmed_facts"]
        self._touch(task)
        self._event("history_compressed", task)
        self._write()
        return self._envelope(
            task,
            business=False,
            extra={
                "compression_strategy": compressed.strategy,
                "pre_message_count": compressed.pre_message_count,
                "post_message_count": compressed.post_message_count,
                "facts_before": before,
                "facts_after": task["confirmed_facts"],
                "facts_stable": stable,
                "summary_is_not_execution": True,
            },
        )

    def _continue_compressed(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        completed = [
            item
            for item in self.state["tool_calls"].values()
            if item["task_id"] == task["task_id"] and item["status"] == "success"
        ]
        restatement = {
            "goal": task["confirmed_facts"].get("goal"),
            "params": task["confirmed_facts"].get("params"),
            "constraints": task["confirmed_facts"].get("constraints"),
            "completed_ops": [
                {"tool_call_id": item["tool_call_id"], "status": item["status"]}
                for item in completed
            ],
        }
        for step in task["steps"]:
            if step["status"] == "pending":
                self._invoke(task, step, actor)
                break
        self._rollup_steps(task)
        self._touch(task)
        self._event("continued_after_compression", task)
        self._write()
        return self._envelope(
            task, extra={"restatement": restatement, "execution_summary": _summary(task)}
        )

    def _restart(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        cause = str(payload.get("cause") or "backend_restart")
        self._write()
        self.state = _empty_state()
        self._read()
        before = self._fingerprint()
        recovered: list[str] = []
        for call in self.state["tool_calls"].values():
            if call["status"] != "running":
                continue
            pid = int(call.get("submit_pid") or 0)
            if _pid_alive(pid):
                continue
            call["status"] = "recovering"
            call["resubmitted"] = False
            recovered.append(call["tool_call_id"])
            task = self.state["tasks"].get(call["task_id"])
            step = _find_step(task, call["step_id"]) if task else None
            if step is not None and step["status"] == "running":
                step["status"] = "recovering"
        for task in self.state["tasks"].values():
            if task["status"] == _TERMINAL_OK:
                continue
            if any(step["status"] == "recovering" for step in task["steps"]):
                task["status"] = "recovering"
                task["error_code"] = task.get("error_code") or "restart_inflight"
                task["error_message"] = "重启时有未完成工具，未重复提交"
        after = self._fingerprint()
        record = {
            "restart_id": _new_id("restart"),
            "cause": cause,
            "before_fingerprint": before,
            "after_fingerprint": after,
            "inflight_recovered": recovered,
            "memory_dropped": True,
            "reloaded_from": str(self.path),
            "timestamp": _now(),
            "orphan_count": len(self.orphans()),
        }
        self.state["restarts"].append(record)
        focus_id = str(payload.get("task_id") or "")
        focus = self.state["tasks"].get(focus_id)
        if focus is not None:
            self._event("restart_recovered", focus)
        self._write()
        if focus is None:
            return {
                "success": True,
                "business_success": False,
                "source": SOURCE,
                "restart": record,
                "evidence": _blank_evidence() | {"E16_restart_recovery_record": record},
            }
        return self._envelope(focus, business=False, extra={"restart": record})

    def _chain(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        task = self._authorized(payload, actor, scope, write=True)
        if not _is_task(task):
            return task
        employees = [str(item) for item in payload.get("employees") or []]
        if employees[:1] != [actor] or len(employees) != 4:
            return self._fail(task, "chain_shape", "交接链必须是发起员工起的 4 人链")
        opened = self._execute_named_tool(
            "handoff_commit",
            {"stage": actor, "goal": task["goal"], "source": actor, "target": actor},
            task["task_id"],
        )
        if not opened.get("ok"):
            return self._fail(task, "chain_tool_failed", "交接链起点没有工具执行记录")
        task["prior_results"].append({"employee": actor, "result": opened, "confirmed": True})
        self._touch(task)
        for source, target in zip(employees, employees[1:]):
            record = self._perform_handoff(
                task,
                source=source,
                target=target,
                permissions=list(payload.get("permissions") or ["continue"]),
                new_conditions={},
                idempotency_key=f"{task['task_id']}:chain:{source}:{target}",
                effect={
                    "stage": target,
                    "saw_prior": _clone(task["prior_results"]),
                    "goal": task["goal"],
                },
                policy="retry",
            )
            if record["status"] != _TERMINAL_OK:
                self._write()
                return self._envelope(task, business=False, extra={"handoff": record})
        task["result_payload"] = _clone(task["prior_results"][-1])
        task["holder_employee"] = employees[-1]
        task["status"] = _TERMINAL_OK
        task["error_code"] = ""
        task["error_message"] = ""
        self._touch(task)
        self._event("chain_completed", task)
        self._write()
        return self._envelope(task)

    def _metrics_op(
        self, actor: str, text: str, payload: dict[str, Any], **scope: str
    ) -> dict[str, Any]:
        pollution = self.pollution_findings()
        duplicates = self.duplicate_side_effects()
        return {
            "success": True,
            "business_success": not pollution and not duplicates,
            "source": SOURCE,
            "pollution": len(pollution),
            "pollution_findings": pollution,
            "duplicate_side_effects": len(duplicates),
            "duplicate_keys": duplicates,
            "orphan_count": len(self.orphans()),
            "evidence": _blank_evidence(),
        }

    def _perform_handoff(
        self,
        task: dict[str, Any],
        *,
        source: str,
        target: str,
        permissions: list[str],
        new_conditions: dict[str, Any],
        idempotency_key: str,
        effect: dict[str, Any],
        policy: str,
        retry_of: str = "",
        inherited: dict[str, Any] | None = None,
        target_tenant_id: str = "",
        delegated_tool: str = "",
        delegated_action: str = "",
        delegated_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if new_conditions:
            task["conditions"] = _merge_conditions(task["conditions"], new_conditions)
        if target not in task["authorized_employees"]:
            task["authorized_employees"].append(target)
        task["grants"][target] = list(permissions)
        task["holder_employee"] = target
        flags = self._flags(target)
        record = {
            "handoff_id": _new_id("handoff"),
            "task_id": task["task_id"],
            "source_employee": source,
            "target_employee": target,
            "permissions": list(permissions),
            "requirements": list(task["requirements"]),
            "goal": task["goal"],
            "idempotency_key": idempotency_key,
            "policy": policy,
            "retry_of": retry_of,
            "retry_count": int(task["retry_count"]),
            "effect": effect,
            "status": "pending",
            "error_code": "",
            "error_message": "",
            "result_payload": {},
            "duplicate_prevented": False,
            "context_version": task["context_version"],
            "context_snapshot": inherited if inherited is not None else {},
            "created_at": _now(),
        }
        self._touch(task)
        record["context_snapshot"] = (
            inherited if inherited is not None else _clone(task["context_snapshot"])
        )
        record["context_version"] = task["context_version"]
        failure = _availability_failure(flags)
        if failure:
            code, message = failure
            record["status"] = "failed"
            record["error_code"] = code
            record["error_message"] = message
            task["status"] = "failed"
            task["error_code"] = code
            task["error_message"] = message
            self._recovery(task, record["handoff_id"], code, message)
        elif idempotency_key in self.state["side_effects"]:
            record["status"] = _TERMINAL_OK
            record["duplicate_prevented"] = True
            record["result_payload"] = _clone(self.state["side_effects"][idempotency_key]["result"])
        else:
            result = self._execute_named_tool(
                "handoff_commit",
                {
                    "effect": effect,
                    "goal": task["goal"],
                    "source": source,
                    "target": target,
                    "idempotency_key": idempotency_key,
                    "task_id": task["task_id"],
                    "tenant_id": task["tenant_id"],
                    "user_id": task["user_id"],
                    "permissions": list(permissions),
                    "target_tenant_id": target_tenant_id,
                    "delegated_tool": delegated_tool,
                    "delegated_action": delegated_action,
                    "delegated_params": dict(delegated_params or {}),
                },
                task["task_id"],
                runtime_context={
                    "tenant_id": task["tenant_id"],
                    "user_id": task["user_id"],
                    "employee_id": source,
                    "task_id": task["task_id"],
                },
            )
            call_id = _new_id("tool")
            call_status = "success" if result.get("ok") else "failed"
            self.state["tool_calls"][call_id] = {
                "tool_call_id": call_id,
                "task_id": task["task_id"],
                "step_id": f"handoff:{target}",
                "idempotency_key": idempotency_key,
                "status": call_status,
                "result_payload": result,
                "error_code": "" if result.get("ok") else str(result.get("error_code") or ""),
                "error_message": "" if result.get("ok") else str(result.get("error_message") or ""),
                "resubmitted": False,
                "submitted": True,
                "submit_pid": os.getpid(),
            }
            if not result.get("ok"):
                record["status"] = "failed"
                record["error_code"] = str(result.get("error_code") or "handoff_tool_failed")
                record["error_message"] = str(result.get("error_message") or "交接工具没有成功记录")
                task["status"] = "failed"
                task["error_code"] = record["error_code"]
                task["error_message"] = record["error_message"]
                self._recovery(
                    task, record["handoff_id"], record["error_code"], record["error_message"]
                )
            else:
                self.state["side_effects"][idempotency_key] = {
                    "invocations": 1,
                    "result": result,
                    "task_id": task["task_id"],
                }
                record["status"] = _TERMINAL_OK
                record["result_payload"] = result
                self._remember_handoff_child(task, target, result)
                task["prior_results"].append(
                    {
                        "employee": target,
                        "result": result,
                        "handoff_id": record["handoff_id"],
                        "confirmed": True,
                    }
                )
                open_steps = [step for step in task["steps"] if step["status"] != "success"]
                if not open_steps:
                    task["status"] = _TERMINAL_OK
                    task["error_code"] = ""
                    task["error_message"] = ""
                elif task["status"] == "failed":
                    task["status"] = "running"
                    task["error_code"] = ""
                    task["error_message"] = ""
        self.state["handoffs"][record["handoff_id"]] = record
        task["handoff_ids"].append(record["handoff_id"])
        self._touch(task)
        return record

    def _remember_handoff_child(
        self, task: dict[str, Any], target: str, result: dict[str, Any]
    ) -> None:
        child_id = str(result.get("child_task_id") or "")
        if not child_id or child_id == task["task_id"] or child_id in self.state["tasks"]:
            return
        child = _clone(task)
        child["task_id"] = child_id
        child["parent_task_id"] = task["task_id"]
        child["root_task_id"] = task.get("root_task_id") or task["task_id"]
        child["child_task_ids"] = []
        child["conversation_id"] = f"{task['conversation_id']}:{child_id}"
        child["owner_employee"] = target
        child["holder_employee"] = target
        child["authorized_employees"] = [target, task["owner_employee"]]
        child["grants"] = {target: list(result.get("delegated_tools") or [])}
        child["steps"] = []
        child["status"] = _TERMINAL_OK
        child["error_code"] = ""
        child["error_message"] = ""
        child["handoff_ids"] = []
        child["prior_results"] = []
        child["messages"] = []
        child["business_data"] = {}
        child["result_payload"] = {
            "parent_task_id": task["task_id"],
            "child_task_id": child_id,
            "parent_run_id": result.get("parent_run_id"),
            "child_run_id": result.get("child_run_id"),
            "execution_status": result.get("execution_status"),
            "result": result.get("result"),
        }
        self._touch(child)
        self.state["tasks"][child_id] = child
        if child_id not in task["child_task_ids"]:
            task["child_task_ids"].append(child_id)

    def _execute_pending(
        self, task: dict[str, Any], actor: str, *, limit: int | None, only: set[str] | None = None
    ) -> None:
        ran = 0
        for step in task["steps"]:
            if only is not None and step["step_id"] not in only:
                continue
            if step["status"] == "blocked" and _deps_ok(task, step):
                step["status"] = "pending"
                step["error_code"] = ""
            if step["status"] != "pending":
                continue
            if limit is not None and ran >= limit:
                break
            self._invoke(task, step, actor)
            ran += 1
        self._rollup_steps(task)

    def _invoke(self, task: dict[str, Any], step: dict[str, Any], actor: str) -> None:
        grant = list(task["grants"].get(actor) or [])
        if "*" not in grant and step["tool"] not in grant:
            step["status"] = "failed"
            step["error_code"] = "unauthorized_tool"
            step["error_message"] = "员工无权调用该工具"
            return
        if step["status"] == "success" or step["idempotency_key"] in self.state["side_effects"]:
            if step["idempotency_key"] in self.state["side_effects"]:
                step["status"] = "success"
                step["result_payload"] = _clone(
                    self.state["side_effects"][step["idempotency_key"]]["result"]
                )
                step["skipped_duplicate"] = True
            return
        if step["status"] == "running":
            return
        if not _deps_ok(task, step):
            step["status"] = "blocked"
            step["error_code"] = "dependency_not_met"
            step["error_message"] = "前置步骤未成功，依赖步骤不继续"
            return
        call_id = _new_id("tool")
        call = {
            "tool_call_id": call_id,
            "task_id": task["task_id"],
            "step_id": step["step_id"],
            "idempotency_key": step["idempotency_key"],
            "status": "running",
            "result_payload": {},
            "error_code": "",
            "error_message": "",
            "resubmitted": False,
            "submitted": True,
            "submit_pid": os.getpid(),
        }
        step["tool_call_id"] = call_id
        step["status"] = "running"
        self.state["tool_calls"][call_id] = call
        self._write()
        result = self._execute_named_tool(step["tool"], _clone(step["params"]), task["task_id"])
        if not isinstance(result, dict) or result.get("ok") is False:
            call["status"] = "failed"
            call["error_code"] = str((result or {}).get("error_code") or "tool_failed")
            call["error_message"] = str((result or {}).get("error_message") or "工具失败")
            step["status"] = "failed"
            step["error_code"] = call["error_code"]
            step["error_message"] = call["error_message"]
            step["result_payload"] = result if isinstance(result, dict) else {}
            call["result_payload"] = step["result_payload"]
            return
        self.state["side_effects"][step["idempotency_key"]] = {
            "invocations": 1,
            "result": result,
            "task_id": task["task_id"],
        }
        call["status"] = "success"
        call["result_payload"] = result
        step["status"] = "success"
        step["error_code"] = ""
        step["error_message"] = ""
        step["result_payload"] = result

    def _apply_fact(self, task: dict[str, Any], fact: dict[str, Any]) -> None:
        confidence = str(fact.get("confidence") or "")
        kind = str(fact.get("kind") or "")
        if confidence != "confirmed":
            if fact:
                task["speculative"].append(fact)
            return
        if kind == "tool_result":
            call = self.state["tool_calls"].get(str(fact.get("tool_call_id") or ""))
            if call is None or call["status"] != "success" or call["task_id"] != task["task_id"]:
                task["rejected_claims"].append(fact)
                return
        key = str(fact.get("key") or kind or "")
        if not key:
            task["rejected_claims"].append(fact)
            return
        value = fact.get("value")
        current = task["confirmed_facts"]
        if key in current and current[key] != value:
            current.setdefault("_preserved", []).append(
                {"key": key, "kept": current[key], "added": value}
            )
            return
        current[key] = value

    def _aggregate_parent(self, parent: dict[str, Any]) -> None:
        children = [
            self.state["tasks"][cid]
            for cid in parent["child_task_ids"]
            if cid in self.state["tasks"]
        ]
        aggregate = {
            "success": sum(child["status"] == _TERMINAL_OK for child in children),
            "failure": sum(child["status"] == "failed" for child in children),
            "incomplete": sum(
                child["status"] not in {_TERMINAL_OK, "failed"} for child in children
            ),
        }
        parent["aggregate"] = aggregate
        if parent["completion_condition"] != "all_children_success":
            return
        if aggregate["failure"]:
            parent["status"] = "failed"
            parent["error_code"] = "child_failed"
            parent["error_message"] = "子任务失败，父任务不能记为成功"
        elif aggregate["incomplete"] or aggregate["success"] != len(children):
            parent["status"] = "running"
        elif children:
            parent["status"] = _TERMINAL_OK
            parent["error_code"] = ""
            parent["error_message"] = ""
            parent["result_payload"] = {
                "children": [
                    {
                        "task_id": child["task_id"],
                        "status": child["status"],
                        "token": child["result_payload"].get("token"),
                    }
                    for child in children
                ]
            }

    def _rollup_steps(self, task: dict[str, Any]) -> None:
        if not task["steps"] or task["completion_condition"] == "all_children_success":
            task["completed_steps"] = [
                step["step_id"] for step in task["steps"] if step["status"] == "success"
            ]
            task["remaining_steps"] = [
                step["step_id"] for step in task["steps"] if step["status"] != "success"
            ]
            return
        statuses = {step["status"] for step in task["steps"]}
        if statuses == {"success"}:
            task["status"] = _TERMINAL_OK
            task["error_code"] = ""
            task["error_message"] = ""
        elif "failed" in statuses or "blocked" in statuses:
            task["status"] = "partial_success" if "success" in statuses else "failed"
            if task["status"] == "failed":
                task["error_code"] = task.get("error_code") or "step_failed"
        elif statuses <= {"pending", "running", "success", "recovering"}:
            if task["status"] not in {"paused", "recovering"}:
                task["status"] = "running"
        task["completed_steps"] = [
            step["step_id"] for step in task["steps"] if step["status"] == "success"
        ]
        task["remaining_steps"] = [
            step["step_id"] for step in task["steps"] if step["status"] != "success"
        ]

    def _authorized(
        self, payload: dict[str, Any], actor: str, scope: dict[str, str], *, write: bool
    ) -> dict[str, Any]:
        found = self.state["tasks"].get(str(payload.get("task_id") or ""))
        if not isinstance(found, dict):
            return self._fail(None, "task_not_found", "任务不存在")
        if self._allows(found, actor, scope):
            return found
        return self._fail(found, "unauthorized", "无权读取其他员工或用户的任务上下文", redact=True)

    def _allows(self, task: dict[str, Any], actor: str, scope: dict[str, str]) -> bool:
        if task["tenant_id"] != scope["tenant"] or task["user_id"] != scope["user"]:
            return False
        return actor == task["owner_employee"] or actor in task["authorized_employees"]

    def _flags(self, employee_id: str) -> dict[str, Any]:
        path = self.workspace / "employees" / f"{employee_id}.json"
        flags = {key: key == "available" for key in _EMPLOYEE_FLAGS}
        if not path.is_file():
            return flags
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return flags
        if not isinstance(loaded, dict):
            return flags
        for key in _EMPLOYEE_FLAGS:
            if key in loaded:
                flags[key] = bool(loaded[key])
        return flags

    def _conversation(self, key: str) -> dict[str, Any] | None:
        raw = self.state["conversations"].get(key)
        if isinstance(raw, dict) and raw.get("task_id"):
            return dict(raw)
        if isinstance(raw, str) and raw:
            return {"task_id": raw, "active": False}
        return None

    def _exclusive(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        handle = lock_path.open("a+")

        class _Guard:
            def __enter__(self_inner):
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
                return False

        return _Guard()

    def _execute_named_tool(
        self,
        name: str,
        params: dict[str, Any],
        task_id: str,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        script = self.workspace / "tools" / f"{name}.py"
        if script.is_file():
            try:
                proc = subprocess.run(
                    [sys.executable, str(script)],
                    input=json.dumps(
                        {"params": params, "task_id": task_id, "workspace": str(self.workspace)},
                        ensure_ascii=False,
                    ),
                    capture_output=True,
                    text=True,
                    timeout=8,
                    cwd=str(self.workspace),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return {"ok": False, "error_code": "tool_timeout", "error_message": "工具超时"}
            if proc.returncode != 0:
                return {
                    "ok": False,
                    "error_code": "tool_crashed",
                    "error_message": (proc.stderr or proc.stdout or "工具进程失败")[-400:],
                }
            try:
                data = json.loads(proc.stdout or "")
            except json.JSONDecodeError:
                return {
                    "ok": False,
                    "error_code": "tool_output",
                    "error_message": "工具没有返回 JSON",
                }
            if not isinstance(data, dict):
                return {
                    "ok": False,
                    "error_code": "tool_output",
                    "error_message": "工具结果不是对象",
                }
            return data
        try:
            from app.application.tools.workflow import execute_workflow_tool

            raw = execute_workflow_tool(
                name, params, str(self.workspace), runtime_context=runtime_context
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return {"ok": False, "error_code": "tool_missing", "error_message": str(exc)}
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            return {"ok": False, "error_code": "tool_missing", "error_message": str(raw)[:300]}
        if not isinstance(data, dict):
            return {"ok": False, "error_code": "tool_missing", "error_message": f"没有工具 {name}"}
        if data.get("ok") is False or data.get("success") is False or data.get("error"):
            return {
                "ok": False,
                "error_code": str(data.get("error_code") or data.get("error") or "tool_failed"),
                "error_message": str(
                    data.get("error_message") or data.get("message") or data.get("error") or ""
                ),
            }
        data["ok"] = True
        return data

    def _recovery(
        self, task: dict[str, Any], handoff_id: str, action: str, reason: str
    ) -> dict[str, Any]:
        record = {
            "recovery_id": _new_id("recovery"),
            "task_id": task["task_id"],
            "handoff_id": handoff_id,
            "action": action,
            "reason": reason,
            "retry_count": task["retry_count"],
            "status": task["status"],
            "timestamp": _now(),
        }
        self.state["recoveries"].append(record)
        return record

    def _touch(self, task: dict[str, Any]) -> None:
        task["context_version"] = int(task.get("context_version") or 0) + 1
        task["updated_at"] = _now()
        task["context_snapshot"] = {
            "goal": task["goal"],
            "conditions": _clone(task["conditions"]),
            "constraints": list(task["constraints"]),
            "business_data": _clone(task["business_data"]),
            "requirements": list(task["requirements"]),
            "completed_steps": list(task["completed_steps"]),
            "remaining_steps": list(task["remaining_steps"]),
            "confirmed_facts": _clone(task["confirmed_facts"]),
            "prior_results": _clone(task["prior_results"]),
            "context_version": task["context_version"],
        }
        task["completed_steps"] = [
            step["step_id"] for step in task["steps"] if step["status"] == "success"
        ]
        task["remaining_steps"] = [
            step["step_id"] for step in task["steps"] if step["status"] != "success"
        ]
        task["context_snapshot"]["completed_steps"] = list(task["completed_steps"])
        task["context_snapshot"]["remaining_steps"] = list(task["remaining_steps"])

    def _event(self, kind: str, task: dict[str, Any]) -> None:
        self.state["events"].append(
            {
                "kind": kind,
                "task_id": task["task_id"],
                "evidence": self._evidence(task),
                "timestamp": _now(),
            }
        )

    def _evidence(self, task: dict[str, Any] | None, *, redact: bool = False) -> dict[str, Any]:
        if task is None:
            return _blank_evidence()
        handoff = (
            self.state["handoffs"].get(task["handoff_ids"][-1]) if task.get("handoff_ids") else None
        )
        calls = [
            item for item in self.state["tool_calls"].values() if item["task_id"] == task["task_id"]
        ]
        call = calls[-1] if calls else None
        recoveries = [
            item for item in self.state["recoveries"] if item["task_id"] == task["task_id"]
        ]
        restarts = list(self.state["restarts"])
        snapshot = {} if redact else _clone(task.get("context_snapshot") or {})
        return {
            "E01_task_id": "" if redact else task["task_id"],
            "E02_parent_task_id": "" if redact else task.get("parent_task_id") or "",
            "E02_child_task_id": ""
            if redact or not task.get("child_task_ids")
            else task["child_task_ids"][-1],
            "E03_handoff_id": "" if handoff is None else handoff["handoff_id"],
            "E04_source_employee": "" if handoff is None else handoff["source_employee"],
            "E04_target_employee": "" if handoff is None else handoff["target_employee"],
            "E05_context_snapshot": snapshot,
            "E06_context_version": 0 if redact else task.get("context_version") or 0,
            "E07_conversation_id": "" if redact else task.get("conversation_id") or "",
            "E08_tool_call_id": "" if call is None else call["tool_call_id"],
            "E09_execution_status": task.get("status") or "",
            "E10_retry_count": task.get("retry_count") or 0,
            "E11_idempotency_key": (call or handoff or {}).get("idempotency_key") or "",
            "E12_result_payload": {}
            if redact
            else _clone(task.get("result_payload") or (call or {}).get("result_payload") or {}),
            "E13_error_code": task.get("error_code") or "",
            "E13_error_message": task.get("error_message") or "",
            "E14_recovery_record": recoveries[-1] if recoveries else {},
            "E15_event_timestamp": task.get("updated_at") or "",
            "E16_restart_recovery_record": restarts[-1] if restarts else {},
        }

    def _envelope(
        self,
        task: dict[str, Any],
        *,
        business: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        business_success = task["status"] == _TERMINAL_OK if business is None else business
        if task["status"] != _TERMINAL_OK:
            business_success = False
        body = {
            "success": True,
            "business_success": business_success,
            "source": SOURCE,
            "employee_id": task.get("holder_employee") or task.get("owner_employee"),
            "task_id": task["task_id"],
            "task": _public_task(task),
            "evidence": self._evidence(task),
            "error_code": task.get("error_code") or "",
            "error_message": task.get("error_message") or "",
            "events": [item for item in self.state["events"] if item["task_id"] == task["task_id"]],
        }
        if extra:
            body.update(extra)
        return body

    def _fail(
        self, task: dict[str, Any] | None, code: str, message: str, *, redact: bool = False
    ) -> dict[str, Any]:
        return {
            "success": False,
            "business_success": False,
            "source": SOURCE,
            "error_code": code,
            "error_message": message,
            "task_id": "" if task is None or redact else task.get("task_id") or "",
            "evidence": self._evidence(task, redact=redact),
        }

    def _fingerprint(self) -> str:
        view: list[Any] = []
        for task_id in sorted(self.state["tasks"]):
            task = self.state["tasks"][task_id]
            view.append(
                {
                    "task_id": task_id,
                    "parent": task["parent_task_id"],
                    "children": task["child_task_ids"],
                    "status": task["status"],
                    "goal": task["goal"],
                    "steps": [(step["step_id"], step["status"]) for step in task["steps"]],
                    "messages": len(task["messages"]),
                    "requirements": task["requirements"],
                }
            )
        view.append(
            sorted(
                (item["tool_call_id"], item["status"]) for item in self.state["tool_calls"].values()
            )
        )
        view.append(sorted(self.state["handoffs"]))
        encoded = json.dumps(view, ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.state, ensure_ascii=False, default=str), encoding="utf-8"
        )
        temporary.replace(self.path)

    def _read(self) -> None:
        if not self.path.is_file():
            self.state = _empty_state()
            return
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        state = _empty_state()
        state.update(loaded if isinstance(loaded, dict) else {})
        self.state = state


def _step_from(task_id: str, raw: dict[str, Any], index: int) -> dict[str, Any]:
    step_id = str(raw.get("step_id") or f"s{index + 1}")
    return {
        "step_id": step_id,
        "name": str(raw.get("name") or step_id),
        "tool": str(raw.get("tool") or "note"),
        "params": dict(raw.get("params") or {}),
        "depends_on": list(raw.get("depends_on") or []),
        "idempotency_key": str(raw.get("idempotency_key") or f"{task_id}:{step_id}"),
        "idempotent": bool(raw.get("idempotent") or False),
        "status": "pending",
        "error_code": "",
        "error_message": "",
        "result_payload": {},
        "tool_call_id": "",
        "skipped_duplicate": False,
    }


def _find_step(task: dict[str, Any] | None, step_id: str) -> dict[str, Any] | None:
    if task is None:
        return None
    for step in task["steps"]:
        if isinstance(step, dict) and step.get("step_id") == step_id:
            return step
    return None


def _deps_ok(task: dict[str, Any], step: dict[str, Any]) -> bool:
    by_id = {item["step_id"]: item for item in task["steps"]}
    return all(by_id[dep]["status"] == "success" for dep in step["depends_on"] if dep in by_id)


def _merge_conditions(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = dict(old)
    for key, value in new.items():
        if key not in merged or merged[key] == value:
            merged[key] = value
            continue
        merged[key] = {"kept": merged[key], "added": value, "merge": "preserve_both"}
    return merged


def _availability_failure(flags: dict[str, Any]) -> tuple[str, str] | None:
    if not flags.get("available", True):
        return "employee_unavailable", "目标员工不可用"
    if flags.get("timeout"):
        return "employee_timeout", "目标员工超时"
    if flags.get("crash"):
        return "employee_crashed", "目标员工执行中崩溃"
    if flags.get("unrecoverable"):
        return "employee_unrecoverable", "目标员工不可恢复"
    return None


def _conv_key(task: dict[str, Any]) -> str:
    return f"{task['tenant_id']}:{task['user_id']}:{task['conversation_id']}"


def _summary(task: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "step_id": step["step_id"],
            "status": step["status"],
            "tool_call_id": step.get("tool_call_id") or "",
        }
        for step in task["steps"]
    ]


def _presented_handoff(record: dict[str, Any]) -> dict[str, Any]:
    """Show the shared employee status. The ledger keeps its own completed word."""
    shown = _clone(record)
    from app.domain.task_lifecycle.adapters import LegacyTransitionError, canonicalize

    try:
        shown["status"] = canonicalize("employee", str(record.get("status") or ""))
    except LegacyTransitionError:
        return shown
    return shown


def _public_task(task: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "task_id",
        "parent_task_id",
        "child_task_ids",
        "root_task_id",
        "conversation_id",
        "tenant_id",
        "user_id",
        "owner_employee",
        "holder_employee",
        "goal",
        "conditions",
        "constraints",
        "business_data",
        "requirements",
        "status",
        "error_code",
        "error_message",
        "retry_count",
        "context_version",
        "context_snapshot",
        "completed_steps",
        "remaining_steps",
        "confirmed_facts",
        "speculative",
        "rejected_claims",
        "prior_results",
        "result_payload",
        "aggregate",
        "completion_condition",
        "handoff_ids",
        "steps",
        "compression_strategy",
        "compression_count",
        "compressed_summary",
    )
    return {key: _clone(task.get(key)) for key in keys}


def _blank_evidence() -> dict[str, Any]:
    return {
        "E01_task_id": "",
        "E02_parent_task_id": "",
        "E02_child_task_id": "",
        "E03_handoff_id": "",
        "E04_source_employee": "",
        "E04_target_employee": "",
        "E05_context_snapshot": {},
        "E06_context_version": 0,
        "E07_conversation_id": "",
        "E08_tool_call_id": "",
        "E09_execution_status": "",
        "E10_retry_count": 0,
        "E11_idempotency_key": "",
        "E12_result_payload": {},
        "E13_error_code": "",
        "E13_error_message": "",
        "E14_recovery_record": {},
        "E15_event_timestamp": "",
        "E16_restart_recovery_record": {},
    }


def _is_task(value: dict[str, Any]) -> bool:
    return "task_id" in value and value.get("source") != SOURCE


def _await(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict[str, Any] = {}

    def _runner() -> None:
        box["value"] = asyncio.run(coro)

    thread = threading.Thread(target=_runner)
    thread.start()
    thread.join()
    return box["value"]


def ledger_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root) / ".xcmax" / "employee_task_ledger.json"


def load_employee_task_ledger(workspace_root: str | Path) -> dict[str, Any]:
    path = ledger_path(workspace_root)
    if not path.is_file():
        return _empty_state()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    state = _empty_state()
    state.update(loaded if isinstance(loaded, dict) else {})
    return state


def audit_employee_task_ledger(workspace_root: str | Path) -> dict[str, Any]:
    """Read the durable ledger from disk. Does not trust an in-memory object."""
    runtime = TaskContinuityRuntime(ledger_path(workspace_root), workspace=workspace_root)
    runtime._read()
    pollution = runtime.pollution_findings()
    duplicates = runtime.duplicate_side_effects()
    return {
        "pollution": len(pollution),
        "duplicate_side_effects": len(duplicates),
        "orphan_count": len(runtime.orphans()),
    }


def _path_lock(path: Path) -> threading.RLock:
    key = os.path.abspath(path)
    with _LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def maybe_continue_employee_task(
    employee_id: str,
    task: str,
    payload: dict[str, Any] | None,
    *,
    user_id: Any = "",
    session_id: str | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Entry used by EmployeeAgent.run. Ordinary chat returns None."""
    body = dict(payload or {})
    action = str(body.get("continuity_action") or "").strip()
    text = str(task or "").strip()
    if not action and "steps" not in body and text != CONTINUE_TEXT:
        return None
    workspace = workspace_root or body.get("workspace_root")
    if not workspace:
        return {
            "success": False,
            "business_success": False,
            "source": SOURCE,
            "error_code": "continuity_workspace_missing",
            "error_message": "任务连续性需要工作区以写入持久账本",
            "evidence": _blank_evidence(),
        }
    if not action:
        action = "start" if "steps" in body else "resume"
    if action not in _ACTIONS:
        return {
            "success": False,
            "business_success": False,
            "source": SOURCE,
            "error_code": "unknown_op",
            "error_message": f"不支持的连续性操作: {action}",
            "evidence": _blank_evidence(),
        }
    body["op"] = action
    runtime = TaskContinuityRuntime(ledger_path(workspace), workspace=workspace)
    return runtime.dispatch(employee_id, text or task, body, user_id=user_id, session_id=session_id)
