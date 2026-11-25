"""Immutable original goals, host scope and independent result evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.task_lifecycle.results import (
    execution_result_error,
    execution_result_outcome_unknown,
)


class AgentRuntimeContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


GOAL_PROTOCOL = "xcmax.agent-goal.v2"
_SCOPE_FIELDS = (
    "user_id",
    "actor_id",
    "tenant_id",
    "mod_id",
    "active_mod_id",
    "employee_id",
    "session_id",
    "conversation_id",
    "workspace_id",
    "parent_run_id",
    "parent_task_id",
    "root_run_id",
    "employee_tool_allowlist",
    "_employee_gate_contract",
)


def goal_scope(run: Any) -> dict[str, Any]:
    """Bind host identity and restrictions without copying authentication secrets."""
    context = run.metadata.get("runtime_context") or {}
    return {
        "run_id": run.run_id,
        "owner_id": run.user_id,
        "allowed_actions": copy.deepcopy(run.metadata.get("runtime_allowed_actions")),
        "entity_binding_digest": canonical_digest(context.get("enterprise_cognition")),
        **{key: copy.deepcopy(context.get(key)) for key in _SCOPE_FIELDS},
        "constraints": copy.deepcopy(context.get("_runtime_goal_constraints") or {}),
    }


def build_goal_contract(
    run: Any,
    *,
    history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
    context_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist the user's request; this contract neither plans nor authorizes actions."""
    if not isinstance(run.message, str) or not run.message.strip():
        raise AgentRuntimeContractError("invalid_goal", "原始任务不能为空")
    historical = history if history is not None else run.metadata.get("_codex_history")
    request = {
        "text": run.message,
        "input_data": copy.deepcopy(run.metadata.get("_codex_input_data")),
        "attachments": copy.deepcopy(attachments or []),
        "context_evidence": copy.deepcopy(context_evidence or []),
        "history": [
            {"role": row["role"], "content": row["content"]}
            for row in historical or []
            if isinstance(row, dict)
            and row.get("role") in {"user", "assistant", "tool"}
            and isinstance(row.get("content"), str)
        ],
    }
    contract = {"protocol": GOAL_PROTOCOL, "scope": goal_scope(run), "request": request}
    try:
        return {**contract, "digest": canonical_digest(contract)}
    except (TypeError, ValueError) as exc:
        raise AgentRuntimeContractError("invalid_goal", "原始任务数据不能持久化") from exc


def validate_goal_contract(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"protocol", "scope", "request", "digest"}
        or value.get("protocol") != GOAL_PROTOCOL
        or not isinstance(value.get("scope"), dict)
        or not isinstance(value.get("request"), dict)
        or not isinstance(value["request"].get("text"), str)
        or not value["request"]["text"].strip()
        or value.get("digest")
        != canonical_digest({key: item for key, item in value.items() if key != "digest"})
    ):
        raise AgentRuntimeContractError("goal_changed", "原始目标合同无效或已改变")
    return copy.deepcopy(value)


def validate_runtime_goal(run: Any) -> str:
    """Recheck immutable request and scope for each grant, tool and final decision."""
    contract = validate_goal_contract(run.metadata.get("runtime_goal_contract"))
    if contract != build_goal_contract(
        run,
        attachments=contract["request"].get("attachments"),
        context_evidence=contract["request"].get("context_evidence"),
    ):
        raise AgentRuntimeContractError("goal_changed", "原任务、历史或授权范围已改变")
    return str(contract["digest"])


def goal_answers(run: Any) -> list[dict[str, Any]]:
    """Only host-persisted answers extend the original request, never model history."""
    return [
        {
            "source_id": f"answer:{event.event_id}",
            "question": event.data.get("question"),
            "answer": event.data.get("answer"),
            "input_data": copy.deepcopy(event.data.get("input_data")),
        }
        for event in run.events
        if event.event_type == "runtime.input_answered"
    ]


class GoalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    goal_id: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=4000)
    kind: Literal["reply", "read", "write", "constraint"]
    status: Literal["satisfied", "unmet", "not_applicable"]
    evidence_ids: list[str] = Field(max_length=256)
    reason: str = Field(min_length=1, max_length=4000)


class GoalReview(BaseModel):
    """A non-executing semantic assessment, constrained by host receipt validation."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    goals: list[GoalAssessment] = Field(min_length=1, max_length=64)
    violations: list[str] = Field(max_length=64)
    uncovered_sources: list[str] = Field(max_length=64)
    feedback: str = Field(max_length=12000)


def goal_evidence_snapshot(
    contract: dict[str, Any],
    rows: list[dict[str, Any]],
    output: str,
    answers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deduplicate aliases while binding complete receipts, including failed attempts."""
    contract = validate_goal_contract(contract)
    evidence: dict[str, dict[str, Any]] = {}
    tasks: dict[str, str] = {}
    effects: dict[str, str] = {}
    conflicts = []
    for row in rows:
        child = str(row.get("child_run_id") or "")
        task = str(row.get("child_task_id") or "")
        operation = {key: copy.deepcopy(row.get(key)) for key in ("tool_id", "action", "params")}
        fingerprint = canonical_digest(operation)
        raw_receipt = row.get("receipt")
        receipt = copy.deepcopy(raw_receipt) if isinstance(raw_receipt, dict) else {}
        item = {
            "evidence_id": child,
            "task_id": task,
            **operation,
            "fingerprint": fingerprint,
            "read_only": row.get("read_only") is True,
            "state": row.get("state"),
            "created_at": row.get("created_at"),
            "receipt": receipt,
        }
        if (
            not child
            or not task
            or not isinstance(raw_receipt, dict)
            or row.get("fingerprint") != fingerprint
            or receipt.get("run_id") != child
            or receipt.get("task_id") != task
            or tasks.get(task, child) != child
            or (child in evidence and evidence[child] != item)
            or (not item["read_only"] and fingerprint in effects and effects[fingerprint] != child)
        ):
            conflicts.append(child or task or "missing_child_identity")
        else:
            evidence[child], tasks[task] = item, child
            if not item["read_only"]:
                effects[fingerprint] = child
    snapshot = {
        "goal_digest": contract["digest"],
        "answers": copy.deepcopy(answers or []),
        "evidence": [evidence[key] for key in sorted(evidence)],
        "conflicts": sorted(set(conflicts)),
        "response_digest": canonical_digest(output),
    }
    return {**snapshot, "digest": canonical_digest(snapshot)}


