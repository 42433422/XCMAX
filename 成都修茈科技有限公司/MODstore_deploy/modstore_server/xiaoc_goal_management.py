"""Read-only operating goal discovery over the existing customer-value ledger.

Candidates are review material. They do not create a new approval, budget,
employee task or permission; the existing life/portfolio routes own those.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
EXECUTION_STEPS = ("inspect", "plan")


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


def _previous_expired_candidate(
    goals: list[dict[str, Any]], owner: int, stage: str, value: dict[str, Any],
    *, now: datetime,
) -> tuple[bool, str | None]:
    """Only renew expired, unbound review material, never an approved or stopped goal."""
    prior = [
        goal for goal in goals
        if isinstance(goal, dict)
        and goal.get("candidate_origin") == ORIGIN
        and goal.get("candidate_owner_user_id") == owner
        and goal.get("issue_key") == stage
    ]
    if not prior:
        return True, None
    try:
        observed = parse_time(value["observed_at"])
        dated = []
        for goal in prior:
            observation = goal["observation"]
            deadline = parse_time(goal["review_deadline"])
            if (
                goal.get("status") != "proposed"
                or goal.get("decision_id")
                or goal.get("step_bindings")
                or not isinstance(goal.get("id"), str)
                or not goal["id"]
                or observation.get("source_owner") != value["source_owner"]
                or observation.get("stage") != stage
                or observation.get("window_days") != value["window_days"]
                or not parse_time(observation["observed_at"]) < deadline <= now
                or observed <= deadline
            ):
                return False, None
            dated.append((deadline, goal["id"]))
        return True, max(dated)[1]
    except (KeyError, TypeError, ValueError, AttributeError):
        return False, None


def discover_goal_candidate(
    context: dict[str, Any], state: dict[str, Any], owner: int, *, now: datetime
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """One active review candidate per owner/issue; retain expired review history."""
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
        allowed, predecessor = _previous_expired_candidate(goals, owner, stage, value, now=now)
        if not allowed:
            continue
        identity = [state["identity_id"], owner, ORIGIN, stage]
        if predecessor is not None:
            identity.append(predecessor)
        goal_id = "xiaoc-issue-" + _digest(identity)[:24]
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
        if predecessor is not None:
            goal["supersedes_goal_id"] = predecessor
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
    if candidate_gate(goal, owner, context, now=now)["status"] != "eligible":
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


def candidate_gate(
    goal: dict[str, Any], owner: int, value: dict[str, Any], *, now: datetime
) -> dict[str, Any]:
    """Read-only eligibility. A rolling aggregate is never a fixed-cohort outcome."""
    stage = goal.get("issue_key")
    status = "awaiting_evidence"
    count = None
    source = goal.get("observation") or {}
    try:
        deadline = parse_time(goal["review_deadline"])
        original_at = parse_time(source["observed_at"])
        observed = parse_time(value["observed_at"])
        if goal.get("candidate_owner_user_id") != owner:
            status = "owner_mismatch"
        elif now >= deadline:
            status = "expired"
        elif (
            stage in STAGES
            and source.get("stage") == stage
            and value.get("status") == "ok"
            and value.get("value_ledger_ready") is True
            and value.get("source_owner") == source.get("source_owner")
            and value.get("source_owner") in {
                "python_payment_orders", "java_postgresql_internal_api"
            }
            and value.get("window_days") == source.get("window_days") == 90
            and max(original_at, now - timedelta(days=1)) <= observed <= now
        ):
            gaps = value.get("lifecycle_gaps")
            if isinstance(gaps, dict) and type(gaps.get(stage)) is int and gaps[stage] >= 0:
                count = gaps[stage]
                status = "eligible" if count > 0 else "no_current_gap"
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    result = {
        "goal_id": goal["id"],
        "owner_user_id": owner,
        "status": status,
        "as_of": now.isoformat(),
        "observed_at": value.get("observed_at") if isinstance(value, dict) else None,
        "source_owner": source.get("source_owner"),
        "gap_count": count,
        "scope": "current_rolling_observation_not_outcome_verification",
    }
    result["evidence_ref"] = "operating-gate:" + _digest(result)
    return result


class GoalStepAllocation(BaseModel):
    """Explicit allocations supplied by the current human owner, not model text."""

    model_config = ConfigDict(extra="forbid", strict=True)
    step_id: Literal["inspect", "plan"]
    employee_id: str = Field(min_length=1, max_length=128)
    input_data: dict[str, Any] = Field(default_factory=dict)
    cost_cents: int = Field(ge=0, le=100_000_000)
    tokens: int = Field(ge=0, le=1_000_000_000)
    compute_seconds: int = Field(ge=1, le=240)


def build_goal_opportunities(
    goal: dict[str, Any], allocations: list[GoalStepAllocation], limits: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Compile the fixed review DAG to the existing CP-SAT opportunity contract."""
    from modstore_server.strategic_portfolio import Opportunity, RESOURCES

    if goal.get("candidate_origin") != ORIGIN:
        raise LifePolicyError("仅原经营候选支持此依赖分解")
    by_step = {row.step_id: row for row in allocations}
    if len(allocations) != 2 or set(by_step) != set(EXECUTION_STEPS):
        raise LifePolicyError("须逐项分配核对与建议两个原子目标")
    if any(sum(getattr(row, key) for row in allocations) > limits[key] for key in RESOURCES):
        raise LifePolicyError("子目标总资源超过原提案预算")
    ids = {
        step: "life-step-" + _digest([goal["id"], step])[:32] for step in EXECUTION_STEPS
    }
    descriptions = {
        "inspect": "核对原客户价值链缺口及同口径原记录；提交来源与缺失证据。",
        "plan": "依据原核对任务结果提交处理建议及成本风险；不执行业务变更。",
    }
    rows = []
    for step in EXECUTION_STEPS:
        allocation = by_step[step]
        rows.append(
            Opportunity(
                opportunity_id=ids[step],
                title=f"{goal['title']}：{step}"[:200],
                task=descriptions[step],
                employee_id=allocation.employee_id,
                input_data=allocation.input_data,
                value_score=100,
                confidence_bps=5000,
                cost_cents=allocation.cost_cents,
                tokens=allocation.tokens,
                compute_seconds=allocation.compute_seconds,
                risk="medium",
                depends_on=[] if step == "inspect" else [ids["inspect"]],
                source_refs=list(dict.fromkeys(goal["evidence_refs"])),
            ).model_dump()
        )
    return rows, ids


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def operating_dependency_handoff(
    opportunity: dict[str, Any], tasks: dict[str, Any]
) -> list[dict[str, Any]]:
    """Read completed predecessor evidence from the same original portfolio only.

    The projection is evidence metadata, not new executable inputs or arbitrary
    worker text. Existing approved workspace and file contracts remain unchanged.
    """
    from modstore_server.strategic_execution_receipts import evaluate_execution_receipt
    from modstore_server.strategic_portfolio import PortfolioError, digest

    if not str(opportunity.get("opportunity_id", "")).startswith("life-step-"):
        return []
    result = []
    for key in opportunity.get("depends_on", []):
        task = tasks.get(key)
        receipt = task.get("execution_receipt") if isinstance(task, dict) else None
        calls = task.get("calls") if isinstance(task, dict) else None
        if (
            not isinstance(task, dict)
            or task.get("status") != "completed"
            or not _valid_sha(task.get("result_sha256"))
            or not isinstance(receipt, dict)
            or receipt.get("truncated")
            or evaluate_execution_receipt(receipt).status != "completed"
            or not isinstance(calls, dict)
            or any(
                not isinstance(call, dict) or call.get("status") != "settled"
                for call in calls.values()
            )
        ):
            raise PortfolioError("operating dependency has no verified terminal receipt")
        inner = receipt.get("result")
        inner = inner if isinstance(inner, dict) else receipt
        artifacts = []
        for output in inner.get("outputs", []) if isinstance(inner.get("outputs"), list) else []:
            if not isinstance(output, dict) or output.get("handler") != "direct_python":
                continue
            body = output.get("output")
            if not isinstance(body, dict) or body.get("status") != "completed":
                continue
            rows = body.get("artifacts")
            if not isinstance(rows, list):
                continue
            for item in rows:
                if (
                    isinstance(item, dict)
                    and _valid_sha(item.get("artifact_sha256"))
                    and type(item.get("size_bytes")) is int
                    and item["size_bytes"] >= 0
                ):
                    artifacts.append({
                        "artifact_sha256": item["artifact_sha256"],
                        "size_bytes": item["size_bytes"],
                    })
                if len(artifacts) >= 32:
                    break
            if len(artifacts) >= 32:
                break
        result.append({
            "opportunity_id": key,
            "result_sha256": task["result_sha256"],
            "receipt_sha256": digest(receipt),
            "artifact_receipts": artifacts,
            "scope": "verified_predecessor_receipt_metadata_not_current_artifact_bytes",
        })
    return result


