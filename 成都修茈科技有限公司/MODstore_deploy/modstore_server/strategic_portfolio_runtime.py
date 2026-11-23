"""Strategy execution, attributable customer outcomes and bounded replanning."""

from __future__ import annotations

import asyncio
import json
import math
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
        from modstore_server.strategic_company_planner import claim_candidates

        require_authorization(row, proposal, state, session=session)
        tasks = state["tasks"]
        now = datetime.now(UTC)
        running = [task for task in tasks.values() if task["status"] in {"running", "waiting"}]
        if any(_date(task["deadline"]) <= now for task in running):
            state.update(halted=True, stop_reason="execution_outcome_unknown_after_deadline")
            return None
        if len(running) >= proposal["limits"]["max_parallel"]:
            return None
        opportunities = {item["opportunity_id"]: item for item in proposal["opportunities"]}
        selected = state["plan"]["selected"]
        company_selected = claim_candidates(session, decision_id, proposal, state)
        if company_selected is not None:
            selected = company_selected
            planned = list(dict.fromkeys([*tasks, *selected]))
            state["plan"].update(
                selected=planned,
                deferred=[key for key in opportunities if key not in planned],
                allocation={
                    field: sum(opportunities[key][field] for key in selected) for field in RESOURCES
                },
                company_selection_sha256=state["company_selection"].get("selection_sha256"),
            )
        for key in selected:
            opportunity = opportunities[key]
            if key in tasks or any(
                tasks.get(dep, {}).get("status") != "completed" for dep in opportunity["depends_on"]
            ):
                continue
            reservation = {field: opportunity[field] for field in RESOURCES}
            from modstore_server.xiaoc_life_store import (
                LifePolicyError,
                require_life_task_capacity,
                require_operating_goal_admission,
            )

            try:
                require_operating_goal_admission(decision_id, proposal)
                require_life_task_capacity(proposal, reservation["tokens"])
            except LifePolicyError as exc:
                raise PortfolioError(str(exc)) from exc
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
            ).scalar_one_or_none()
            if action is None:
                if company_selected is None:
                    raise PortfolioError("approved portfolio action is missing")
                # The approval covers every frozen opportunity, including one
                # deferred by the original local optimizer. Admit its action in
                # the same transaction as the task and company reservation.
                action = StrategicActionItem(
                    action_id=_action_id(decision_id, key),
                    decision_id=decision_id,
                    description=opportunity["task"],
                    assigned_to=opportunity["employee_id"],
                    due_at=_date(proposal["limits"]["expires_at"]),
                    created_at=now,
                )
                session.add(action)
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
    input_data: dict[str, Any] | None = None,
    market_research: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reuse the existing strategic planner with account-scoped live inputs."""
    from sqlalchemy import func

    from modstore_server import strategy_planner
    from modstore_server.customer_value_classification import (
        amount_cents,
        classify_payment_order,
        parse_datetime,
    )
    from modstore_server.customer_value_payment_source import (
        load_authoritative_payment_orders,
    )
    from modstore_server.db.customer_value import CustomerValueReceipt
    from modstore_server.db.llm_chat import LlmCallLog
    from modstore_server.models_cs import CustomerServiceTicket
    from modstore_server.services.llm import (
        chat_dispatch_via_platform_only,
        resolve_platform_bench_llm,
    )
    from modstore_server.strategic_execution_contract import (
        freeze_execution,
        validate_input,
    )
    from modstore_server.strategic_market_research import bind_market_candidate, discover_market
    from modstore_server.strategic_portfolio import Opportunity, PortfolioLimits
    from modstore_server.strategic_portfolio_usage import (
        planning_admission,
        planning_usage_scope,
    )
    from modstore_server.task_router import _load_all_employee_profiles

    if type(owner_user_id) is not int or owner_user_id <= 0:
        raise PortfolioError("owner is required for planning context")
    from modstore_server.strategic_company_resources import bind_limits

    cap = PortfolioLimits.model_validate(
        bind_limits(owner_user_id, PortfolioLimits.model_validate(limits).model_dump())
    )
    approved_input = validate_input(input_data or {})
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        tickets = (
            session.execute(
                select(CustomerServiceTicket)
                .where(
                    CustomerServiceTicket.user_id == owner_user_id,
                    CustomerServiceTicket.status != "closed",
                    CustomerServiceTicket.created_at <= now,
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
                LlmCallLog.created_at <= now,
            )
        ).one()
        customer_goals = list(
            session.scalars(
                select(CustomerValueReceipt.customer_goal_id)
                .where(
                    CustomerValueReceipt.customer_ref == f"paid-user:{owner_user_id}",
                    CustomerValueReceipt.receipt_kind == "goal",
                    CustomerValueReceipt.verification_status == "verified",
                    CustomerValueReceipt.occurred_at <= now,
                )
                .distinct()
                .limit(32)
            )
        )
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
        and (paid_at := parse_datetime(order.get("paid_at"))) is not None
        and paid_at <= now
        and str(order.get("currency") or "CNY") == "CNY"
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
    market = await discover_market(
        market_research, owner_user_id=owner_user_id, employees=employees
    )

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
            admission = await planning_admission(provider, model, owner_user_id=owner_user_id)
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
        "customer_goal_ids": customer_goals,
        "market": market,
    }
    plan = await strategy_planner.generate_candidates(
        context, chat=PlatformPlanner() if use_llm else None
    )
    default_employee = "daily-orchestrator" if "daily-orchestrator" in employees else employees[0]
    count = max(1, len(plan["candidates"]))
    opportunities, rejected = [], []
    for feature in plan["candidates"]:
        try:
            market_binding = bind_market_candidate(feature, market)
        except PortfolioError as exc:
            rejected.append({"title": feature["title"], "reason": str(exc)})
            continue
        bindings = market_binding.get("customer_goal_bindings", [])
        observed_goals = {*customer_goals, *[row["customer_goal_id"] for row in bindings]}
        goals = feature.get("customer_goal_ids") or []
        if not isinstance(goals, list) or not all(
            isinstance(goal_id, str) and goal_id in observed_goals for goal_id in goals
        ):
            rejected.append(
                {
                    "title": feature["title"],
                    "reason": "customer_goal_not_owned_or_observed",
                }
            )
            continue
        if (
            feature["metric_id"]
            in {
                strategy_planner.strategy_bets.REVENUE_METRIC,
                strategy_planner.strategy_bets.CUSTOMER_ACCEPTANCE_METRIC,
            }
            and not goals
        ):
            rejected.append(
                {
                    "title": feature["title"],
                    "reason": "business_hypothesis_requires_customer_goal_binding",
                }
            )
            continue
        candidate = Opportunity(
            opportunity_id="op-"
            + digest([goal, feature["title"], source_refs, market_binding])[:20],
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
            source_refs=[*source_refs, *market_binding.get("source_refs", [])],
            customer_goal_ids=goals,
            customer_goal_bindings=bindings,
            input_data={
                **approved_input,
                **(
                    {"market_evidence": market_binding["market_evidence"]} if market_binding else {}
                ),
            },
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
        try:
            opportunities.append(freeze_execution(owner_user_id, candidate))
        except RECOVERABLE_ERRORS as exc:
            rejected.append({"title": feature["title"], "reason": str(exc)[:500]})
    return {
        "source": plan["source"],
        "metrics": metrics,
        "source_refs": source_refs,
        "opportunities": opportunities,
        "rejected_candidates": rejected,
        "planning_calls": planning_calls,
        "company_evidence": {
            **{key: company_context[key] for key in ("assets", "repo", "domains")},
            "market": market,
        },
        "prior_review_count": len(history),
        "estimate_basis": "reviewable_equal_resource_slices_not_observed_costs",
    }


def _execute(task: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.employee_executor import execute_employee_task
    from modstore_server.platform_llm_scope import platform_llm_scope
    from modstore_server.strategic_execution_contract import execution_payload
    from modstore_server.strategic_portfolio_usage import portfolio_usage_scope

    with (
        platform_llm_scope(),
        portfolio_usage_scope(task["decision_id"], task["opportunity_id"], task["lease_token"]),
    ):
        if (task.get("input_data") or {}).get("remote_execution"):
            from modstore_server.strategic_remote_bridge import dispatch_report
            from modstore_server.strategic_workspace_bridge import KIND, attach_workspace

            if task["input_data"]["remote_execution"].get("kind") == "original_pr_repair":
                from modstore_server.para_github_repair import (
                    attach_workspace as attach_original_pr,
                )

                return attach_original_pr(task)
            if task["input_data"]["remote_execution"].get("kind") == KIND:
                return attach_workspace(task)
            return dispatch_report(task)
        return dict(
            execute_employee_task(
                task["employee_id"],
                task["task"],
                execution_payload(task),
                user_id=task["owner_user_id"],
            )
        )


def _finish(
    task: dict[str, Any],
    result: dict[str, Any],
    elapsed: int,
    *,
    remote_receipt: tuple[str, str] | None = None,
) -> None:
    from modstore_server.strategic_customer_outcomes import attach_local_delivery_artifacts

    result = attach_local_delivery_artifacts(task, result)

    def apply(_row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any) -> None:
        saved = state["tasks"][task["opportunity_id"]]
        prior_stop = (state.get("halted"), state.get("stop_reason"))
        remote_record = None
        allowed_statuses = {"running"}
        if remote_receipt is not None:
            from modstore_server.strategic_remote_bridge import KIND, _row, _snapshot
            from modstore_server.strategic_workspace_bridge import KIND as WORKSPACE_KIND

            remote_record = _row(session, remote_receipt[0])
            binding = saved.get("worker_binding") or {}
            if (
                binding.get("adapter") not in {KIND, WORKSPACE_KIND, "original_pr_repair"}
                or binding.get("receipt_id") != remote_receipt[0]
            ):
                raise PortfolioError("remote completion does not own its worker binding")
            original_pr = binding.get("adapter") == "original_pr_repair"
            if remote_record.state in {"execution_completed", "failed"} and not (
                original_pr
                and remote_record.state == "execution_completed"
                and saved["status"] == "waiting"
            ):
                return
            if digest(_snapshot(remote_record, saved)) != remote_receipt[1]:
                raise PortfolioError("remote completion changed during artifact readback")
            if binding.get("adapter") == WORKSPACE_KIND:
                from modstore_server.strategic_workspace_receipts import validate_terminal

                validate_terminal(session, json.loads(remote_record.request_json), result)
            elif binding.get("adapter") == "original_pr_repair":
                from modstore_server.strategic_remote_bridge import _request
                from modstore_server.strategic_workspace_receipts import validate_terminal

                if result.get("remote_receipt", {}).get("stage") == "not_dispatched" and (
                    saved["calls"]
                    or any(
                        saved.get("remote_state", {}).get(key)
                        for key in ("phases", "phase", "model_grant", "task_grants")
                    )
                ):
                    raise PortfolioError(
                        "original PR has admitted model work pending reconciliation"
                    )
                validate_terminal(session, _request(remote_record), result)
            allowed_statuses.add("waiting")
        if saved["lease_token"] != task["lease_token"] or saved["status"] not in allowed_statuses:
            raise PortfolioError("execution completion does not own its lease")
        calls = list(saved["calls"].values())
        unknown_usage = any(call["status"] != "settled" for call in calls)
        if remote_record is not None and unknown_usage:
            # The model reader and native receipt reader can race. Check inside
            # this CAS, before changing the original worker or remote terminal,
            # so accounting can later finish this same execution without replay.
            if not state.get("halted"):
                state.update(halted=True, stop_reason="upstream_usage_unknown")
            return
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
        if remote_record is not None:
            # The original task and its native transport acknowledgement commit
            # together, so a restart cannot replay or overwrite a terminal report.
            if binding.get("adapter") == "original_pr_repair":
                from modstore_server.strategic_workspace_receipts import project_pr_receipt

                project_pr_receipt(remote_record, saved, result)
            else:
                remote_record.state = (
                    "execution_completed" if saved["status"] == "completed" else "failed"
                )
            remote_record.updated_at = time.time()
            if prior_stop[0] and prior_stop[1] != "upstream_usage_unknown":
                state.update(halted=True, stop_reason=prior_stop[1])
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
    from modstore_server.strategic_remote_receipts import reconcile_portfolio

    reconcile_portfolio(decision_id, owner_user_id=owner_user_id)
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


def _business_outcome(
    status: dict[str, Any],
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    """Attribute payments only to the exact approved customer and completed artifact."""
    from modstore_server.customer_value_classification import (
        amount_cents,
        classify_payment_order,
        parse_datetime,
    )
    from modstore_server.customer_value_payment_source import load_authoritative_payment_orders
    from modstore_server.strategic_customer_outcomes import (
        VERIFIED_DELIVERY_ATTRIBUTION,
        customer_delivery_evidence,
    )

    start, now = window_start or _date(status["started_at"]), window_end or datetime.now(UTC)
    source = load_authoritative_payment_orders(max(1, (datetime.now(UTC) - start).days + 1))
    if not (source.get("source_available") is True and source.get("source_authoritative") is True):
        return {
            "status": "unknown",
            "reason": "authoritative_payment_source_unavailable",
            "revenue_cents": None,
        }
    evidence = customer_delivery_evidence(status, start=start, end=now)
    orders: dict[str, int] = {}
    for order in source.get("orders") or []:
        valid, _ = classify_payment_order(order, cutoff=start)
        order_no = str(order.get("out_trade_no") or order.get("order_no") or "")
        paid_at = parse_datetime(order.get("paid_at"))
        customer_ref = f"paid-user:{order.get('user_id')}"
        if (
            valid
            and paid_at
            and paid_at <= now
            and str(order.get("currency") or "CNY") == "CNY"
            and (customer_ref, order_no) in evidence["accepted_orders"]
        ):
            orders[order_no] = amount_cents(order)
    missing = evidence["missing_attribution"]
    return {
        "status": "unknown" if missing else "verified",
        "reason": "executed_delivery_attribution_missing" if missing else "",
        "source": source.get("source_owner"),
        "revenue_cents": None if missing else sum(orders.values()),
        "verified_attributed_cents": sum(orders.values()),
        "paid_order_count": len(orders),
        "order_refs_sha256": digest(
            {"orders": orders, "customer_evidence": evidence["evidence_sha256"]}
        ),
        "window_start": start.isoformat(),
        "window_end": now.isoformat(),
        "attribution": VERIFIED_DELIVERY_ATTRIBUTION,
    }


def review_portfolio(decision_id: str, *, owner_user_id: int | None = None) -> dict[str, Any]:
    from modstore_server.strategic_customer_outcomes import customer_acceptance_outcome
    from modstore_server.strategy_bets import (
        CUSTOMER_ACCEPTANCE_METRIC,
        REVENUE_METRIC,
        review_hypotheses,
    )

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
            and target["metric_id"] in {REVENUE_METRIC, CUSTOMER_ACCEPTANCE_METRIC}
            and item["opportunity_id"] not in status.get("hypothesis_outcomes", {})
        ):
            start = _date(task["started_at"])
            end = start + timedelta(days=target["window_days"])
            if datetime.now(UTC) >= end:
                observe = (
                    customer_acceptance_outcome
                    if target["metric_id"] == CUSTOMER_ACCEPTANCE_METRIC
                    else _business_outcome
                )
                hypothesis_business[item["opportunity_id"]] = observe(
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
        # Pruning is monotone: each non-stable pass removes at least one
        # candidate. Bound passes to the original candidate count so malformed
        # prerequisite graphs can never hold the execution worker indefinitely.
        for _ in range(len(candidates)):
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
