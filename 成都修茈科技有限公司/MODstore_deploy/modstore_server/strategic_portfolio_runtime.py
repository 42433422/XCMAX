"""Strategy execution, attributable customer outcomes and bounded replanning."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from modstore_server.db.db_base import get_session_factory
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from modstore_server.strategic_portfolio import (
    RESOURCES,
    SCHEMA,
    PortfolioError,
    _date,
    _json,
    digest,
    mutate_portfolio,
    plan_portfolio,
    portfolio_status,
    require_authorization,
)
from modstore_server.strategy_bets import BetHypothesis


def _action_id(decision_id: str, opportunity_id: str) -> str:
    return "portfolio-" + digest([decision_id, opportunity_id])[:32]


def _consumed(task: dict[str, Any], resource: str) -> int:
    field = {
        "cost_cents": "accrued_cost_cents",
        "tokens": "actual_tokens",
        "compute_seconds": "compute_seconds",
    }[resource]
    return (
        int(task.get(field, task["reservation"][resource]))
        if task["status"] in {"completed", "failed"}
        else int(task["reservation"][resource])
    )


def _claim(decision_id: str, owner_user_id: int | None) -> dict[str, Any] | None:
    token = uuid.uuid4().hex

    def apply(
        row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any
    ) -> dict[str, Any] | None:
        require_authorization(row, proposal, state)
        tasks = state["tasks"]
        now = datetime.now(UTC)
        running = [task for task in tasks.values() if task["status"] in {"running", "waiting"}]
        if any(_date(task["deadline"]) <= now for task in running):
            state.update(halted=True, stop_reason="execution_outcome_unknown_after_deadline")
            return None
        if len(running) >= proposal["limits"]["max_parallel"]:
            return None
        opportunities = {item["opportunity_id"]: item for item in proposal["opportunities"]}
        for key in state["plan"]["selected"]:
            opportunity = opportunities[key]
            if key in tasks or any(
                tasks.get(dep, {}).get("status") != "completed" for dep in opportunity["depends_on"]
            ):
                continue
            reservation = {field: opportunity[field] for field in RESOURCES}
            if any(
                sum(_consumed(task, field) for task in tasks.values()) + reservation[field]
                > proposal["limits"][field]
                for field in RESOURCES
            ):
                raise PortfolioError("portfolio resource budget exhausted")
            task = {
                "status": "running",
                "lease_token": token,
                "reservation": reservation,
                "started_at": now.isoformat(),
                "deadline": (now + timedelta(seconds=reservation["compute_seconds"])).isoformat(),
                "calls": {},
            }
            tasks[key] = task
            action = session.execute(
                select(StrategicActionItem).where(
                    StrategicActionItem.action_id == _action_id(decision_id, key)
                )
            ).scalar_one()
            action.status, action.updated_at = "in_progress", now
            action.result_json = _json(
                {"schema": SCHEMA, "opportunity_id": key, "lease_token": token}
            )
            return {
                **opportunity,
                "decision_id": decision_id,
                "owner_user_id": proposal["owner_user_id"],
                "lease_token": token,
                "deadline": task["deadline"],
            }
        return None

    return mutate_portfolio(decision_id, apply, owner_user_id=owner_user_id)


async def discover_portfolio_opportunities(
    *,
    owner_user_id: int,
    goal: str,
    limits: dict[str, Any],
    use_llm: bool = True,
) -> dict[str, Any]:
    """Reuse the existing strategic planner with account-scoped live inputs."""
    from sqlalchemy import func

    from modstore_server import strategy_planner
    from modstore_server.customer_value_classification import amount_cents, classify_payment_order
    from modstore_server.customer_value_payment_source import load_authoritative_payment_orders
    from modstore_server.db.llm_chat import LlmCallLog
    from modstore_server.models_cs import CustomerServiceTicket
    from modstore_server.services.llm import (
        chat_dispatch_via_platform_only,
        resolve_platform_bench_llm,
    )
    from modstore_server.strategic_portfolio import Opportunity, PortfolioLimits
    from modstore_server.strategic_portfolio_usage import planning_admission, planning_usage_scope
    from modstore_server.task_router import _load_all_employee_profiles

    if type(owner_user_id) is not int or owner_user_id <= 0:
        raise PortfolioError("owner is required for planning context")
    cap = PortfolioLimits.model_validate(limits)
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        tickets = (
            session.execute(
                select(CustomerServiceTicket)
                .where(
                    CustomerServiceTicket.user_id == owner_user_id,
                    CustomerServiceTicket.status != "closed",
                )
                .order_by(CustomerServiceTicket.id.desc())
                .limit(12)
            )
            .scalars()
            .all()
        )
        usage = session.execute(
            select(func.count(LlmCallLog.id), func.sum(LlmCallLog.total_tokens)).where(
                LlmCallLog.user_id == owner_user_id,
                LlmCallLog.created_at >= now - timedelta(days=30),
            )
        ).one()
        gaps = [f"客户问题 {ticket.ticket_no}：{ticket.title[:180]}" for ticket in tickets]
        prior_rows = (
            session.execute(
                select(StrategicDecision)
                .where(
                    StrategicDecision.scope == "strategy_portfolio",
                    StrategicDecision.scope_ref.like(f"user:{owner_user_id}:%"),
                )
                .order_by(StrategicDecision.updated_at.desc())
                .limit(10)
            )
            .scalars()
            .all()
        )
        history = []
        for previous in prior_rows:
            proposal_data = json.loads(str(previous.decision_payload_json or "{}"))
            if proposal_data.get("owner_user_id") == owner_user_id:
                prior_state = json.loads(str(previous.execution_result_json or "{}"))
                history.extend(prior_state.get("reviews", [])[-1:])
    source = load_authoritative_payment_orders(30)
    own_orders = [
        order
        for order in source.get("orders") or []
        if str(order.get("user_id")) == str(owner_user_id)
        and classify_payment_order(order, cutoff=now - timedelta(days=30))[0]
    ]
    metrics = {
        "open_tickets": len(tickets),
        "llm_calls_30d": int(usage[0] or 0),
        "llm_tokens_30d": int(usage[1] or 0),
        "payments_available": source.get("source_available") is True,
        "verified_paid_cents_30d": (
            sum(amount_cents(order) for order in own_orders)
            if source.get("source_authoritative") is True
            else None
        ),
    }
    source_refs = [
        f"account:{owner_user_id}:metrics:{digest(metrics)}",
        *[f"customer_ticket:{ticket.id}" for ticket in tickets],
    ]
    employees = [row["id"] for row in _load_all_employee_profiles() if row.get("id")]
    if not employees:
        return {
            "source": "live_metrics",
            "metrics": metrics,
            "source_refs": source_refs,
            "opportunities": [],
            "reason": "no_registered_executor",
        }
    company_context = await asyncio.to_thread(strategy_planner.collect_context)

    planning_calls: list[dict[str, Any]] = []

    class PlatformPlanner:
        async def chat(
            self,
            messages: list[dict[str, str]],
            *,
            temperature: float = 0.3,
            max_tokens: int = 1600,
        ) -> str | None:
            provider, model = resolve_platform_bench_llm()
            if not provider or not model:
                return None
            admission = await planning_admission(provider, model)
            if admission is None:
                planning_calls.append(
                    {
                        "provider": provider,
                        "model": model,
                        "status": "blocked",
                        "reason": "existing_platform_subscription_headroom_unknown",
                    }
                )
                return None
            with planning_usage_scope(owner_user_id, admission) as context:
                result = await chat_dispatch_via_platform_only(
                    provider, model, messages, max_tokens=min(max_tokens, 1600)
                )
                planning_calls.extend(context["receipts"])
            return str(result.get("content") or "") if result.get("ok") else None

    context = {
        **company_context,
        "goal": goal,
        "project_gaps": gaps,
        "observed_metrics": metrics,
        "prior_outcome_reviews": history,
        "proposal_limits_not_yet_authorized": cap.model_dump(),
        "source_refs": source_refs,
        "employees": employees,
    }
    plan = await strategy_planner.generate_candidates(
        context, chat=PlatformPlanner() if use_llm else None
    )
    default_employee = "daily-orchestrator" if "daily-orchestrator" in employees else employees[0]
    count = max(1, len(plan["candidates"]))
    opportunities = [
        Opportunity(
            opportunity_id="op-" + digest([goal, feature["title"], source_refs])[:20],
            title=feature["title"][:200],
            task=f"{feature['title']}\n目的：{feature['hypothesis']}\n验收：{feature['metric_id']} {feature['direction']} {feature['threshold']}\n只在现有审批范围内执行；对外通信、支付和新增资源仍需其原有授权。"[
                :4000
            ],
            employee_id=(
                feature.get("employee_id")
                if feature.get("employee_id") in employees
                else default_employee
            ),
            value_score=int(feature["expected_value"] * 100 / feature["effort"]),
            confidence_bps=5000 if plan["source"] == "llm" else 2500,
            cost_cents=cap.cost_cents // count,
            tokens=cap.tokens // count,
            compute_seconds=max(1, cap.compute_seconds // count),
            risk="medium",
            source_refs=source_refs,
            hypothesis=BetHypothesis.model_validate(
                {
                    key: feature[key]
                    for key in (
                        "hypothesis",
                        "metric_id",
                        "threshold",
                        "direction",
                        "window_days",
                        "kill_criteria",
                    )
                }
            ),
        ).model_dump()
        for feature in plan["candidates"]
    ]
    return {
        "source": plan["source"],
        "metrics": metrics,
        "source_refs": source_refs,
        "opportunities": opportunities,
        "planning_calls": planning_calls,
        "company_evidence": {key: company_context[key] for key in ("assets", "repo", "domains")},
        "prior_review_count": len(history),
        "estimate_basis": "reviewable_equal_resource_slices_not_observed_costs",
    }


def _execute(task: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.employee_executor import execute_employee_task
    from modstore_server.platform_llm_scope import platform_llm_scope
    from modstore_server.strategic_portfolio_usage import portfolio_usage_scope

    with (
        platform_llm_scope(),
        portfolio_usage_scope(task["decision_id"], task["opportunity_id"], task["lease_token"]),
    ):
        return dict(
            execute_employee_task(
                task["employee_id"],
                task["task"],
                {
                    "strategic_decision_id": task["decision_id"],
                    "strategic_opportunity_id": task["opportunity_id"],
                    "idempotency_key": _action_id(task["decision_id"], task["opportunity_id"]),
                    "deadline_epoch": _date(task["deadline"]).timestamp(),
                    "allow_high_risk_real_run": False,
                    "suppress_handoff": True,
                    "suppress_employee_im": True,
                    "suppress_lifecycle_events": True,
                },
                user_id=task["owner_user_id"],
            )
        )


def _finish(task: dict[str, Any], result: dict[str, Any], elapsed: int) -> None:
    def apply(_row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any) -> None:
        saved = state["tasks"][task["opportunity_id"]]
        if saved["lease_token"] != task["lease_token"] or saved["status"] != "running":
            raise PortfolioError("execution completion does not own its lease")
        from modstore_server.cred_vault import redact
        from modstore_server.strategic_execution_receipts import evaluate_execution_receipt

        receipt = evaluate_execution_receipt(result)
        ok, reason = receipt.status == "completed", receipt.reason
        unknown_receipt = receipt.status == "unknown"
        if unknown_receipt:
            state.update(halted=True, stop_reason=reason)
        pending_execution = receipt.status == "pending"
        bound_worker = (
            pending_execution
            and saved.get("worker_binding")
            and result.get("worker_receipt_id") == saved["worker_binding"]["receipt_id"]
        )
        if pending_execution:
            ok, reason = False, "downstream_execution_receipt_pending"
            if not bound_worker:
                state.update(halted=True, stop_reason=reason)
        calls = list(saved["calls"].values())
        unknown_usage = any(call["status"] != "settled" for call in calls)
        if unknown_usage:
            state.update(halted=True, stop_reason="upstream_usage_unknown")
        if elapsed > saved["reservation"]["compute_seconds"]:
            state.update(halted=True, stop_reason="compute_budget_exceeded")
        saved.update(
            status=(
                "unknown"
                if unknown_usage or unknown_receipt or (pending_execution and not bound_worker)
                else "waiting" if bound_worker else "completed" if ok else "failed"
            ),
            completed_at=(
                None
                if bound_worker or unknown_usage or unknown_receipt or pending_execution
                else datetime.now(UTC).isoformat()
            ),
            compute_seconds=elapsed,
            actual_tokens=sum(call.get("actual_tokens", call["reserved_tokens"]) for call in calls),
            accrued_cost_cents=sum(
                call.get("accrued_cost_cents", call["reserved_cost_cents"]) for call in calls
            ),
            cost_basis="approved_tariff_accrual",
            result_sha256=digest(result),
            reason=reason[:500],
        )
        serialized = redact(_json(result))
        saved["execution_receipt"] = (
            json.loads(serialized)
            if len(serialized) <= 64_000
            else {"sha256": digest(result), "preview": serialized[:8000], "truncated": True}
        )
        failures = sum(item["status"] in {"failed", "unknown"} for item in state["tasks"].values())
        if failures >= proposal["limits"]["max_failures"] and not state.get("halted"):
            state.update(halted=True, stop_reason="failure_guardrail")
        action = session.execute(
            select(StrategicActionItem).where(
                StrategicActionItem.action_id
                == _action_id(task["decision_id"], task["opportunity_id"])
            )
        ).scalar_one()
        action.status = (
            "completed"
            if saved["status"] == "completed"
            else "in_progress" if saved["status"] == "waiting" else "blocked"
        )
        action.completed_at = (
            None if saved["status"] in {"waiting", "unknown"} else datetime.now(UTC)
        )
        action.updated_at = datetime.now(UTC)
        action.result_json, action.block_reason = _json(saved), "" if ok else reason[:500]

    mutate_portfolio(task["decision_id"], apply)


def execute_portfolio_worker(
    binding: dict[str, Any], *, owner_user_id: int, execute: Any
) -> dict[str, Any]:
    """Local durable queue adapter; remote executors need their own metered gateway."""
    from modstore_server.strategic_portfolio_usage import portfolio_worker_scope

    with portfolio_worker_scope(binding, owner_user_id=owner_user_id) as task:
        try:
            result = execute(task)
            if not isinstance(result, dict):
                result = {"status": "unknown", "receipt_error": "invalid worker receipt"}
        except RECOVERABLE_ERRORS as exc:
            result = {"status": "unknown", "receipt_error": type(exc).__name__}
        elapsed = max(1, math.ceil((datetime.now(UTC) - _date(task["started_at"])).total_seconds()))
        _finish(task, result, elapsed)
    return portfolio_status(binding["decision_id"], owner_user_id=owner_user_id)


def run_portfolio_cycle(
    decision_id: str, *, owner_user_id: int | None = None, max_tasks: int = 1
) -> dict[str, Any]:
    """Dispatch only durable, unexecuted approved tasks; never replay uncertain work."""
    if type(max_tasks) is not int or not 1 <= max_tasks <= 16:
        raise PortfolioError("max_tasks must be 1..16")
    plan_portfolio(decision_id, owner_user_id=owner_user_id)
    processed = 0
    for _ in range(max_tasks):
        task = _claim(decision_id, owner_user_id)
        if task is None:
            break
        started = time.monotonic()
        try:
            result = _execute(task)
            if not isinstance(result, dict):
                result = {"status": "unknown", "receipt_error": "invalid executor receipt"}
        except RECOVERABLE_ERRORS as exc:
            result = {"status": "unknown", "receipt_error": type(exc).__name__}
        _finish(task, result, max(1, math.ceil(time.monotonic() - started)))
        processed += 1
        if portfolio_status(decision_id)["halted"]:
            break
    return {"processed": processed, **portfolio_status(decision_id, owner_user_id=owner_user_id)}


def _execution_artifacts(value: Any, depth: int = 0) -> set[tuple[str, str]]:
    """Read structured delivery identities from the persisted executor receipt."""
    if depth > 6:
        return set()
    found: set[tuple[str, str]] = set()
    if isinstance(value, dict):
        artifact = value.get("artifact_id")
        evidence = value.get("evidence")
        sha = value.get("artifact_sha256") or (
            evidence.get("artifact_sha256") if isinstance(evidence, dict) else None
        )
        if (
            isinstance(artifact, str)
            and artifact
            and isinstance(sha, str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", sha)
        ):
            found.add((artifact, sha.lower()))
        for item in value.values():
            found.update(_execution_artifacts(item, depth + 1))
    elif isinstance(value, list):
        for item in value[:100]:
            found.update(_execution_artifacts(item, depth + 1))
    return found


def _business_outcome(
    status: dict[str, Any],
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    """Never attribute an unrelated platform payment or an unverified receipt."""
    from modstore_server.customer_value_classification import (
        amount_cents,
        classify_payment_order,
        parse_datetime,
    )
    from modstore_server.customer_value_payment_source import load_authoritative_payment_orders
    from modstore_server.db.customer_value import CustomerValueReceipt

    start, now = window_start or _date(status["started_at"]), window_end or datetime.now(UTC)
    source = load_authoritative_payment_orders(max(1, (datetime.now(UTC) - start).days + 1))
    if not (source.get("source_available") is True and source.get("source_authoritative") is True):
        return {
            "status": "unknown",
            "reason": "authoritative_payment_source_unavailable",
            "revenue_cents": None,
        }
    delivered: dict[str, set[tuple[str, str]]] = {}
    executed_since: dict[str, datetime] = {}
    missing_attribution = False
    for item in status["opportunities"]:
        task = status.get("tasks", {}).get(item["opportunity_id"], {})
        if task.get("status") != "completed":
            continue
        artifacts = _execution_artifacts(task.get("execution_receipt"))
        if item["customer_goal_ids"] and not artifacts:
            missing_attribution = True
        for goal in item["customer_goal_ids"]:
            if artifacts:
                delivered.setdefault(goal, set()).update(artifacts)
                task_start = _date(task["started_at"])
                executed_since[goal] = min(executed_since.get(goal, task_start), task_start)
    goal_ids = set(delivered)
    goals: dict[tuple[str, str, str], set[str]] = {}
    refunded: set[str] = set()
    with get_session_factory()() as session:
        receipts = (
            session.execute(
                select(CustomerValueReceipt).where(
                    CustomerValueReceipt.verification_status == "verified",
                    CustomerValueReceipt.customer_ref == f"paid-user:{status['owner_user_id']}",
                    CustomerValueReceipt.customer_goal_id.in_(goal_ids),
                    CustomerValueReceipt.receipt_kind.in_(("outcome", "acceptance")),
                    CustomerValueReceipt.occurred_at >= start,
                    CustomerValueReceipt.occurred_at <= now,
                )
            )
            .scalars()
            .all()
        )
        for receipt in receipts:
            if (
                receipt.customer_goal_id in goal_ids
                and receipt.environment in {"production", "prod"}
                and receipt.currency == "CNY"
                and receipt.occurred_at.replace(tzinfo=UTC)
                >= max(start, executed_since[str(receipt.customer_goal_id)])
                and receipt.receipt_kind in {"outcome", "acceptance"}
            ):
                if receipt.receipt_kind == "acceptance":
                    try:
                        evidence = json.loads(str(receipt.evidence_json) or "{}")
                    except (ValueError, TypeError):
                        continue
                    if (
                        not isinstance(evidence, dict)
                        or (
                            str(receipt.artifact_id),
                            str(evidence.get("artifact_sha256", "")).lower(),
                        )
                        not in delivered[str(receipt.customer_goal_id)]
                    ):
                        continue
                goals.setdefault(
                    (
                        str(receipt.order_no),
                        str(receipt.customer_goal_id),
                        str(receipt.customer_ref),
                    ),
                    set(),
                ).add(str(receipt.receipt_kind))
        matched_orders = {number for number, _goal, _customer in goals}
        refunded = set(
            session.execute(
                select(CustomerValueReceipt.order_no).where(
                    CustomerValueReceipt.order_no.in_(matched_orders),
                    CustomerValueReceipt.receipt_kind == "refund",
                    CustomerValueReceipt.verification_status == "verified",
                    CustomerValueReceipt.occurred_at <= now,
                )
            )
            .scalars()
            .all()
        )
    orders: dict[str, int] = {}
    for order in source.get("orders") or []:
        valid, _ = classify_payment_order(order, cutoff=start)
        order_no = str(order.get("out_trade_no") or order.get("order_no") or "")
        paid_at = parse_datetime(order.get("paid_at"))
        if (
            not valid
            or str(order.get("user_id")) != str(status["owner_user_id"])
            or order_no in refunded
            or not paid_at
            or paid_at > now
            or str(order.get("currency") or "CNY") != "CNY"
        ):
            continue
        if any(
            number == order_no
            and customer == f"paid-user:{order.get('user_id')}"
            and kinds == {"outcome", "acceptance"}
            for (number, _goal, customer), kinds in goals.items()
        ):
            orders[order_no] = amount_cents(order)
    return {
        "status": "unknown" if missing_attribution else "verified",
        "reason": "executed_delivery_attribution_missing" if missing_attribution else "",
        "source": source.get("source_owner"),
        "revenue_cents": None if missing_attribution else sum(orders.values()),
        "verified_attributed_cents": sum(orders.values()),
        "paid_order_count": len(orders),
        "order_refs_sha256": digest(sorted(orders)),
        "window_start": start.isoformat(),
        "window_end": now.isoformat(),
        "attribution": "same_owner_completed_task_artifact_and_verified_acceptance_with_order_outcome_not_incremental_causality",
    }


def review_portfolio(decision_id: str, *, owner_user_id: int | None = None) -> dict[str, Any]:
    from modstore_server.strategy_bets import REVENUE_METRIC, review_hypotheses

    status = portfolio_status(decision_id, owner_user_id=owner_user_id)
    if not status.get("started_at"):
        raise PortfolioError("portfolio has not started")
    outcome = _business_outcome(status)
    hypothesis_business = {}
    for item in status["opportunities"]:
        target, task = item.get("hypothesis"), status.get("tasks", {}).get(item["opportunity_id"])
        if (
            target
            and task
            and target["metric_id"] == REVENUE_METRIC
            and item["opportunity_id"] not in status.get("hypothesis_outcomes", {})
        ):
            start = _date(task["started_at"])
            end = start + timedelta(days=target["window_days"])
            if datetime.now(UTC) >= end:
                hypothesis_business[item["opportunity_id"]] = _business_outcome(
                    {**status, "opportunities": [item]}, window_start=start, window_end=end
                )

    def apply(
        _row: Any, proposal: dict[str, Any], state: dict[str, Any], _session: Any
    ) -> dict[str, Any]:
        hypotheses = review_hypotheses(proposal, state, hypothesis_business)
        tasks = list(state["tasks"].values())
        cost = sum(_consumed(item, "cost_cents") for item in tasks)
        known = all(
            item["status"] in {"completed", "failed"}
            and all(call["status"] == "settled" for call in item["calls"].values())
            for item in tasks
        )
        revenue = outcome.get("revenue_cents")
        elapsed = (datetime.now(UTC) - _date(state["started_at"])).total_seconds()
        mature = elapsed >= proposal["limits"]["observation_hours"] * 3600
        roi = (
            ((revenue - cost) * 10_000 // cost)
            if type(revenue) is int and cost > 0 and known
            else None
        )
        stop = ""
        if _date(proposal["limits"]["expires_at"]) <= datetime.now(UTC):
            stop = "authorization_expired"
        elif cost > proposal["limits"]["stop_loss_cents"] and (
            not mature
            or type(revenue) is not int
            or cost - revenue > proposal["limits"]["stop_loss_cents"]
        ):
            stop = "stop_loss_budget"
        elif mature and roi is not None and roi < proposal["limits"]["min_roi_bps"]:
            stop = "business_roi_guardrail"
        if stop:
            state.update(halted=True, stop_reason=stop)
        report = {
            "at": datetime.now(UTC).isoformat(),
            "business": outcome,
            "accrued_cost_cents": cost,
            "cost_basis": "approved_tariff_accrual_not_supplier_invoice",
            "usage_complete": known,
            "observation_complete": mature,
            "attributed_roi_bps": roi,
            "hypotheses": hypotheses,
            "decision": (
                "stop"
                if state["halted"]
                else (
                    "wait_for_measurement"
                    if not mature or not known or revenue is None
                    else "reallocate_within_approval"
                )
            ),
            "stop_reason": state.get("stop_reason", ""),
        }
        state["reviews"] = [*state.get("reviews", [])[-89:], report]
        return report

    report = mutate_portfolio(decision_id, apply, owner_user_id=owner_user_id)
    if report["decision"] == "reallocate_within_approval":
        report["reallocation"] = reallocate_portfolio(decision_id, owner_user_id=owner_user_id)
    return report


def reallocate_portfolio(decision_id: str, *, owner_user_id: int | None = None) -> dict[str, Any]:
    """Reuse released resources for unexecuted approved opportunities only."""
    from modstore_server.strategic_portfolio import optimize_portfolio

    def apply(
        row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any
    ) -> dict[str, Any]:
        require_authorization(row, proposal, state)
        latest = (state.get("reviews") or [{}])[-1]
        if latest.get("decision") != "reallocate_within_approval":
            raise PortfolioError("reallocation requires a completed outcome review")
        tasks = state["tasks"]
        if any(task["status"] in {"running", "waiting", "unknown"} for task in tasks.values()):
            return {"status": "waiting_for_execution_receipts"}
        remaining = {
            **proposal["limits"],
            **{
                key: max(
                    0,
                    proposal["limits"][key] - sum(_consumed(task, key) for task in tasks.values()),
                )
                for key in RESOURCES
            },
        }
        remaining["stop_loss_cents"] = min(remaining["stop_loss_cents"], remaining["cost_cents"])
        candidates = []
        by_id = {item["opportunity_id"]: item for item in proposal["opportunities"]}
        for item in by_id.values():
            if item["opportunity_id"] in tasks or any(
                tasks.get(dep, {}).get("status") in {"failed", "unknown"}
                for dep in item["depends_on"]
            ):
                continue
            history = [
                task
                for key, task in tasks.items()
                if by_id[key]["employee_id"] == item["employee_id"]
            ]
            succeeded = sum(task["status"] == "completed" for task in history)
            candidates.append(
                {
                    **item,
                    "depends_on": [dep for dep in item["depends_on"] if dep not in tasks],
                    "confidence_bps": item["confidence_bps"]
                    * (succeeded + 1)
                    // (len(history) + 1),
                }
            )
        # Exclude descendants whose prerequisites were eliminated by outcomes.
        while True:
            identifiers = {item["opportunity_id"] for item in candidates}
            valid = [item for item in candidates if set(item["depends_on"]).issubset(identifiers)]
            if len(valid) == len(candidates):
                break
            candidates = valid
        if not candidates or remaining["compute_seconds"] <= 0:
            return {"status": "no_remaining_approved_work"}
        allocation = optimize_portfolio(candidates, remaining)
        for key in allocation["selected"]:
            action_id = _action_id(decision_id, key)
            action = session.execute(
                select(StrategicActionItem).where(StrategicActionItem.action_id == action_id)
            ).scalar_one_or_none()
            if action is None:
                session.add(
                    StrategicActionItem(
                        action_id=action_id,
                        decision_id=decision_id,
                        description=by_id[key]["task"],
                        assigned_to=by_id[key]["employee_id"],
                        status="pending",
                        due_at=_date(proposal["limits"]["expires_at"]),
                        result_json=_json({"schema": SCHEMA, "opportunity_id": key}),
                    )
                )
        state["plan"] = {
            **allocation,
            "selected": [*tasks, *allocation["selected"]],
            "reallocated_at": datetime.now(UTC).isoformat(),
            "remaining_limits": remaining,
        }
        return allocation

    return mutate_portfolio(decision_id, apply, owner_user_id=owner_user_id)
