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

from modstore_server.strategic_customer_outcomes import CustomerGoalBinding
from modstore_server.xiaoc_goal_governance import (
    goal_path,
    observed_priority,
    review_milestones,
)
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
ExecutionStep = Literal["inspect", "plan"]
EXECUTION_STEPS: tuple[ExecutionStep, ...] = ("inspect", "plan")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _gaps(value: Any, now: datetime) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or value.get("status") != "ok"
        or value.get("value_ledger_ready") is not True
        or value.get("source_owner")
        not in {
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
        stage: gaps[stage] for stage in STAGES if type(gaps.get(stage)) is int and gaps[stage] > 0
    }


def _previous_expired_candidate(
    goals: list[dict[str, Any]],
    owner: int,
    stage: str,
    value: dict[str, Any],
    *,
    now: datetime,
) -> tuple[bool, str | None]:
    """Only renew expired, unbound review material, never an approved or stopped goal."""
    prior = [
        goal
        for goal in goals
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
            "priority": observed_priority(stage, count, value["observed_at"], now=now),
            "hierarchy": goal_path(
                state["identity_id"], str(state.get("mission") or ""), goal_id, now=now
            ),
            "depends_on_goal_ids": [],
            "milestones": review_milestones(now=now, deadline=deadline),
            "expected_benefit": "识别并减少已核验缺口；收益金额尚未测量。",
            "risk": "窗口滚动、重复归因、误把缺失证据当成客户失败；不得据此自动改写业务。",
            "cost_estimate": {"status": "unknown", "existing_policy_upper_bound": budget_bound},
            "review_deadline": deadline.isoformat(),
            "acceptance": {
                "metric": "customer_value_lifecycle_gap_count",
                "stage": stage,
                "direction": "min",
                "baseline": count,
                "target": 0,
                "condition": "独立回读同口径及原客户/订单；窗口滚动或缺失来源不能证明改善。",
            },
            "subgoals": [
                {"id": "inspect", "depends_on": [], "description": "核对原记录及缺失证据"},
                {
                    "id": "plan",
                    "depends_on": ["inspect"],
                    "description": "提交处理建议与成本风险评审",
                },
                {"id": "verify", "depends_on": ["plan"], "description": "独立回读核验原结果"},
            ],
            "subgoals_status": "review_only_not_dispatched",
        }
        if predecessor is not None:
            goal["supersedes_goal_id"] = predecessor
        fact = {"ref": ref, "text": json.dumps(observation, ensure_ascii=False)}
        return goal, fact
    return None


