"""Reserve final review inside the original run's time, call and cost limits.

These are earmarks in the existing SQL run/model ledger, not a second wallet or
runtime. Only a host-owned running verification task may spend them.
"""

from __future__ import annotations

import math
from typing import Any

JOB_KEY = "runtime_goal_verification_task"
JOB_HEADER = "x-xcagi-verification-job"
VERIFIER_VERSION = 2


def initialize_verification_budget(
    run: Any,
    metadata: dict[str, Any],
    *,
    context_window: int,
    max_model_calls: int,
    total_seconds: float,
) -> dict[str, Any]:
    """Freeze an envelope once; a retry cannot replenish it or raise total limits."""
    from app.infrastructure.billing.model_usage import estimate_llm_cost_units
    from app.infrastructure.xiaox.binding import XiaoxBindingError

    if "verification_budget" in metadata:
        return dict(metadata["verification_budget"])
    if (
        type(max_model_calls) is not int
        or max_model_calls < 2
        or type(context_window) is not int
        or context_window <= 0
        or not math.isfinite(total_seconds)
        or total_seconds <= 0
    ):
        raise XiaoxBindingError(
            "verification_budget_insufficient", "原任务预算不足以同时执行和独立核验"
        )
    remaining_calls = max_model_calls - len(metadata.get("model_requests") or {})
    if remaining_calls < 2:
        raise XiaoxBindingError(
            "verification_budget_insufficient", "原任务剩余调用次数不足以同时执行和独立核验"
        )
    calls = min(3, max(1, max_model_calls // 4), remaining_calls - 1)
    call_limit = min(3, remaining_calls - 1)
    per_call = estimate_llm_cost_units(total_tokens=context_window)
    if (cost_limit := run.metadata.get("ai_cost_budget_units")) is not None:
        remaining = max(
            0,
            int(cost_limit)
            - int(run.metadata.get("ai_cost_units_total") or 0)
            - int(run.metadata.get("reserved_cost_units") or 0),
        )
        # Keep at most a quarter for review, rounded up only to guarantee one
        # complete request. Both phases use the original admission cost ceiling.
        if remaining < 2 * per_call:
            raise XiaoxBindingError(
                "verification_budget_insufficient", "原任务剩余费用不足以同时执行和独立核验"
            )
        calls = min(calls, max(1, remaining // (4 * per_call)))
        call_limit = min(call_limit, remaining // per_call - 1)
    budget = {
        "version": 1,
        "model_calls": calls,
        "max_model_calls": call_limit,
        "per_call_cost_units": per_call,
        "cost_units": calls * per_call,
        "seconds": min(90.0, float(total_seconds) / 4),
    }
    metadata["verification_budget"] = budget
    return dict(budget)


def verification_reserve(metadata: dict[str, Any]) -> tuple[int, int]:
    """Protect minimum review slots within the frozen lifetime request ceiling."""
    budget = metadata.get("verification_budget") or {}
    if not budget:
        return 0, 0  # Existing in-flight runs have no retroactive budget promise.
    used = sum(
        row.get("purpose") == "verification"
        for row in (metadata.get("model_requests") or {}).values()
    )
    # Old frozen envelopes retain their original ceiling. Introducing slots
    # never grants a pre-upgrade task additional verification calls.
    ceiling = int(budget.get("max_model_calls", budget["model_calls"]))
    calls = min(max(0, int(budget["model_calls"])), max(0, ceiling - used))
    return calls, calls * int(budget["per_call_cost_units"])


def active_verification_job_id(run: Any, metadata: dict[str, Any]) -> str:
    """A client payload cannot grant access to the host-reserved review resources."""
    job = run.metadata.get(JOB_KEY) or {}
    identity = job.get("job_id")
    if (
        metadata.get("active_phase") == "verification"
        and job.get("state") == "running"
        and isinstance(identity, str)
        and 0 < len(identity) <= 160
        and type(job.get("generation")) is int
        and job["generation"] == metadata.get("generation")
    ):
        return identity
    return ""


def phase_deadline(run: Any, metadata: dict[str, Any]) -> float:
    """The execution phase must leave the reserved review time unused."""
    deadline = metadata.get("deadline_at")
    if not active_verification_job_id(run, metadata):
        deadline = metadata.get("execution_deadline_at", deadline)
    if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        return 0.0
    return float(deadline)
