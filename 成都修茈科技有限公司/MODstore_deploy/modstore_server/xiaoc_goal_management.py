"""Read-only operating goal discovery over the existing customer-value ledger.

Candidates are review material. They do not create a new approval, budget,
employee task or permission; the existing life/portfolio routes own those.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from modstore_server.xiaoc_life_policy import LifePolicyError, parse_time

ORIGIN = "customer_value_gap/v1"
STAGES = (
    "payment",
    "installation",
    "first_use",
    "outcome",
    "acceptance",
    "reuse",
    "sequence",
    "enterprise_subject",
)
LABELS = dict(zip(STAGES, ("付款", "安装", "首次使用", "产出", "验收", "复用", "顺序", "企业主体")))


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _gaps(value: Any, now: datetime) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or value.get("status") != "ok"
        or value.get("value_ledger_ready") is not True
        or value.get("source_owner") not in {
            "python_payment_orders",
            "java_postgresql_internal_api",
        }
    ):
        return {}
    try:
        observed = parse_time(value["observed_at"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return {}
    if not now - timedelta(days=1) <= observed <= now:
        return {}
    if type(value.get("window_days")) is not int or value["window_days"] != 90:
        return {}
    gaps = value.get("lifecycle_gaps")
    if not isinstance(gaps, dict):
        return {}
    return {
        stage: gaps[stage]
        for stage in STAGES
        if type(gaps.get(stage)) is int and gaps[stage] > 0
    }


def discover_goal_candidate(
    context: dict[str, Any], state: dict[str, Any], owner: int, *, now: datetime
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """One stable candidate per owner and issue, with original observation evidence."""
    if type(owner) is not int or owner <= 0 or state.get("paused"):
        return None
    goals = state.get("goals", [])
    if len(goals) >= 100:
        return None
    value = context.get("customer_value")
    gaps = _gaps(value, now)
    if not gaps or not isinstance(value, dict):
        return None
    policy = state.get("policy", {})
    deadline = now + timedelta(days=7)
    if policy.get("authorization_expires_at"):
        deadline = min(deadline, parse_time(policy["authorization_expires_at"]))
    if deadline <= now:
        return None
    existing = {goal.get("id") for goal in goals if isinstance(goal, dict)}
    for stage, count in sorted(gaps.items(), key=lambda row: (-row[1], row[0])):
        goal_id = "xiaoc-issue-" + _digest([state["identity_id"], owner, ORIGIN, stage])[:24]
        if goal_id in existing:
            continue
        observation = {
            "source_owner": value["source_owner"],
            "observed_at": value["observed_at"],
            "window_days": value["window_days"],
            "stage": stage,
            "gap_count": count,
        }
        ref = "customer-value-gap:" + _digest(observation)
        label = LABELS[stage]
        limits = policy.get("portfolio_limits") or {}
        budget_bound = {
            key: limits.get(key) if type(limits.get(key)) is int and limits[key] >= 0 else None
            for key in ("cost_cents", "tokens", "compute_seconds")
        }
        goal = {
            "id": goal_id,
            "domain": "enterprise",
            "status": "proposed",
            "goal_kind": "operating",
            "candidate_origin": ORIGIN,
            "candidate_owner_user_id": owner,
            "title": f"核对客户价值链{label}缺口",
            "description": f"对原客户价值账本中的{label}缺口核对同口径原记录，提出处理建议。",
            "evidence_refs": [ref],
            "issue_key": stage,
            "observation": observation,
            "priority": {"basis": "observed_gap_count", "score": count},
            "expected_benefit": "识别并减少已核验缺口；收益金额尚未测量。",
            "risk": "窗口滚动、重复归因、误把缺失证据当成客户失败；不得据此自动改写业务。",
            "cost_estimate": {"status": "unknown", "existing_policy_upper_bound": budget_bound},
            "review_deadline": deadline.isoformat(),
            "acceptance": {
                "metric": "customer_value_lifecycle_gap_count",
                "stage": stage,
                "baseline": count,
                "target": 0,
                "condition": "独立回读同口径及原客户/订单；窗口滚动或缺失来源不能证明改善。",
            },
            "subgoals": [
                {"id": "inspect", "depends_on": [], "description": "核对原记录及缺失证据"},
                {"id": "plan", "depends_on": ["inspect"], "description": "提交处理建议与成本风险评审"},
                {"id": "verify", "depends_on": ["plan"], "description": "独立回读核验原结果"},
            ],
            "subgoals_status": "review_only_not_dispatched",
        }
        fact = {"ref": ref, "text": json.dumps(observation, ensure_ascii=False)}
        return goal, fact
    return None


def check_candidate_promotion(
    goal: dict[str, Any], owner: int, limits: dict[str, Any], context: dict[str, Any],
    *, now: datetime,
) -> None:
    """Recheck a deterministic candidate at the ORIGINAL human promotion route."""
    if goal.get("candidate_origin") != ORIGIN:
        return
    if goal.get("candidate_owner_user_id") != owner or goal.get("status") != "proposed":
        raise LifePolicyError("经营候选已失效或不属于当前授权人")
    try:
        deadline = parse_time(goal["review_deadline"])
        expiry = parse_time(limits["expires_at"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise LifePolicyError("经营候选或原提案期限无效") from exc
    if not now < expiry <= deadline:
        raise LifePolicyError("经营候选已过期或提案期限超出候选复核期限")
    if goal.get("issue_key") not in _gaps(context, now):
        raise LifePolicyError("原经营缺口已消失或证据不可用，请重新观察")


def portfolio_goal_closed(record: dict[str, Any], *, now: datetime) -> bool:
    """No new dispatch after original rejection, stop or expiry; readbacks continue."""
    if record.get("halted") or record.get("status") in {"rejected", "withdrawn"}:
        return True
    expiry = (record.get("limits") or {}).get("expires_at")
    if expiry is None:
        return False  # Legacy projection; original portfolio admission still verifies.
    try:
        return parse_time(expiry) <= now
    except (TypeError, ValueError, AttributeError):
        return True
