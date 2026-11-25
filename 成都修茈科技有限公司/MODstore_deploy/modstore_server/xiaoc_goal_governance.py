"""Read-only goal governance for the existing XiaoC life and strategic ledgers.

Hierarchy anchors are projections, not a second goal/approval/task store.
Evidence-based priority is a scheduling heuristic, not estimated CNY benefit.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from modstore_server.xiaoc_life_policy import parse_time

ACTIVE_STATUSES = frozenset(
    {"proposed", "paused", "awaiting_approval", "approved", "active", "executing", "blocked"}
)
STAGE_SEVERITY = {
    "payment": 4,
    "installation": 3,
    "first_use": 3,
    "outcome": 4,
    "acceptance": 4,
    "reuse": 2,
    "sequence": 3,
    "enterprise_subject": 3,
}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def goal_path(identity_id: str, mission: str, goal_id: str, *, now: datetime) -> dict[str, Any]:
    """Freeze deterministic mission -> quarter -> candidate ancestry in the candidate."""
    if not identity_id or not goal_id or now.tzinfo is None:
        raise ValueError("goal identity and timezone-aware date required")
    quarter = (now.month - 1) // 3 + 1
    strategy = "mission:" + _hash([identity_id, mission])[:24]
    period = f"{now.year}-Q{quarter}"
    quarter_id = "quarter:" + _hash([strategy, period])[:24]
    return {
        "schema": "goal_path/v1",
        "levels": [
            {
                "id": strategy,
                "level": "strategy",
                "parent_id": None,
                "title": mission or "mission_not_set",
                "authority": "existing_management_mission_projection",
            },
            {
                "id": quarter_id,
                "level": "quarter",
                "parent_id": strategy,
                "period": period,
                "authority": "derived_quarter_anchor_not_separate_approved_target",
            },
            {
                "id": goal_id,
                "level": "operating",
                "parent_id": quarter_id,
                "authority": "sourced_review_candidate_not_approved_execution",
            },
        ],
    }


def observed_priority(stage: str, count: int, observed_at: str, *, now: datetime) -> dict[str, Any]:
    """Rank observed gaps, recency and review risk; never invent monetary benefit."""
    if stage not in STAGE_SEVERITY or type(count) is not int or count <= 0:
        raise ValueError("verified positive count required")
    measured = parse_time(observed_at)
    age = (now - measured).total_seconds()
    if now.tzinfo is None or age < 0 or age > 86400:
        raise ValueError("current evidence required")
    benefit_proxy = min(count, 999) * STAGE_SEVERITY[stage]
    urgency = max(0, 24 - math.ceil(age / 3600))
    unknown_cost_risk = 20
    score = max(0, min(100000, benefit_proxy * 10 + urgency - unknown_cost_risk))
    return {
        "basis": "observed_gap_severity_recency_minus_unknown_cost_risk/v1",
        "score": score,
        "benefit_proxy": {"metric": "verified_gap_count", "count": count, "severity": STAGE_SEVERITY[stage]},
        "urgency": {"evidence_age_hours_ceiling": math.ceil(age / 3600), "score": urgency},
        "risk": {"cost_not_measured": True, "penalty": unknown_cost_risk},
        "scope": "relative_review_order_not_financial_roi_or_execution_authority",
    }


def review_milestones(*, now: datetime, deadline: datetime) -> list[dict[str, Any]]:
    if now.tzinfo is None or deadline.tzinfo is None or deadline <= now:
        raise ValueError("review milestone requires a future deadline")
    duration = deadline - now
    return [
        {
            "step_id": step,
            "depends_on": depends,
            "due_at": (deadline if n == 3 else now + duration * n / 3).isoformat(),
            "scope": "review_checkpoint_not_employee_execution_receipt",
        }
        for n, step, depends in (
            (1, "inspect", []),
            (2, "plan", ["inspect"]),
            (3, "verify", ["plan"]),
        )
    ]


def goal_conflicts(
    goal: dict[str, Any], others: list[dict[str, Any]], *, now: datetime
) -> list[dict[str, str]]:
    """Explicit exclusions and incompatible observed metric bounds fail closed."""
    result: list[dict[str, str]] = []
    owner = goal.get("candidate_owner_user_id")
    for other in others:
        if (
            not isinstance(other, dict)
            or other.get("id") == goal.get("id")
            or owner is None
            or other.get("candidate_owner_user_id") != owner
            or other.get("status") not in ACTIVE_STATUSES
            or other.get("id") == goal.get("supersedes_goal_id")
        ):
            continue
        try:
            if other.get("review_deadline") and parse_time(other["review_deadline"]) <= now:
                continue
        except (TypeError, ValueError, AttributeError):
            # Invalid persisted deadline is not evidence that another live goal is obsolete.
            pass
        key = other.get("id")
        explicit = goal.get("excludes_goal_ids") or []
        reverse = other.get("excludes_goal_ids") or []
        if not isinstance(explicit, list) or not isinstance(reverse, list):
            result.append({"goal_id": str(key), "reason": "invalid_exclusion_contract"})
            continue
        if key in explicit or goal.get("id") in reverse:
            result.append({"goal_id": str(key), "reason": "explicit_mutual_exclusion"})
            continue
        left, right = goal.get("acceptance"), other.get("acceptance")
        left_scope, right_scope = goal.get("observation"), other.get("observation")
        if (
            not isinstance(left, dict)
            or not isinstance(right, dict)
            or not isinstance(left_scope, dict)
            or not isinstance(right_scope, dict)
        ):
            result.append({"goal_id": str(key), "reason": "invalid_metric_scope"})
            continue
        if (
            not left.get("metric")
            or left.get("metric") != right.get("metric")
            or left.get("stage") != right.get("stage")
            or left_scope.get("source_owner") != right_scope.get("source_owner")
        ):
            continue
        directions = {left.get("direction"), right.get("direction")}
        a, b = left.get("target"), right.get("target")
        if directions == {"min", "max"}:
            if (
                type(a) not in (int, float)
                or type(b) not in (int, float)
                or (type(a) is float and not math.isfinite(a))
                or (type(b) is float and not math.isfinite(b))
            ):
                result.append({"goal_id": str(key), "reason": "invalid_metric_bounds"})
                continue
            lower = a if left["direction"] == "max" else b
            upper = a if left["direction"] == "min" else b
            if lower > upper:
                result.append({"goal_id": str(key), "reason": "incompatible_metric_bounds"})
    return result


def goal_dependency_gate(goal: dict[str, Any], others: list[dict[str, Any]]) -> dict[str, Any]:
    """A completed task alone cannot satisfy a dependency without acceptance proof."""
    dependencies = goal.get("depends_on_goal_ids")
    if dependencies is None:
        dependencies = []
    if (
        not isinstance(dependencies, list)
        or len(dependencies) > 32
        or any(not isinstance(row, str) or not row for row in dependencies)
        or len(dependencies) != len(set(dependencies))
        or goal.get("id") in dependencies
    ):
        return {"status": "blocked", "reason": "invalid_goal_dependencies"}
    by_id = {row.get("id"): row for row in others if isinstance(row, dict)}
    pending = []
    for dependency in dependencies:
        predecessor = by_id.get(dependency)
        if predecessor is None:
            return {"status": "blocked", "reason": "missing_goal_dependency"}
        proof = predecessor.get("step_projection") or {}
        if (
            predecessor.get("status") not in {"execution_verified", "completed"}
            or proof.get("all_steps_verified") is not True
            or proof.get("independent_acceptance") != "verified_all_accepted"
        ):
            pending.append(dependency)
    return {"status": "waiting" if pending else "ready", "pending": pending}


def candidate_contract_valid(goal: dict[str, Any], *, now: datetime) -> bool:
    """An editable projection cannot change an original verified observation."""
    if goal.get("candidate_origin") != "customer_value_gap/v1":
        return True
    try:
        observation = goal["observation"]
        acceptance = goal["acceptance"]
        stage = goal["issue_key"]
        if not isinstance(observation, dict) or not isinstance(acceptance, dict):
            return False
        if (
            stage not in STAGE_SEVERITY
            or observation.get("stage") != stage
            or observation.get("source_owner")
            not in {"python_payment_orders", "java_postgresql_internal_api"}
            or observation.get("window_days") != 90
            or type(observation.get("gap_count")) is not int
            or observation["gap_count"] <= 0
            or type(goal.get("candidate_owner_user_id")) is not int
            or goal["candidate_owner_user_id"] <= 0
            or acceptance.get("metric") != "customer_value_lifecycle_gap_count"
            or acceptance.get("stage") != stage
            or acceptance.get("direction", "min") != "min"
            or acceptance.get("baseline") != observation["gap_count"]
            or type(acceptance.get("target")) is not int
            or acceptance["target"] != 0
            or not isinstance(goal.get("evidence_refs"), list)
            or not goal["evidence_refs"]
            or goal["evidence_refs"][0] != "customer-value-gap:" + _hash(observation)
        ):
            return False
        return parse_time(observation["observed_at"]) <= now < parse_time(
            goal["review_deadline"]
        )
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return False


def governance_gate(
    goal: dict[str, Any], others: list[dict[str, Any]], *, now: datetime
) -> dict[str, Any]:
    conflicts = goal_conflicts(goal, others, now=now)
    dependencies = goal_dependency_gate(goal, others)
    if not candidate_contract_valid(goal, now=now):
        status = "blocked_invalid_candidate"
    elif goal.get("status") not in ACTIVE_STATUSES:
        status = "terminal"
    elif conflicts:
        status = "blocked_conflict"
    elif dependencies["status"] != "ready":
        status = "blocked_dependency"
    else:
        status = "reviewable"
    return {
        "status": status,
        "conflicts": conflicts,
        "dependencies": dependencies,
        "authorization": "requires_existing_human_portfolio_approval",
        "estimated_profit": None,
        "independent_business_effect": "unverified",
    }


def project_goal_governance(state: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Read-only status surface; all business truth stays in the original ledgers."""
    goals = state.get("goals") or []
    result: list[dict[str, Any]] = []
    for goal in goals:
        if not isinstance(goal, dict) or goal.get("candidate_origin") != "customer_value_gap/v1":
            continue
        milestones = []
        for row in goal.get("milestones", []):
            try:
                overdue = parse_time(row["due_at"]) < now
            except (KeyError, ValueError, TypeError, AttributeError):
                overdue = True
            milestones.append(
                {
                    "step_id": row.get("step_id"),
                    "due_at": row.get("due_at"),
                    "overdue": overdue and goal.get("status") in ACTIVE_STATUSES,
                    "scope": "review_checkpoint_only",
                }
            )
        result.append(
            {
                "goal_id": goal.get("id"),
                "status": goal.get("status"),
                "priority": goal.get("priority"),
                "hierarchy": goal.get("hierarchy"),
                "milestones": milestones,
                "governance": governance_gate(goal, goals, now=now),
                "success_verification": (goal.get("step_projection") or {}).get(
                    "independent_acceptance", "not_independently_verified"
                ),
            }
        )
    result.sort(
        key=lambda row: (
            -(row.get("priority") or {}).get("score", 0),
            str(row.get("goal_id") or ""),
        )
    )
    return {
        "schema": "xiaoc_goal_governance/v1",
        "items": result,
        "scope": "existing_life_state_projection_not_new_executor_or_approval",
    }