def project_goal_steps(goal: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Read back exact original opportunities/tasks; do not equate review with success."""
    bindings = goal.get("step_bindings")
    if not isinstance(bindings, dict) or set(bindings) != set(EXECUTION_STEPS):
        return {}
    if (
        goal.get("decision_id") != record.get("decision_id")
        or goal.get("candidate_owner_user_id") != record.get("owner_user_id")
        or len(set(bindings.values())) != len(EXECUTION_STEPS)
    ):
        return {"status": "binding_mismatch"}
    opportunities = {
        row["opportunity_id"]: row for row in record.get("opportunities", [])
    }
    if (
        set(opportunities) != set(bindings.values())
        or opportunities[bindings["inspect"]].get("depends_on") != []
        or opportunities[bindings["plan"]].get("depends_on") != [bindings["inspect"]]
    ):
        return {"status": "binding_mismatch"}
    tasks = record.get("tasks") or {}
    steps = []
    for step in EXECUTION_STEPS:
        opportunity_id = bindings[step]
        task = tasks.get(opportunity_id) or {}
        steps.append({
            "step_id": step,
            "opportunity_id": opportunity_id,
            "task_status": task.get("status", "pending"),
            "result_sha256": task.get("result_sha256"),
        })
    all_verified = all(
        step["task_status"] == "completed" and _valid_sha(step["result_sha256"])
        for step in steps
    )
    handoff = "pending"
    if all_verified:
        from modstore_server.strategic_portfolio import PortfolioError

        try:
            expected = operating_dependency_handoff(opportunities[bindings["plan"]], tasks)
        except PortfolioError:
            expected = []
        handoff = (
            "verified"
            if expected and tasks[bindings["plan"]].get("dependency_handoff") == expected
            else "unverified"
        )
    return {
        "status": "original_task_projection",
        "decision_id": record["decision_id"],
        "steps": steps,
        "all_steps_verified": all_verified and handoff == "verified",
        "dependency_handoff": handoff,
        "independent_acceptance": "pending_fixed_cohort_verification",
    }
