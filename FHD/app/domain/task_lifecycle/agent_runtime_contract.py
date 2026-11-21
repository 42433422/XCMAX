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
    """Copy a host-frozen goal; malformed identities never become completion evidence."""
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
            or not row["tool_id"]
            or not isinstance(row["action"], str)
            or not row["action"]
            or not isinstance(row["params"], dict)
            for row in value
        )
    ):
        raise AgentRuntimeContractError("invalid_expected_operations", "冻结业务目标格式无效")
    canonical_digest(value)  # Reject non-JSON values and non-finite numbers.
    return copy.deepcopy(value)


def match_frozen_workflow(
    expected: Any,
    rows: list[dict[str, Any]],
) -> tuple[bool, int]:
    """Match one whole workflow, returning coverage and distinct operation count.

    The existing executor proves each receipt before this identity comparison.
    A bag of dynamic actions cannot establish a multi-goal task's ordering or
    conditional coverage. Repeated model call IDs for one child count only once.
    """
    unique = {row.get("child_run_id") or row.get("child_task_id"): row for row in rows}
    if isinstance(expected, list) and len(expected) == len(unique) == 1:
        operation = expected[0]
        actual = next(iter(unique.values()))
        if isinstance(operation, dict) and set(operation) == {"tool_id", "action", "params"}:
            matched = canonical_digest(operation) == canonical_digest(
                {key: actual.get(key) for key in ("tool_id", "action", "params")}
            )
            return matched, len(unique)
    return False, len(unique)