def resumable_operating_candidate(
    context: dict[str, Any],
    state: dict[str, Any],
    owner: int,
    *,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Return a sourced existing proposal after a previous unconfigured/failed cycle.

    The original stable goal and idempotency key are reused, so no parallel
    queue or duplicate business action is created by a repeat observation.
    """
    from modstore_server.xiaoc_goal_governance import governance_gate

    policy = state.get("policy") or {}
    value = context.get("customer_value")
    if (
        state.get("paused")
        or state.get("stopped")
        or not policy.get("employee_id")
        or not isinstance(policy.get("portfolio_limits"), dict)
        or not isinstance(value, dict)
        or type(owner) is not int
        or owner <= 0
    ):
        return None
    pending = []
    goals = state.get("goals") or []
    for goal in goals:
        if (
            not isinstance(goal, dict)
            or goal.get("candidate_origin") != ORIGIN
            or goal.get("status") != "proposed"
            or goal.get("candidate_owner_user_id") != owner
            or goal.get("decision_id")
            or goal.get("step_bindings")
        ):
            continue
        try:
            if goal.get("next_review_at") and parse_time(goal["next_review_at"]) > now:
                continue
        except (TypeError, ValueError, AttributeError):
            continue
        if (
            candidate_gate(goal, owner, value, now=now)["status"] != "eligible"
            or governance_gate(goal, goals, now=now)["status"] != "reviewable"
        ):
            continue
        priority = goal.get("priority") or {}
        score = priority.get("score") if isinstance(priority, dict) else 0
        pending.append((score if type(score) is int else 0, goal))
    if not pending:
        return None
    selected = sorted(pending, key=lambda row: (-row[0], row[1]["id"]))[0][1]
    observation = selected["observation"]
    fact = {"ref": selected["evidence_refs"][0], "text": json.dumps(observation, ensure_ascii=False)}
    return dict(selected), fact


def check_candidate_promotion(
    goal: dict[str, Any],
    owner: int,
    limits: dict[str, Any],
    context: dict[str, Any],
    *,
    now: datetime,
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
            and value.get("source_owner")
            in {"python_payment_orders", "java_postgresql_internal_api"}
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
    customer_goal_bindings: list[CustomerGoalBinding] = Field(default_factory=list, max_length=32)
    acceptance_window_days: int | None = Field(default=None, ge=1, le=7)


def build_goal_opportunities(
    goal: dict[str, Any], allocations: list[GoalStepAllocation], limits: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Compile the fixed review DAG to the existing CP-SAT opportunity contract."""
    from modstore_server.strategic_portfolio import RESOURCES, Opportunity
    from modstore_server.strategy_bets import CUSTOMER_ACCEPTANCE_METRIC, BetHypothesis

    if goal.get("candidate_origin") != ORIGIN:
        raise LifePolicyError("仅原经营候选支持此依赖分解")
    by_step = {row.step_id: row for row in allocations}
    if len(allocations) != 2 or set(by_step) != set(EXECUTION_STEPS):
        raise LifePolicyError("须逐项分配核对与建议两个原子目标")
    if any(sum(getattr(row, key) for row in allocations) > limits[key] for key in RESOURCES):
        raise LifePolicyError("子目标总资源超过原提案预算")
    inspect, plan = by_step["inspect"], by_step["plan"]
    if inspect.customer_goal_bindings or inspect.acceptance_window_days is not None:
        raise LifePolicyError("核对步骤不能代替客户交付验收")
    if bool(plan.customer_goal_bindings) != (plan.acceptance_window_days is not None):
        raise LifePolicyError("固定客户验收须同时绑定原目标及观察期限")
    cohort = [row.customer_goal_id for row in plan.customer_goal_bindings]
    if len(cohort) != len(set(cohort)):
        raise LifePolicyError("固定客户验收目标不能重复")
    ids: dict[str, str] = {
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
                customer_goal_ids=cohort if step == "plan" else [],
                customer_goal_bindings=allocation.customer_goal_bindings,
                hypothesis=(
                    BetHypothesis(
                        hypothesis="固定已同意的客户目标全部取得原独立验收证据",
                        metric_id=CUSTOMER_ACCEPTANCE_METRIC,
                        threshold=1.0,
                        direction="max",
                        window_days=allocation.acceptance_window_days,
                        kill_criteria=["固定窗口内未观察到全体目标验收"],
                        kill_on_miss=False,
                    )
                    if allocation.acceptance_window_days is not None
                    else None
                ),
            ).model_dump()
        )
    return rows, ids


