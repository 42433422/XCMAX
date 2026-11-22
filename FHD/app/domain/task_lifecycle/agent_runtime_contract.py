"""Frozen operation identity and goal coverage for an agent-owned task."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


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


def validate_expected_operations(
    value: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Freeze all required independent operations, never infer a goal from tool calls.

    Ordering and conditional branches belong to an existing, frozen workflow
    operation. Two identical effects cannot represent separate obligations: the
    server deliberately deduplicates those effects across model call IDs.
    """
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or not value
        or len(value) > 64
        or any(
            not isinstance(row, dict)
            or set(row) != {"tool_id", "action", "params"}
            or not isinstance(row["tool_id"], str)
            or not row["tool_id"].strip()
            or not isinstance(row["action"], str)
            or not row["action"].strip()
            or not isinstance(row["params"], dict)
            for row in value
        )
    ):
        raise AgentRuntimeContractError("invalid_expected_operations", "冻结业务目标格式无效")
    try:
        fingerprints = {canonical_digest(operation) for operation in value}
    except (TypeError, ValueError) as exc:
        raise AgentRuntimeContractError(
            "invalid_expected_operations", "冻结业务目标必须是有效 JSON"
        ) from exc
    if len(fingerprints) != len(value):
        raise AgentRuntimeContractError(
            "invalid_expected_operations", "冻结业务目标不能重复声明同一操作"
        )
    return copy.deepcopy(value)


def frozen_workflow_operation(plan: dict[str, Any]) -> dict[str, Any]:
    """Reference a host-normalized graph; the model never supplies executable nodes."""
    return {
        "tool_id": "xcmax_workflow",
        "action": "execute",
        "params": {"plan_digest": canonical_digest(plan)},
    }


def frozen_goal_digest(expected: Any, plan: Any = None) -> str:
    """Bind the operation obligations and their optional host-owned workflow together."""
    expected = validate_expected_operations(expected)
    workflows = [row for row in expected or [] if row["tool_id"] == "xcmax_workflow"]
    if (plan is None and workflows) or (
        plan is not None
        and (not isinstance(plan, dict) or workflows != [frozen_workflow_operation(plan)])
    ):
        raise AgentRuntimeContractError(
            "invalid_frozen_plan", "冻结工作流必须与宿主保存的完整计划一致"
        )
    return canonical_digest({"expected_operations": expected, "frozen_plan": plan})


def frozen_goal_coverage(expected: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare host obligations against independently verified durable child identities.

    The receipt reader proves execution before this comparison. Exploratory safe
    reads are observations, not extra obligations or permission to write. Aliases
    of one durable child never cover two obligations, and contradictory aliases
    or repeated effect executions cannot silently overwrite earlier evidence.
    """
    try:
        expected = validate_expected_operations(expected)
    except AgentRuntimeContractError:
        expected = None
    required = {canonical_digest(operation) for operation in expected or []}
    children: dict[str, tuple[str, str, bool]] = {}
    tasks: dict[str, str] = {}
    operations: dict[str, dict[str, Any]] = {}
    conflicts: set[str] = set()
    for row in rows:
        child = str(row.get("child_run_id") or "")
        task = str(row.get("child_task_id") or "")
        fingerprint = canonical_digest(
            {key: row.get(key) for key in ("tool_id", "action", "params")}
        )
        identity = (task, fingerprint, row.get("read_only") is True)
        if (
            not child
            or not task
            or children.get(child, identity) != identity
            or tasks.get(task, child) != child
            or row.get("fingerprint", fingerprint) != fingerprint
        ):
            conflicts.add(child or task or "missing_child_identity")
            continue
        if child in children:
            continue
        children[child] = identity
        tasks[task] = child
        prior = operations.get(fingerprint)
        if prior and (prior.get("read_only") is not True or row.get("read_only") is not True):
            conflicts.add(child)
        operations[fingerprint] = row
    matched = required & operations.keys()
    unexpected = {
        fingerprint
        for fingerprint, row in operations.items()
        if fingerprint not in required and row.get("read_only") is not True
    }
    missing = required - matched
    return {
        "frozen": expected is not None,
        "required": len(required),
        "verified": len(matched),
        "operations": len(children),
        "missing": sorted(missing),
        "unexpected": sorted(unexpected),
        "conflicting_receipts": sorted(conflicts),
        "completed": bool(required) and not (missing or unexpected or conflicts),
    }