def validate_goal_review(
    raw: Any, contract: dict[str, Any], snapshot: dict[str, Any], output: str
) -> tuple[dict[str, Any], list[str]]:
    """A model can associate facts with goals; it cannot mint execution evidence."""
    review = GoalReview.model_validate(raw)
    sources = {"request": contract["request"]["text"]}
    sources.update(
        (row["source_id"], row["answer"])
        for row in snapshot["answers"]
        if isinstance(row.get("source_id"), str) and isinstance(row.get("answer"), str)
    )
    constraints = contract["scope"].get("constraints") or {}
    if isinstance(constraints.get("objective"), str):
        sources["objective"] = constraints["objective"]
    evidence = {row["evidence_id"]: row for row in snapshot["evidence"]}
    verified = {
        key: row
        for key, row in evidence.items()
        if row["state"] == "completed"
        and row["receipt"].get("status") == "completed"
        and row["receipt"].get("success") is True
        and row["receipt"].get("verified") is True
        and not execution_result_outcome_unknown(row["receipt"], include_execution=True)
        and not execution_result_error(row["receipt"])
    }
    errors = list(snapshot["conflicts"])
    seen: set[str] = set()
    used_writes: set[str] = set()
    assigned: dict[str, str] = {}
    for goal in review.goals:
        if goal.goal_id in seen or goal.source not in sources.get(goal.source_id, ""):
            errors.append(f"目标 {goal.goal_id} 缺少唯一标识或原始请求证据")
        seen.add(goal.goal_id)
        selected = set(goal.evidence_ids)
        if len(selected) != len(goal.evidence_ids) or selected - evidence.keys() - {"response"}:
            errors.append(f"目标 {goal.goal_id} 引用了不存在的回执")
        if goal.status == "unmet":
            continue
        if goal.kind == "reply":
            if goal.status != "satisfied" or selected != {"response"} or not output.strip():
                errors.append(f"回复目标 {goal.goal_id} 没有完整正文")
        elif goal.kind in {"read", "write"}:
            if not selected or not selected <= verified.keys():
                errors.append(f"业务目标 {goal.goal_id} 缺少独立核验的原任务回执")
            if goal.status == "not_applicable":
                if not selected or any(
                    not verified.get(key, {}).get("read_only") for key in selected
                ):
                    errors.append(f"条件目标 {goal.goal_id} 未提供只读前提证据")
            elif goal.kind == "write":
                writes = {
                    key for key in selected if not verified.get(key, {}).get("read_only", True)
                }
                if not writes:
                    errors.append(f"写入目标 {goal.goal_id} 不能用只读结果冒充完成")
                used_writes.update(writes)
                for key in writes:
                    if key in assigned:
                        errors.append(f"目标 {goal.goal_id} 重用了 {assigned[key]} 的同一写入回执")
                    assigned[key] = goal.goal_id
            elif any(not verified.get(key, {}).get("read_only", True) for key in selected):
                errors.append(f"只读目标 {goal.goal_id} 包含额外写入")
        elif goal.status != "satisfied" or selected - verified.keys():
            errors.append(f"约束 {goal.goal_id} 的核验无效")
    successful_writes = {
        key
        for key, row in evidence.items()
        if not row["read_only"] and row["receipt"].get("success") is True
    }
    if successful_writes - used_writes:
        errors.append("存在未被原始目标覆盖的写入回执")
    if constraints.get("objective") and not any(
        goal.source_id == "objective" for goal in review.goals
    ):
        errors.append("未核对宿主绑定的经营目标")
    return review.model_dump(), errors


def goal_report_coverage(
    contract: Any,
    rows: list[dict[str, Any]],
    output: str,
    answers: list[dict[str, Any]] | None,
    report: Any,
) -> dict[str, Any]:
    """Re-evaluate a persisted report against the exact current host evidence."""
    result = {"completed": False, "required": 0, "verified": 0, "mode": "business", "errors": []}
    try:
        snapshot = goal_evidence_snapshot(contract, rows, output, answers)
        if (
            not isinstance(report, dict)
            or report.get("protocol") != GOAL_PROTOCOL
            or report.get("goal_digest") != contract["digest"]
            or report.get("evidence_digest") != snapshot["digest"]
            or report.get("response_digest") != canonical_digest(output)
            or report.get("report_digest")
            != canonical_digest(
                {key: value for key, value in report.items() if key != "report_digest"}
            )
        ):
            result["errors"] = ["目标、补答、执行回执或回复已改变，需要重新核验"]
            return result
        review, errors = validate_goal_review(report.get("review"), contract, snapshot, output)
        goals = review["goals"]
        mode = "business" if any(g["kind"] in {"read", "write"} for g in goals) else "reply"
        complete = not (errors or review["violations"] or review["uncovered_sources"])
        return {
            "completed": complete
            and report.get("status") == "verified"
            and report.get("accepted") is True
            and all(g["status"] != "unmet" for g in goals),
            "required": len(goals),
            "verified": sum(g["status"] != "unmet" for g in goals),
            "mode": mode,
            "errors": errors + review["violations"] + review["uncovered_sources"],
        }
    except (TypeError, ValueError, KeyError, ValidationError):
        result["errors"] = ["原始目标核验报告无效"]
        return result