def compile_autonomous_review_plan(
    goal: dict[str, Any],
    *,
    owner: int,
    policy: dict[str, Any],
    goals: list[dict[str, Any]],
    current_value: dict[str, Any],
    now: datetime,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Compile inspect -> plan review tasks using ONLY the existing human policy.

    This never approves the portfolio. Empty tool input prevents automatically
    selecting a privileged business mutation under a generic employee policy.
    """
    from modstore_server.xiaoc_goal_governance import governance_gate

    limits = policy.get("portfolio_limits")
    employee_id = policy.get("employee_id")
    if (
        not isinstance(limits, dict)
        or not isinstance(employee_id, str)
        or not employee_id
        or policy.get("task_input")
    ):
        raise LifePolicyError("自主调查需要原预算、员工及空的安全任务输入")
    if goal.get("candidate_origin") != ORIGIN or goal.get("status") != "proposed":
        raise LifePolicyError("仅未审批的原经营候选可自动生成调查提案")
    check_candidate_promotion(goal, owner, limits, current_value, now=now)
    if governance_gate(goal, goals, now=now)["status"] != "reviewable":
        raise LifePolicyError("原候选来源、冲突或前置依赖未通过审查")
    seconds = limits.get("compute_seconds")
    if type(seconds) is not int or not 2 <= seconds <= 7_776_000:
        raise LifePolicyError("原预算不足以执行两个可核验的原子调查步骤")
    # A single review step may consume at most 240 seconds in the approved worker.
    allowed_seconds = min(seconds, 480)
    resources = {
        name: limits.get(name) for name in ("cost_cents", "tokens", "compute_seconds")
    }
    if any(type(value) is not int or value < 0 for value in resources.values()):
        raise LifePolicyError("原预算资源合同不完整")
    allocations = []
    for index, step in enumerate(EXECUTION_STEPS):
        cost = limits["cost_cents"] // 2 if index == 0 else limits["cost_cents"] - limits["cost_cents"] // 2
        tokens = limits["tokens"] // 2 if index == 0 else limits["tokens"] - limits["tokens"] // 2
        compute = allowed_seconds // 2 if index == 0 else allowed_seconds - allowed_seconds // 2
        allocations.append(
            GoalStepAllocation(
                step_id=step,
                employee_id=employee_id,
                input_data={},
                cost_cents=cost,
                tokens=tokens,
                compute_seconds=compute,
            )
        )
    return build_goal_opportunities(goal, allocations, limits)


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= set("0123456789abcdef")


def _terminal_task_receipt(task: Any) -> dict[str, Any] | None:
    from modstore_server.strategic_execution_receipts import evaluate_execution_receipt

    if not isinstance(task, dict) or task.get("status") != "completed":
        return None
    receipt, calls = task.get("execution_receipt"), task.get("calls")
    if (
        _valid_sha(task.get("result_sha256"))
        and isinstance(receipt, dict)
        and not receipt.get("truncated")
        and evaluate_execution_receipt(receipt).status == "completed"
        and isinstance(calls, dict)
        and all(isinstance(c, dict) and c.get("status") == "settled" for c in calls.values())
    ):
        return receipt
    return None


def operating_dependency_handoff(
    opportunity: dict[str, Any], tasks: dict[str, Any]
) -> list[dict[str, Any]]:
    """Read only predecessor receipt metadata, not executable inputs or current artifact bytes."""
    from modstore_server.strategic_portfolio import PortfolioError, digest

    if not str(opportunity.get("opportunity_id", "")).startswith("life-step-"):
        return []
    result = []
    for key in opportunity.get("depends_on", []):
        task = tasks.get(key)
        if not isinstance(task, dict):
            raise PortfolioError("operating dependency has no verified terminal receipt")
        if (receipt := _terminal_task_receipt(task)) is None:
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
                    artifacts.append(
                        {
                            "artifact_sha256": item["artifact_sha256"],
                            "size_bytes": item["size_bytes"],
                        }
                    )
                if len(artifacts) >= 32:
                    break
            if len(artifacts) >= 32:
                break
        result.append(
            {
                "opportunity_id": key,
                "result_sha256": task["result_sha256"],
                "receipt_sha256": digest(receipt),
                "artifact_receipts": artifacts,
                "scope": "verified_predecessor_receipt_metadata_not_current_artifact_bytes",
            }
        )
    return result


def _fixed_cohort_acceptance(
    item: dict[str, Any], record: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Evaluate only the original frozen, artifact-linked customer cohort."""
    from modstore_server.strategic_portfolio import digest
    from modstore_server.strategy_bets import CUSTOMER_ACCEPTANCE_METRIC, judge

    bindings = item.get("customer_goal_bindings")
    if not bindings:
        return "pending_fixed_cohort_verification", {}
    unknown = "unknown_fixed_cohort_evidence"
    try:
        cohort = [CustomerGoalBinding.model_validate(row).model_dump() for row in bindings]
        ids = [row["customer_goal_id"] for row in cohort]
        target = item["hypothesis"]
        key = item["opportunity_id"]
        authorization = record["authorization"]
        if (
            not ids
            or len(ids) != len(set(ids))
            or set(ids) != set(item["customer_goal_ids"])
            or target["metric_id"] != CUSTOMER_ACCEPTANCE_METRIC
            or target["threshold"] != 1.0
            or target["direction"] != "max"
            or not _valid_sha(record.get("proposal_sha256"))
            or authorization.get("proposal_sha256") != record["proposal_sha256"]
            or authorization.get("user_id") != record["owner_user_id"]
            or not authorization.get("actor")
        ):
            return unknown, {}
        snapshot = record.get("hypothesis_outcomes", {}).get(key)
        if snapshot is None:
            return "pending_fixed_cohort_verification", {"cohort_sha256": digest(cohort)}
        task = record["tasks"][key]
        evidence = snapshot["evidence"]
        accepted, total, value = (
            evidence.get("accepted_goals"),
            evidence.get("target_goals"),
            evidence.get("value"),
        )
        start, end, reviewed = (
            parse_time(snapshot["window_start"]),
            parse_time(snapshot["window_end"]),
            parse_time(snapshot["reviewed_at"]),
        )
        if (
            task.get("status") != "completed"
            or not _valid_sha(task.get("result_sha256"))
            or snapshot["opportunity_id"] != key
            or snapshot["hypothesis"] != target
            or digest({k: v for k, v in snapshot.items() if k != "snapshot_sha256"})
            != snapshot.get("snapshot_sha256")
            or start != parse_time(task["started_at"])
            or end != start + timedelta(days=target["window_days"])
            or not start <= parse_time(task["completed_at"]) <= end <= reviewed <= datetime.now(UTC)
            or evidence.get("source")
            != "CustomerValueReceipt:verified_outcome_and_customer_acceptance"
            or evidence.get("basis")
            != "approved_goals_with_completed_artifact_and_customer_acceptance"
            or not _valid_sha(evidence.get("evidence_sha256"))
            or type(total) is not int
            or total != len(ids)
            or type(accepted) is not int
            or not 0 <= accepted <= total
            or type(value) not in (int, float)
            or value != accepted / total
            or snapshot["verdict"] != judge(CUSTOMER_ACCEPTANCE_METRIC, value, 1.0, "max")
        ):
            return unknown, {}
        return (
            "verified_all_accepted" if accepted == total else "not_all_verified_by_cutoff",
            {
                "cohort_sha256": digest(cohort),
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "metric_evidence_sha256": evidence["evidence_sha256"],
                "target_goals": total,
                "accepted_goals": accepted,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "scope": "original_customer_acceptance_not_incremental_business_effect",
            },
        )
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return unknown, {}


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
    opportunities = {row["opportunity_id"]: row for row in record.get("opportunities", [])}
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
        steps.append(
            {
                "step_id": step,
                "opportunity_id": opportunity_id,
                "task_status": task.get("status", "pending"),
                "result_sha256": task.get("result_sha256"),
            }
        )
    all_verified, handoff = False, "pending"
    if all(s["task_status"] == "completed" and _valid_sha(s["result_sha256"]) for s in steps):
        from modstore_server.strategic_portfolio import PortfolioError, digest

        all_verified = all(
            (receipt := _terminal_task_receipt(tasks[s["opportunity_id"]])) is not None
            and digest(receipt) == s["result_sha256"]
            for s in steps
        )
        try:
            expected = operating_dependency_handoff(opportunities[bindings["plan"]], tasks)
        except PortfolioError:
            expected = []
        handoff = (
            "verified"
            if expected and tasks[bindings["plan"]].get("dependency_handoff") == expected
            else "unverified"
        )
    acceptance, acceptance_proof = _fixed_cohort_acceptance(opportunities[bindings["plan"]], record)
    if acceptance == "verified_all_accepted" and not (all_verified and handoff == "verified"):
        acceptance = "unknown_dependency_not_verified"
    return {
        "status": "original_task_projection",
        "decision_id": record["decision_id"],
        "steps": steps,
        "all_steps_verified": all_verified and handoff == "verified",
        "dependency_handoff": handoff,
        "independent_acceptance": acceptance,
        **({"acceptance_proof": acceptance_proof} if acceptance_proof else {}),
    }
