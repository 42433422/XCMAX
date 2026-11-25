"""Management XiaoC cognition on the existing LangGraph, model and task ports.

The SQL life store owns leases, policy revisions, daily reservations and durable
experiences. A bounded graph never replays an uncertain paid call after restart.
Existing strategic approvals continue to own all employee execution.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict, TypeVar

from modstore_server.operational_errors import BOUNDARY_ERRORS
from modstore_server.xiaoc_goal_management import (
    candidate_gate,
    discover_goal_candidate,
    resumable_operating_candidate,
    portfolio_goal_closed,
    project_goal_steps,
)
from modstore_server.xiaoc_life_cognition import (
    CognitionContextError,
    cognition_messages,
    cognition_prompt_bound,
    cognitive_review_facts,
    feedback_facts,
    goal_review_facts,
    goal_review_projection,
    parse_decision,
    portfolio_feedback,
    reflection_facts,
    reflection_receipt,
)
from modstore_server.xiaoc_life_native_checkpoint import (
    native_life_checkpointer,
    native_thread_config,
)
from modstore_server.xiaoc_life_telemetry import life_operation

T = TypeVar("T")


class LifeBlocked(ValueError):
    """An unmet execution precondition, reported without invented activity."""


BLOCKED_SUMMARIES = {
    "life_cycle_prompt_budget_exhausted": "本轮预算不足以容纳观察上下文，尚未调用模型；请核对每日额度与本轮可用预算。",
    "platform_model_not_configured": "尚未配置可用的平台模型，本轮未调用模型。",
    "platform_quota_unknown_or_exhausted": "平台模型额度未知或已耗尽，本轮未调用模型。",
    "research_not_configured": "尚未配置自托管 SearXNG，兴趣探索等待研究来源配置。",
    "model_usage_unknown": "模型调用用量尚未核实，已保留预算等待原回执，本轮不采纳模型建议。",
    "portfolio_task_exceeds_life_cycle_budget": "原批准任务所需令牌超过本轮可用预算，尚未执行该任务。",
    "life_policy_changed_or_lease_lost": "全局授权已改变或本轮租约已失效，已停止后续行动并保留已有回执。",
    "awaiting_evidence_based_interest": "尚无带来源的学习兴趣，本轮等待真实观察。",
    "research_returned_no_sources": "本轮研究没有返回可用来源，未据此生成新结论。",
    "no_observed_context": "本轮没有可用的企业观察来源，未调用模型。",
    "model_returned_no_usable_result": "模型未返回可用结果，已保存实际调用用量。",
}


class LifeCycle(TypedDict, total=False):
    facts: list[dict[str, Any]]
    decision: dict[str, Any]
    portfolio: dict[str, Any]
    evolution: dict[str, Any]
    goals: list[dict[str, Any]]
    discovered_goals: list[dict[str, Any]]
    interests: list[dict[str, Any]]
    self_model: dict[str, Any]
    summary: str
    status: str
    model_receipt: dict[str, Any]


def _store():
    from modstore_server import xiaoc_life_store

    return xiaoc_life_store


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _fact(kind: str, value: Any, **extra: Any) -> dict[str, Any]:
    return {
        "ref": f"{kind}:{_digest(value)[:24]}",
        "text": json.dumps(value, ensure_ascii=False, default=str),
        **extra,
    }


def _domain_order(state: dict[str, Any]) -> list[str]:
    """Bounded background domains; active enterprise work takes precedence."""
    level = int(state.get("level") or 1)
    if state.get("paused") or level < 4:
        return []
    events = [row for row in reversed(state.get("events", [])) if isinstance(row, dict)]
    domains = ["enterprise"]
    if (
        level >= 5
        and state.get("interests")
        and state.get("policy", {}).get("exploration_percent", 0) > 0
    ):
        domains.insert(0, "exploration")
    if level >= 6 and len(events) >= 3:
        domains.insert(0, "reflection")
    # Prefer domains least recently visited; no repeated busy loop when a lane
    # has no allowance. SQL independently checks the current domain allocation.
    last = {row.get("domain", row.get("kind")): index for index, row in enumerate(events)}
    domains.sort(key=lambda domain: last.get(domain, -1))
    if any(
        isinstance(goal, dict)
        and goal.get("decision_id")
        and goal.get("domain", "enterprise") == "enterprise"
        and goal.get("status") in {"approved", "active", "executing"}
        for goal in state.get("goals", [])
    ):
        domains.remove("enterprise")
        domains.insert(0, "enterprise")
    return domains


def _ready_portfolio_tasks(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Bound a life reservation; the real claim still verifies and admits work."""
    from modstore_server.strategic_portfolio import RESOURCES, _date, optimize_portfolio
    from modstore_server.strategic_portfolio_runtime import _consumed

    tasks, limits = record.get("tasks", {}), record.get("limits", {})
    opportunities = {row["opportunity_id"]: row for row in record["opportunities"]}
    company = bool(limits.get("company_budget_id"))
    remaining = {}
    if company:
        running = [task for task in tasks.values() if task["status"] in {"running", "waiting"}]
        if (
            record.get("halted")
            or record["status"] not in {"approved", "executing"}
            or _date(limits["expires_at"]) <= datetime.now(UTC)
            or len(running) >= limits["max_parallel"]
            or any(_date(task["deadline"]) <= datetime.now(UTC) for task in running)
            or any(task["status"] == "unknown" for task in tasks.values())
        ):
            return []
        remaining = {
            key: max(0, limits[key] - sum(_consumed(task, key) for task in tasks.values()))
            for key in RESOURCES
        }
        selected = list(opportunities)
    else:
        plan = record.get("plan") or optimize_portfolio(record["opportunities"], limits)
        selected = plan["selected"]
    return [
        row
        for key in selected
        if key not in tasks
        and (row := opportunities[key])
        and all(tasks.get(dep, {}).get("status") == "completed" for dep in row["depends_on"])
        and (
            not company
            or row["risk"] != "high"
            and all(row[resource] <= remaining[resource] for resource in RESOURCES)
        )
    ]


def _goals_in_turn(state: dict[str, Any], domain: str) -> list[dict[str, Any]]:
    """Rotate original bindings using SQL state, including zero-progress visits."""
    goals = [
        goal
        for goal in state.get("goals", [])
        if isinstance(goal, dict)
        and goal.get("decision_id")
        and goal.get("domain", "enterprise") == domain
    ]
    cursor = state.get("goal_cursors", {}).get(domain)
    index = next((i + 1 for i, goal in enumerate(goals) if goal.get("id") == cursor), 0)
    return goals[index:] + goals[:index]


def _cycle_reservation(state: dict[str, Any], domain: str) -> int:
    """Cover any ready company choice; the store still clamps each approved lane."""
    from modstore_server.strategic_portfolio import PortfolioError, portfolio_status

    owner = state.get("owner_user_id")
    if type(owner) is not int or owner <= 0:
        return 32768
    for goal in _goals_in_turn(state, domain):
        if goal.get("status") in {"completed", "failed", "stopped"}:
            continue
        try:
            record = portfolio_status(goal["decision_id"], owner_user_id=owner)
        except PortfolioError:
            continue
        if record["status"] not in {"approved", "executing"} or portfolio_goal_closed(
            record, now=datetime.now(UTC)
        ):
            continue
        ready = _ready_portfolio_tasks(record)
        company = bool(record.get("limits", {}).get("company_budget_id"))
        if (
            goal.get("next_review_at")
            and datetime.fromisoformat(goal["next_review_at"]) > datetime.now(UTC)
            and not (company and ready)
        ):
            continue
        if ready:
            requested = (
                max(int(item["tokens"]) for item in ready) if company else int(ready[0]["tokens"])
            )
            return min(1_000_000, requested)
        return 0  # An existing completed execution needs only receipt/outcome reads.
    if domain == "reflection" and any(
        goal.get("retort_request_id")
        and not goal.get("decision_id")
        and goal.get("status") == "awaiting_engineering_budget"
        for goal in state.get("goals", [])
    ):
        return 0  # Reading the original approval into a proposal makes no model call.
    return 32768


class CyclePorts:
    def __init__(self, claim: dict[str, Any]):
        self.claim = claim
        self.state = claim["state"]
        self.domain = claim["domain"]
        self.actual_tokens: int | None = 0
        self.model = ""
        self.evidence: list[str] = []
        self.details: dict[str, Any] = {}
        self.pending_writes: set[asyncio.Task[Any]] = set()
        self.portfolio_started = False

    async def write_in_thread(self, function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        job = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        self.pending_writes.add(job)
        try:
            return await asyncio.shield(job)
        finally:
            if job.done():
                self.pending_writes.discard(job)
                if not job.cancelled():
                    job.exception()

    async def drain_writes(self) -> None:
        # Cancelling the graph does not stop a running thread. Keep the cycle
        # lock until those writes can no longer race a takeover or settlement.
        cancelled = False
        while self.pending_writes:
            try:
                await asyncio.wait(self.pending_writes)
            except asyncio.CancelledError:
                cancelled = True
            for job in tuple(self.pending_writes):
                if job.done():
                    self.pending_writes.remove(job)
                    if not job.cancelled():
                        job.exception()
        if cancelled:
            raise asyncio.CancelledError

    def active(self) -> None:
        if not _store().cycle_active(self.claim):
            raise LifeBlocked("life_policy_changed_or_lease_lost")

    def approved_portfolio(self) -> dict[str, Any] | None:
        from modstore_server.strategic_portfolio import PortfolioError, portfolio_status

        for goal in _goals_in_turn(self.state, self.domain):
            if goal.get("status") in {"completed", "failed", "stopped"}:
                continue
            try:
                status = portfolio_status(
                    goal["decision_id"], owner_user_id=self.claim["owner_user_id"]
                )
            except PortfolioError:
                continue
            if (
                goal.get("next_review_at")
                and datetime.fromisoformat(goal["next_review_at"]) > datetime.now(UTC)
                and not (
                    status.get("limits", {}).get("company_budget_id")
                    and _ready_portfolio_tasks(status)
                )
            ):
                continue
            if status["status"] in {"approved", "executing"} and not portfolio_goal_closed(
                status, now=datetime.now(UTC)
            ):
                return {"goal": goal, "snapshot": status}
        return None

    async def observe(self, _state: LifeCycle) -> LifeCycle:
        self.active()
        if self.domain == "reflection" and self.state["level"] >= 6:
            from modstore_server.xiaoc_life_world import read_samples

            self.details["world_observations"] = await asyncio.to_thread(
                read_samples, datetime.now(UTC)
            )
            self.active()
        portfolio = self.approved_portfolio()
        if portfolio is not None:
            self.details["portfolio_selection"] = {
                "goal_id": portfolio["goal"]["id"],
                "decision_id": portfolio["goal"]["decision_id"],
            }
            return {"portfolio": portfolio, "facts": []}
        from modstore_server import xiaoc_life_evolution as evolution

        pending = evolution.pending_budget(self.state, self.domain)
        if pending is not None:
            return {"evolution": pending, "facts": []}
        from modstore_server.strategy_planner import collect_context

        context = await self.write_in_thread(collect_context)
        if self.domain == "enterprise":
            now = datetime.now(UTC)
            candidate = resumable_operating_candidate(
                context, self.state, self.claim["owner_user_id"], now=now
            )
            if candidate is None:
                candidate = discover_goal_candidate(
                    context, self.state, self.claim["owner_user_id"], now=now
                )
            if candidate is not None:
                goal, fact = candidate
                self.evidence = [fact["ref"]]
                self.details["sources"] = [fact]
                return {"facts": [fact], "discovered_goals": [goal]}
        facts = feedback_facts(self.state) + evolution.feedback_facts(self.state)
        facts.extend(cognitive_review_facts(self.state))
        # Keep pending comparisons visible to reviewers, not to cognition.
        facts.extend(
            row
            for row in self.state.get("experience_review_facts", [])
            if isinstance(row, dict)
            and isinstance(row.get("reviewed_experience"), dict)
            and "experience_candidate" not in row
        )
        facts.extend(reflection_facts(self.state))
        facts.extend(goal_review_facts(self.state))
        if self.domain == "reflection" and self.state["level"] >= 6:
            from modstore_server.xiaoc_life_world import review_projection

            try:
                projection = review_projection(
                    self.state.get("world_review"), self.claim["owner_user_id"]
                )
            except ValueError:
                self.details["world_review_error"] = "invalid_persisted_review"
                projection = {}
            for metric, item in projection.items():
                forecast = {"metric_id": metric, **item}
                facts.append(_fact("world-review", forecast, world_forecast=forecast))
        for key in ("customer_value", "assets", "repo", "domains"):
            value = context.get(key)
            if isinstance(value, dict):
                # No raw customer text, account-private memory or local path is
                # copied into the shared persona or sent as a public query.
                if key == "customer_value":
                    value = {
                        name: value.get(name)
                        for name in (
                            "status",
                            "source_owner",
                            "observed_at",
                            "window_days",
                            "value_ledger_ready",
                            "interpretation",
                            "desktop_release_source_available",
                        )
                        if name in value
                    }
                    original = context[key]
                    if value.get("status") == "ok":
                        payments = original.get("provider_payment_breakdown_cents")
                        if (
                            isinstance(payments, dict)
                            and set(payments) == {"wallet_topup", "product_service", "other"}
                            and all(
                                type(amount) is int and amount >= 0 for amount in payments.values()
                            )
                            and sum(payments.values()) == original.get("verified_paid_amount_cents")
                        ):
                            facts.insert(
                                0,
                                _fact(
                                    "company:provider_payments",
                                    {
                                        "source": value.get("source_owner"),
                                        "as_of": value.get("observed_at"),
                                        "window_days": value.get("window_days"),
                                        "currency": "CNY",
                                        "wallet_topup_paid_cents": payments["wallet_topup"],
                                        "product_service_paid_cents": payments["product_service"],
                                        "other_paid_cents": payments["other"],
                                    },
                                ),
                            )
                        for name in (
                            "verified_paid_count",
                            "verified_paid_amount_cents",
                            "customer_goal_count",
                            "paid_delivery_count",
                            "paid_acceptance_count",
                            "complete_customer_count",
                        ):
                            if type(original.get(name)) is int and original[name] >= 0:
                                value[name] = original[name]
                        for name in ("six_stage_counts", "lifecycle_gaps"):
                            value[name] = {
                                stage: count
                                for stage, count in original.get(name, {}).items()
                                if stage
                                in {
                                    "payment",
                                    "installation",
                                    "first_use",
                                    "outcome",
                                    "acceptance",
                                    "reuse",
                                    "sequence",
                                    "enterprise_subject",
                                }
                                and type(count) is int
                                and count >= 0
                            }
                if key == "domains":
                    value = {
                        "status": value.get("status"),
                        "audited_at": value.get("audited_at"),
                        "domains": [
                            {k: row.get(k) for k in ("domain_id", "status", "audited_at")}
                            for row in value.get("domains", [])[:18]
                            if isinstance(row, dict)
                        ],
                        "interpretation": "historical_requires_revalidation",
                    }
                facts.append(_fact("company:" + key, value))
        for event in self.state.get("events", [])[:4]:
            if (
                isinstance(event, dict)
                and event.get("summary")
                and event.get("kind") not in ("experience_candidate", "experience_review")
                and (event.get("details") or {}).get("owner_user_id")
                == self.state.get("owner_user_id")
            ):
                facts.append(
                    _fact(
                        "historical_life_event",
                        {k: event.get(k) for k in ("id", "cycle_id", "status", "summary")},
                    )
                )
        if self.domain == "exploration":
            facts = await self.research() + facts
        if not facts:
            raise LifeBlocked("no_observed_context")
        from modstore_server.xiaoc_self_metrics import with_cycle_receipts
        from modstore_server.xiaoc_self_model import cognition_projection, employee_preflight

        self_snapshot = await asyncio.to_thread(with_cycle_receipts, self.state)
        self.active()
        projection = cognition_projection(self_snapshot)
        employee = self.state.get("policy", {}).get("employee_id")
        if employee:
            preflight = await asyncio.to_thread(
                employee_preflight, employee, self.claim["owner_user_id"]
            )
            self.active()
            projection["configured_employee"] = preflight["status"]
        # Preserve the original observed context requirement and first evidence.
        facts.insert(1, _fact("functional_self", projection, functional_self_projection=True))
        self.evidence = [row["ref"] for row in facts]
        self.details["sources"] = facts
        return {"facts": facts}

    async def research(self) -> list[dict[str, Any]]:
        from modstore_server.research_tools import searxng_instance_url, searxng_search
        from modstore_server.xiaoc_world_evidence import public_source_observation

        if not searxng_instance_url():
            raise LifeBlocked("research_not_configured")
        interests = [
            row
            for row in self.state.get("interests", [])
            if isinstance(row, dict) and row.get("topic") and row.get("evidence_refs")
        ]
        if not interests:
            raise LifeBlocked("awaiting_evidence_based_interest")
        # Rotate existing evidence-linked interests without manufacturing a
        # personality or exposing private chat contents to a search engine.
        past = [
            event
            for event in self.state.get("events", [])
            if isinstance(event, dict) and event.get("domain", event.get("kind")) == "exploration"
        ]
        query = str(interests[len(past) % len(interests)]["topic"])[:200]
        self.active()
        self.details["research_query"] = query
        rows = await asyncio.wait_for(searxng_search(query, max_results=3), timeout=25)
        self.active()
        facts = []
        for row in rows[:3]:
            if not isinstance(row, dict):
                continue
            observation = public_source_observation(row, datetime.now(UTC))
            if observation is None:
                continue
            facts.append(
                _fact(
                    "web",
                    observation,
                    url=observation["url"],
                    observed_at=observation["collected_at"],
                    interpretation="retrieved_source_not_verified_claim",
                )
            )
        if not facts:
            raise LifeBlocked("research_returned_no_sources")
        return facts

    async def decide(self, state: LifeCycle) -> LifeCycle:
        self.active()
        if state.get("portfolio") or state.get("evolution") or state.get("discovered_goals"):
            return {}
        from fastapi import HTTPException

        from modstore_server.llm_api import resolve_default_llm_route
        from modstore_server.models import get_session_factory
        from modstore_server.services.llm import chat_dispatch_via_platform_only
        from modstore_server.strategic_portfolio_usage import (
            planning_admission,
            planning_usage_scope,
        )

        try:
            with get_session_factory()() as session:
                route = await resolve_default_llm_route(
                    session, self.claim["owner_user_id"], platform_only=True
                )
        except HTTPException as exc:
            raise LifeBlocked("platform_model_not_configured") from exc
        provider, model = route["provider"], route["model"]
        admission = await planning_admission(
            provider, model, owner_user_id=self.claim["owner_user_id"]
        )
        if admission is None:
            raise LifeBlocked("platform_quota_unknown_or_exhausted")
        admission = dict(admission)
        admission["max_total_tokens"] = min(
            admission["max_total_tokens"], self.claim["reserved_tokens"]
        )
        try:
            messages, refs = cognition_messages(
                self.state,
                self.domain,
                state["facts"],
                max_prompt_tokens=admission["max_total_tokens"] - 128,
            )
        except CognitionContextError as exc:
            raise LifeBlocked(str(exc)) from exc
        self.details["attention"] = {
            "selected_refs": sorted(refs),
            "observations_considered": len(state["facts"]),
            "status": "bounded_context_not_authorization",
        }
        prompt_bound = cognition_prompt_bound(messages)
        output_bound = min(
            1600,
            admission["max_output_tokens"],
            admission["max_total_tokens"] - prompt_bound,
        )
        if output_bound < 128:
            raise LifeBlocked("life_cycle_prompt_budget_exhausted")
        admission["max_output_tokens"] = output_bound
        self.active()
        self.model = f"{provider}/{model}"
        with planning_usage_scope(self.claim["owner_user_id"], admission) as context:
            self.actual_tokens = None
            try:
                # Commit the original uncertainty fence before any paid model
                # transport; an absent return receipt must NOT become zero use.
                _store().mark_model_attempt(self.claim)
                result = await chat_dispatch_via_platform_only(
                    provider, model, messages, max_tokens=output_bound
                )
            finally:
                receipts = list(context["receipts"])
                self.details["model_receipts"] = receipts
                if not receipts:
                    self.actual_tokens = None
                elif all(row.get("status") == "settled" for row in receipts):
                    self.actual_tokens = sum(int(row["actual_tokens"]) for row in receipts)
        if self.actual_tokens is None:
            raise LifeBlocked("model_usage_unknown")
        if not result.get("ok"):
            raise LifeBlocked("model_returned_no_usable_result")
        self.active()
        decision = parse_decision(
            str(result.get("content") or ""),
            refs=refs,
            level=self.state["level"],
            domain=self.domain,
        )
        self.evidence = sorted(refs)
        self.details["model_note"] = decision.summary
        self.details["model_note_status"] = "unverified_suggestion"
        if decision.alternatives:
            self.details["proposal_review"] = {
                "status": "unverified_options_not_execution_authority",
                "alternatives": [item.model_dump() for item in decision.alternatives],
            }
        return {
            "decision": decision.model_dump(),
            "model_receipt": {
                "actual_tokens": self.actual_tokens,
                "model": self.model,
                "evidence_refs": self.evidence[:32],
            },
        }

    async def act(self, state: LifeCycle) -> LifeCycle:
        self.active()
        if state.get("portfolio"):
            return await self.advance_portfolio(state["portfolio"])
        if state.get("evolution"):
            from modstore_server.xiaoc_life_evolution import propose_budget

            goal = await self.write_in_thread(propose_budget, self.claim, state["evolution"])
            self.evidence = [
                "retort:" + goal["retort_request_id"],
                "portfolio:" + goal["decision_id"],
            ]
            return {
                "goals": [goal],
                "status": "completed",
                "summary": "已将原改进批准接入公司工程预算提案，等待原审批。",
            }
        if state.get("discovered_goals"):
            goal = dict(state["discovered_goals"][0])
            policy = self.state.get("policy", {})
            limits = policy.get("portfolio_limits")
            employee = policy.get("employee_id")
            if not limits or not employee:
                goal["blocked_reason"] = "awaiting_existing_portfolio_policy"
                return {
                    "goals": [goal],
                    "status": "completed",
                    "summary": "已创建有来源的经营候选；等待原企业预算及员工授权。",
                }
            from modstore_server.strategy_business_context import customer_value_context
            from modstore_server.xiaoc_goal_management import (
                ORIGIN,
                compile_autonomous_review_plan,
            )
            from modstore_server.xiaoc_life_policy import LifePolicyError
            from modstore_server.strategic_portfolio import (
                PortfolioError,
                create_portfolio_proposal,
                digest,
            )
            from modstore_server.xiaoc_self_model import employee_preflight

            current_value = await self.write_in_thread(customer_value_context)
            self.active()
            try:
                opportunities, bindings = compile_autonomous_review_plan(
                    goal,
                    owner=self.claim["owner_user_id"],
                    policy=policy,
                    goals=[*self.state.get("goals", []), goal],
                    current_value=current_value,
                    now=datetime.now(UTC),
                )
            except LifePolicyError as exc:
                goal["blocked_reason"] = str(exc)
                goal["next_review_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
                return {
                    "goals": [goal],
                    "status": "completed",
                    "summary": "经营候选已记录，但原调查授权或实时来源不满足条件。",
                }
            preflight = await self.write_in_thread(
                employee_preflight, employee, self.claim["owner_user_id"]
            )
            self.active()
            self.details["operating_employee_preflight"] = preflight
            if preflight["status"] != "registered_unverified":
                goal["blocked_reason"] = preflight["reason"]
                goal["next_review_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
                return {
                    "goals": [goal],
                    "status": "completed",
                    "summary": "经营候选已记录，但尚无符合原执行入口的员工。",
                }
            try:
                proposal = await self.write_in_thread(
                    create_portfolio_proposal,
                    owner_user_id=self.claim["owner_user_id"],
                    goal=goal["title"],
                    period="xiaoc-life:" + goal["id"][:45],
                    limits=limits,
                    opportunities=opportunities,
                    idempotency_key="xiaoc-life:" + digest([goal["id"], ORIGIN]),
                )
            except PortfolioError as exc:
                goal["blocked_reason"] = str(exc)
                goal["next_review_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
                return {
                    "goals": [goal],
                    "status": "completed",
                    "summary": "原预算优化或提案约束不满足；保留未授权经营候选。",
                }
            self.active()
            if not proposal.get("decision"):
                goal["blocked_reason"] = "awaiting_feasible_review_option"
                goal["next_review_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
                return {
                    "goals": [goal],
                    "status": "completed",
                    "summary": "原资源约束没有可行的调查提案；未获得执行授权。",
                }
            goal.update(
                status="awaiting_approval",
                decision_id=proposal["decision"]["decision_id"],
                step_bindings=bindings,
                subgoals_status="bound_to_original_portfolio",
            )
            self.details.setdefault("created_proposals", []).append(
                {"goal_id": goal["id"], "decision_id": goal["decision_id"]}
            )
            return {
                "goals": [goal],
                "status": "completed",
                "summary": "已自动创建两步经营调查提案，仍待原预算审批；没有派工或业务写入。",
            }
        decision = state["decision"]
        if decision["action"] == "wait":
            return {
                "status": "completed",
                "summary": "已核对当前观察，本轮没有新增行动。",
            }
        goals = []
        suggestion = decision.get("goal") or (
            decision.get("self_assessment")
            if self.domain == "reflection"
            and self.state.get("policy", {}).get("retort_template_id")
            else None
        )
        if suggestion:
            goal_id = (
                "xiaoc-goal-"
                + _digest(
                    [
                        self.state["identity_id"],
                        self.domain,
                        " ".join(suggestion["title"].split()).casefold(),
                        " ".join(suggestion["description"].split()).casefold(),
                    ]
                )[:24]
            )
            goal = {
                **suggestion,
                "id": goal_id,
                "domain": self.domain,
                "status": "proposed",
            }
            existing = next(
                (item for item in self.state.get("goals", []) if item.get("id") == goal_id),
                None,
            )
            if existing is not None:
                goal = dict(existing)
                self.details["existing_goal_id"] = goal_id
            elif len(self.state.get("goals", [])) >= 100:
                self.details["blocked_reason"] = "life_goal_capacity_reached"
                return {
                    "status": "blocked",
                    "summary": "当前目标已达容量上限，未创建新目标或提案。",
                }
            if (
                self.domain == "reflection"
                and self.state.get("policy", {}).get("retort_template_id")
                and not goal.get("decision_id")
            ):
                from modstore_server.xiaoc_life_evolution import propose

                self.active()
                goal = await self.write_in_thread(propose, self.claim, goal)
                self.details["retort_request_id"] = goal["retort_request_id"]
            limits = self.state.get("policy", {}).get("portfolio_limits")
            employee = self.state.get("policy", {}).get("employee_id")
            if (
                limits
                and employee
                and not goal.get("decision_id")
                and not goal.get("retort_request_id")
                and goal.get("status") == "proposed"
            ):
                from modstore_server.strategic_portfolio import (
                    create_portfolio_proposal,
                )
                from modstore_server.xiaoc_self_model import employee_preflight

                self.active()
                preflight = await asyncio.to_thread(
                    employee_preflight, employee, self.claim["owner_user_id"]
                )
                self.active()
                self.details["employee_capability_preflight"] = preflight
                if preflight["status"] != "registered_unverified":
                    goal["blocked_reason"] = preflight["reason"]
                    goals.append(goal)
                    return {
                        "goals": goals,
                        "status": "blocked",
                        "summary": "员工能力来源不可用或未知，未创建执行提案。",
                    }
                proposal = create_portfolio_proposal(
                    owner_user_id=self.claim["owner_user_id"],
                    goal=goal["title"],
                    period="xiaoc-life:" + goal["id"][:45],
                    limits=limits,
                    opportunities=[
                        {
                            "opportunity_id": goal["id"],
                            "title": goal["title"],
                            "task": goal["description"],
                            "employee_id": employee,
                            "input_data": self.state.get("policy", {}).get("task_input", {}),
                            "value_score": 1,
                            # These are scheduler probe weights, not an estimated return/probability.
                            "confidence_bps": 1 if self.domain == "enterprise" else 2500,
                            "hypothesis": decision.get("hypothesis"),
                            **{
                                key: limits[key]
                                for key in ("cost_cents", "tokens", "compute_seconds")
                            },
                            "compute_seconds": min(limits["compute_seconds"], 240),
                            "risk": "medium",
                            "source_refs": goal["evidence_refs"],
                        }
                    ],
                    decision_options=(
                        {
                            "alternatives": decision.get("alternatives", []),
                            "context_sha256": _digest(
                                [
                                    self.details.get("attention", {}).get("selected_refs", []),
                                    [
                                        fact
                                        for fact in state.get("facts", [])
                                        if fact.get("ref") in self.evidence
                                    ],
                                    self.state.get("identity_id"),
                                    self.state.get("self_model", {}),
                                ]
                            ),
                            "evidence_refs": sorted(self.evidence or goal["evidence_refs"]),
                        }
                        if self.domain == "enterprise"
                        else None
                    ),
                    idempotency_key="xiaoc-life:"
                    + _digest(
                        [
                            goal["id"],
                            limits,
                            employee,
                            self.state.get("policy", {}).get("task_input", {}),
                        ]
                    )[:48],
                )
                if proposal.get("decision_review"):
                    self.details["decision_comparison"] = proposal["decision_review"]
                if proposal.get("decision") is None:
                    goal["blocked_reason"] = "awaiting_feasible_decision_option"
                    return {
                        "goals": [goal],
                        "status": "blocked",
                        "summary": "原资源约束未找到可行行动，本轮保留不行动选项及比较回执。",
                    }
                goal.update(
                    decision_id=proposal["decision"]["decision_id"],
                    status="awaiting_approval",
                )
                self.details.setdefault("created_proposals", []).append(
                    {"goal_id": goal["id"], "decision_id": goal["decision_id"]}
                )
            elif not goal.get("decision_id") and goal.get("status") == "proposed":
                goal["blocked_reason"] = "awaiting_portfolio_policy"
            goals.append(goal)
        assessment = decision.get("self_assessment")
        return {
            "goals": goals,
            "interests": decision["interests"],
            "self_model": {**assessment, "status": "hypothesis"} if assessment else {},
            "status": "completed",
            "summary": (
                "同一目标已存在，保留其原状态和执行身份。"
                if self.details.get("existing_goal_id")
                else (
                    "已根据真实观察形成待批准目标，尚未执行目标。"
                    if goals
                    else "已根据真实观察整理学习兴趣与待核验的反思。"
                )
            ),
        }

    async def advance_portfolio(self, binding: dict[str, Any]) -> LifeCycle:
        from modstore_server.strategic_portfolio import plan_portfolio, portfolio_status
        from modstore_server.strategic_portfolio_runtime import (
            review_portfolio,
            run_portfolio_cycle,
        )

        before = binding["snapshot"]
        decision_id = before["decision_id"]
        owner = self.claim["owner_user_id"]
        from modstore_server.strategy_business_context import customer_value_context
        from modstore_server.xiaoc_goal_management import ORIGIN

        gate = None
        if binding["goal"].get("candidate_origin") == ORIGIN:
            observation = await asyncio.to_thread(customer_value_context)
            self.active()
            gate = candidate_gate(binding["goal"], owner, observation, now=datetime.now(UTC))
            self.details["operating_gate"] = gate
            self.evidence = [*binding["goal"]["evidence_refs"], gate["evidence_ref"]]
            if gate["status"] != "eligible":
                return {
                    "goals": [
                        {
                            "id": binding["goal"]["id"],
                            "evidence_refs": binding["goal"]["evidence_refs"],
                            "operating_gate": gate,
                        }
                    ],
                    "status": "blocked",
                    "summary": "原经营候选等待有效缺口证据；未派发新任务，保留原回执。",
                }
            self.claim["operating_goal_admission"] = {
                "decision_id": decision_id,
                "goal_id": binding["goal"]["id"],
                "gate": gate,
            }
        plan_portfolio(decision_id, owner_user_id=owner)
        current = portfolio_status(decision_id, owner_user_id=owner)
        pending = _ready_portfolio_tasks(current)
        company = bool(current.get("limits", {}).get("company_budget_id"))
        if pending and (
            all(item["tokens"] > self.claim["reserved_tokens"] for item in pending)
            if company
            else pending[0]["tokens"] > self.claim["reserved_tokens"]
        ):
            raise LifeBlocked("portfolio_task_exceeds_life_cycle_budget")

        def usage(snapshot):
            calls = [
                call
                for task in snapshot.get("tasks", {}).values()
                for call in task.get("calls", {}).values()
            ]
            if any(call.get("status") != "settled" for call in calls):
                return None
            if any(
                task.get("status") in {"waiting", "running"}
                for task in snapshot.get("tasks", {}).values()
            ):
                return None
            return sum(int(call["actual_tokens"]) for call in calls)

        self.active()
        _store().record_cycle_step(
            self.claim,
            kind="portfolio",
            details={
                "decision_id": decision_id,
                "before_call_ids": [
                    call_id
                    for task in before.get("tasks", {}).values()
                    for call_id in task.get("calls", {})
                ],
                "before_task_ids": list(before.get("tasks", {})),
            },
        )
        self.actual_tokens = None
        self.portfolio_started = True
        try:
            report = await self.write_in_thread(
                run_portfolio_cycle, decision_id, owner_user_id=owner, max_tasks=1
            )
        finally:
            after = portfolio_status(decision_id, owner_user_id=owner)
            old, new = usage(before), usage(after)
            if old is not None and new is not None:
                self.actual_tokens = max(0, new - old)
        if _store().cycle_active(self.claim) and after.get("started_at"):
            await self.write_in_thread(review_portfolio, decision_id, owner_user_id=owner)
            after = portfolio_status(decision_id, owner_user_id=owner)
            old, new = usage(before), usage(after)
            if old is not None and new is not None:
                self.actual_tokens = max(0, new - old)
        from modstore_server.xiaoc_life_reflection import review_experiences

        feedback = portfolio_feedback(after)
        self.details["business_reflection"], _ = review_experiences(after)
        self.details["outcome_feedback"] = feedback
        self.evidence = [f"strategic_portfolio:{decision_id}", feedback["evidence_ref"]]
        self.details["portfolio_receipt"] = {
            "decision_id": decision_id,
            "status": after["status"],
            "processed": report.get("processed", 0),
            "halted": after.get("halted", False),
        }
        selected = after.get("plan", {}).get("selected", [])
        selected_tasks = [after.get("tasks", {}).get(key, {}) for key in selected]
        step_projection = project_goal_steps(binding["goal"], after)
        all_steps_verified = (
            not step_projection or step_projection.get("all_steps_verified") is True
        )
        remaining_ready = company and bool(_ready_portfolio_tasks(after))
        goal_status = "active"
        if portfolio_goal_closed(after, now=datetime.now(UTC)):
            goal_status = "stopped"
        elif (
            not remaining_ready
            and selected_tasks
            and all(task.get("status") == "completed" for task in selected_tasks)
            and all_steps_verified
        ):
            goal_status = "execution_verified"
        elif (
            step_projection
            and not remaining_ready
            and selected_tasks
            and all(task.get("status") == "completed" for task in selected_tasks)
        ):
            goal_status = "blocked"
        elif (
            not remaining_ready
            and selected_tasks
            and all(task.get("status") in {"completed", "failed"} for task in selected_tasks)
        ):
            goal_status = "failed"
        goal = {
            **binding["goal"],
            "status": goal_status,
            "outcome_status": feedback["outcome_status"],
            "outcome_feedback": feedback["metrics"],
            "outcome_ref": feedback["evidence_ref"],
            "goal_review": goal_review_projection(
                owner=owner,
                goal_id=binding["goal"]["id"],
                decision_id=decision_id,
                status=goal_status,
                feedback=feedback,
            ),
            "evidence_refs": list(
                dict.fromkeys([*binding["goal"].get("evidence_refs", []), *self.evidence])
            ),
        }
        if gate is not None:
            goal["operating_gate"] = gate
            goal["step_projection"] = step_projection
        if goal_status == "execution_verified":
            goal["next_review_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        elif remaining_ready:
            goal.pop("next_review_at", None)
        queued = self.bound_worker_receipts(before, after)
        if queued:
            self.details["awaiting_worker"] = queued
            self.evidence.extend(row["receipt_ref"] for row in queued)
            return {
                "goals": [goal],
                "status": "awaiting_worker",
                "summary": "已核对原持久队列回执，等待同一员工任务；保留原租约与预算。",
            }
        return {
            "goals": [goal],
            "status": "completed" if self.actual_tokens is not None else "waiting",
            "summary": (
                "已推进原批准组合并保存执行回执。" + feedback["summary"]
                if self.actual_tokens is not None
                else "原批准组合回执尚未明确；保留预算，等待核对。"
            ),
        }

    def bound_worker_receipts(
        self, before: dict[str, Any], after: dict[str, Any]
    ) -> list[dict[str, str]]:
        """Only the original persisted local queue may retain this cycle's lease."""
        from modstore_server.strategic_execution_receipts import (
            evaluate_execution_receipt,
        )

        if after.get("halted"):
            return []
        receipts = []
        for key, task in after.get("tasks", {}).items():
            calls = task.get("calls", {}).values()
            if task.get("status") == "unknown":
                return []
            if any(call.get("status") not in {"settled", "pending"} for call in calls):
                return []
            if key in before.get("tasks", {}) or task.get("status") not in {
                "waiting",
                "running",
            }:
                if any(call.get("status") != "settled" for call in calls):
                    return []
                continue
            worker = task.get("worker_binding") or {}
            receipt = task.get("execution_receipt") or {}
            scope = worker.get("life_scope") or {}
            if (
                worker.get("decision_id") != after["decision_id"]
                or worker.get("opportunity_id") != key
                or worker.get("owner_user_id") != self.claim["owner_user_id"]
                or not task.get("lease_token")
                or worker.get("lease_token") != task["lease_token"]
                or not after.get("proposal_sha256")
                or worker.get("proposal_sha256") != after["proposal_sha256"]
                or not worker.get("binding_id")
                or not worker.get("receipt_id")
                or receipt.get("worker_receipt_id") != worker["receipt_id"]
                or evaluate_execution_receipt(receipt).status != "pending"
                or any(
                    scope.get(field) != self.claim.get(field)
                    for field in (
                        "cycle_id",
                        "lease_token",
                        "owner_user_id",
                        "domain",
                        "reserved_tokens",
                        "policy_revision",
                        "deadline",
                    )
                )
            ):
                return []
            receipts.append(
                {
                    "decision_id": after["decision_id"],
                    "opportunity_id": key,
                    "receipt_ref": f"worker-receipt:{worker['receipt_id']}",
                    "binding_ref": f"worker-binding:{worker['binding_id']}",
                }
            )
        return receipts

    async def reflect(self, state: LifeCycle) -> LifeCycle:
        # Preserve existing goal and budget authority; record only observed evidence.
        receipt = reflection_receipt(
            self.details.get("outcome_feedback"),
            evidence_refs=self.evidence,
            status=state.get("status", "failed"),
            actual_tokens=self.actual_tokens,
        )
        if (
            receipt["status"] == "unmeasured"
            and state.get("decision")
            and self.details.get("model_note_status") == "unverified_suggestion"
        ):
            receipt = {"status": "model_suggestion_only", "evidence_refs": list(self.evidence)}
        self.details["reflection_receipt"] = receipt
        return state

    def finish(self, result: Mapping[str, Any]) -> dict[str, Any]:
        if result.get("status") == "awaiting_worker" and self.details.get("awaiting_worker"):
            return dict(
                _store().defer_cycle(
                    self.claim,
                    summary=result["summary"],
                    evidence_refs=self.evidence,
                    details=self.details,
                )
            )
        return dict(
            _store().finish_cycle(
                self.claim,
                status=result.get("status", "failed"),
                summary=result.get("summary", "本轮没有形成可用结果。"),
                evidence_refs=self.evidence,
                actual_tokens=self.actual_tokens,
                model=self.model,
                goals=result.get("goals"),
                interests=result.get("interests"),
                self_model=result.get("self_model"),
                details=self.details,
            )
        )


def build_life_graph(ports: CyclePorts, *, checkpointer: Any | None = None):
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(LifeCycle)

    def durable_node(name: str):
        async def invoke(state: LifeCycle) -> LifeCycle:
            with life_operation(name):
                if name != "reflect":
                    ports.active()
                _store().record_cycle_phase(ports.claim, name)
                result: LifeCycle = await getattr(ports, name)(state)
                if name in {"act", "reflect"}:
                    _store().record_cycle_checkpoint(
                        ports.claim,
                        name,
                        result=dict(result),
                        actual_tokens=ports.actual_tokens,
                        evidence_refs=ports.evidence,
                        reflection_status=ports.details.get("reflection_receipt", {}).get("status"),
                    )
                return result

        return invoke

    for name in ("observe", "decide", "act", "reflect"):
        graph.add_node(name, durable_node(name))
    graph.add_edge(START, "observe")
    graph.add_edge("observe", "decide")
    graph.add_edge("decide", "act")
    graph.add_edge("act", "reflect")
    graph.add_edge("reflect", END)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["act"] if checkpointer is not None else None,
    )


async def _continue_at_act(
    graph: Any,
    config: dict[str, Any],
    ports: CyclePorts,
    *,
    restoring: bool,
) -> dict[str, Any] | None:
    """Resume exactly once from a persisted, verified pre-act checkpoint."""
    snapshot = await graph.aget_state(config)
    if tuple(snapshot.next) != ("act",):
        return None
    state = snapshot.values
    if not isinstance(state, dict):
        return None
    receipt = state.get("model_receipt")
    if state.get("decision"):
        # On recovery the in-memory model receipt is NOT authoritative.
        # Refuse a new act until the original outbound ledger is independently
        # settled and agrees with the durable LangGraph state.
        if not isinstance(receipt, dict):
            return None
        if restoring:
            from modstore_server.xiaoc_life_reconciliation import _verified_usage

            with life_operation("reconcile"):
                usage = await asyncio.to_thread(
                    _verified_usage, ports.claim.get("steps", []), ports.claim["owner_user_id"]
                )
        else:
            # The original platform scope completed inside THIS live process.
            # Only recovered calls require SQL receipt reconstruction.
            usage = ports.actual_tokens
        if (
            usage is None
            or type(receipt.get("actual_tokens")) is not int
            or usage != receipt["actual_tokens"]
            or usage > ports.claim["reserved_tokens"]
        ):
            return None
        ports.actual_tokens = usage
        ports.model = str(receipt.get("model") or "")[:256]
        ports.evidence = [
            ref
            for ref in receipt.get("evidence_refs", [])
            if isinstance(ref, str) and 0 < len(ref) <= 256
        ][:32]
    if not _store().admit_cycle_act(ports.claim):
        return None  # The winner owns this cycle; never settle its reservation.
    result: dict[str, Any] = await graph.ainvoke(None, config, durability="sync")
    return result


def _verified_closeout(claim: dict[str, Any], state: Any) -> dict[str, Any] | None:
    from modstore_server.strategic_portfolio import PortfolioError, portfolio_status
    from modstore_server.strategic_portfolio_runtime import read_life_closeout_receipt

    if not isinstance(state, dict) or state.get("decision") or state.get("model_receipt"):
        return None
    binding = state.get("portfolio")
    if not isinstance(binding, dict):
        return None
    goal, before = binding.get("goal"), binding.get("snapshot")
    if not isinstance(goal, dict) or not isinstance(before, dict):
        return None
    goal_id, decision_id = goal.get("id"), goal.get("decision_id")
    owner, proposal_hash = claim["owner_user_id"], before.get("proposal_sha256")
    if (
        not goal_id
        or not decision_id
        or not isinstance(proposal_hash, str)
        or not proposal_hash
        or before.get("decision_id") != decision_id
        or before.get("owner_user_id") != owner
        or not isinstance(goal.get("title"), str)
        or not goal["title"]
        or before.get("goal") != goal["title"][:4000]
        or before.get("tasks", {}) != {}
        or claim.get("awaiting_worker")
        or claim.get("outbound_journal_version") != 1
        or claim.get("outbound_attempted", False) is not False
        or claim.get("steps")
        != [
            {
                "kind": "portfolio",
                "decision_id": decision_id,
                "before_task_ids": [],
                "before_call_ids": [],
            }
        ]
        or not any(
            current.get("id") == goal_id
            and current.get("decision_id") == decision_id
            and current.get("title") == goal["title"]
            and current.get("domain", "enterprise")
            == goal.get("domain", "enterprise")
            == claim["domain"]
            for current in claim["state"]["goals"]
        )
    ):
        return None
    receipt = read_life_closeout_receipt(claim, decision_id, proposal_hash)
    if receipt is None:
        return None
    try:
        record = portfolio_status(decision_id, owner_user_id=owner)
    except PortfolioError:
        return None
    if (
        record.get("proposal_sha256") != proposal_hash
        or record.get("goal") != before["goal"]
        or record.get("plan", {}).get("selected") != [receipt["task_id"]]
        or list(record.get("tasks", {})) != [receipt["task_id"]]
        or record["tasks"][receipt["task_id"]].get("status") != "completed"
    ):
        return None
    steps = project_goal_steps(goal, record)
    status = (
        "stopped"
        if portfolio_goal_closed(record, now=datetime.now(UTC))
        else (
            "blocked"
            if steps and steps.get("all_steps_verified") is not True
            else "execution_verified"
        )
    )
    feedback = portfolio_feedback(record)
    return {
        **receipt,
        "goal": {
            "id": goal_id,
            "decision_id": decision_id,
            "status": status,
            "outcome_status": feedback["outcome_status"],
            "outcome_feedback": feedback["metrics"],
            "outcome_ref": feedback["evidence_ref"],
            "goal_review": goal_review_projection(
                owner=owner,
                goal_id=goal_id,
                decision_id=decision_id,
                status=status,
                feedback=feedback,
            ),
            "evidence_refs": list(
                dict.fromkeys([*goal.get("evidence_refs", []), *receipt["evidence_refs"]])
            ),
            **({"step_projection": steps} if steps else {}),
        },
    }


async def _closeout_at_act(
    graph: Any, config: dict[str, Any], claim: dict[str, Any]
) -> dict[str, Any] | None:
    from langgraph.graph import END

    snapshot = await graph.aget_state(config)
    checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id")
    marker = claim.get("native_closeout")
    if marker is None:
        if snapshot.next != ("act",) or not checkpoint_id:
            return None
        receipt = _verified_closeout(claim, snapshot.values)
        if receipt is None or not _store().prepare_native_closeout(claim, checkpoint_id, receipt):
            return None
        marker = {"source_checkpoint_id": checkpoint_id, "receipt": receipt}

    source_config = {
        **config,
        "configurable": {**config["configurable"], "checkpoint_id": marker["source_checkpoint_id"]},
    }
    source = await graph.aget_state(source_config)
    source_step = source.metadata.get("step") if source.metadata else None
    if source.next != ("act",) or type(source_step) is not int:
        return None
    terminal_id = None
    if checkpoint_id == marker["source_checkpoint_id"] and snapshot.next == ("act",):
        updated = await graph.aupdate_state(source_config, None, as_node=END)
        terminal_id = updated["configurable"]["checkpoint_id"]
        snapshot = await graph.aget_state(config)
    if (
        snapshot.next
        or snapshot.tasks
        or snapshot.values != source.values
        or not snapshot.metadata
        or snapshot.metadata.get("source") != "update"
        or snapshot.metadata.get("step") != source_step + 1
        or not snapshot.parent_config
        or snapshot.parent_config["configurable"] != source.config["configurable"]
        or (
            terminal_id is not None
            and snapshot.config["configurable"]["checkpoint_id"] != terminal_id
        )
    ):
        return None
    receipt = marker["receipt"]
    with life_operation("settle"):
        closed: dict[str, Any] = _store().finish_cycle(
            claim,
            status="completed",
            summary="已核对原本地任务的持久回执并关闭原运行，未重新执行任务。",
            actual_tokens=receipt["actual_tokens"],
            evidence_refs=receipt["evidence_refs"],
            goals=[receipt["goal"]],
            details={
                "portfolio_selection": {
                    "goal_id": receipt["goal"]["id"],
                    "decision_id": receipt["decision_id"],
                },
                "native_closeout": {
                    "source_checkpoint_id": marker["source_checkpoint_id"],
                    "terminal_checkpoint_id": snapshot.config["configurable"]["checkpoint_id"],
                    "task_id": receipt["task_id"],
                },
            },
            expected_closeout=marker,
        )
        return closed


async def recover_native_act() -> dict[str, Any] | None:
    """Settle a verified act receipt, or resume a decision not yet admitted to act."""
    closed = await _recover_native_act(closing=True)
    return closed if closed is not None else await _recover_native_act(closing=False)


async def _recover_native_act(*, closing: bool) -> dict[str, Any] | None:
    from modstore_server.models import get_session_factory
    from modstore_server.xiaoc_life_store import try_cycle_lock

    if closing:
        with get_session_factory()() as session:
            if session.get_bind().dialect.name != "postgresql":
                return None
        load = _store().pending_native_closeout_claim
    else:
        load = _store().pending_native_act_claim
    claim = load()
    if claim is None:
        return None
    with try_cycle_lock(claim["cycle_id"]) as acquired:
        if not acquired:
            return None
        fresh = load()
        if (
            fresh is None
            or fresh["cycle_id"] != claim["cycle_id"]
            or fresh["lease_token"] != claim["lease_token"]
        ):
            return None
        ports = CyclePorts(fresh)
        try:
            async with native_life_checkpointer() as saver:
                graph = build_life_graph(ports, checkpointer=saver)
                config = native_thread_config(fresh)
                if closing:
                    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                    if isinstance(saver, AsyncPostgresSaver):
                        return await _closeout_at_act(graph, config, fresh)
                    return None
                with (
                    life_operation("graph", cycle_id=fresh["cycle_id"]),
                    _store().life_execution_scope(fresh),
                ):
                    result = await _continue_at_act(graph, config, ports, restoring=True)
                if result is not None:
                    with life_operation("settle"):
                        return ports.finish(result)
        finally:
            await ports.drain_writes()
    return None


async def run_claimed_cycle(claim: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.xiaoc_life_store import try_cycle_lock

    with try_cycle_lock(claim["cycle_id"]) as acquired:
        if not acquired:
            return dict(_store().read_state())
        return await _run_locked_cycle(claim)


async def _run_locked_cycle(claim: dict[str, Any]) -> dict[str, Any]:
    if not _store().begin_cycle_graph(claim):
        # Never finish or release the reservation of a competing invocation.
        return dict(_store().read_state())
    ports = CyclePorts(claim)
    try:
        with (
            life_operation("graph", cycle_id=claim["cycle_id"]),
            _store().life_execution_scope(claim),
        ):
            async with native_life_checkpointer() as saver:
                graph = build_life_graph(ports, checkpointer=saver)
                config = native_thread_config(claim)
                await graph.ainvoke({}, config, durability="sync")
                result = await _continue_at_act(graph, config, ports, restoring=False)
                if result is None:
                    # Another worker won the pre-act CAS, or an unverified
                    # model receipt prevents effects. Do not finish its lease.
                    return dict(_store().read_state())
    except asyncio.CancelledError:
        # A portfolio may already have committed its receipt just as the graph
        # is cancelled. Leave its admitted act available to receipt recovery.
        if not ports.pending_writes and not ports.portfolio_started:
            ports.details["reason"] = "cycle_cancelled"
            with life_operation("settle"):
                ports.finish(
                    {
                        "status": "interrupted",
                        "summary": "本轮已中断，未知调用保留预算等待核对。",
                    }
                )
        raise
    except BOUNDARY_ERRORS as exc:
        ports.details["reason"] = str(exc) if isinstance(exc, LifeBlocked) else type(exc).__name__
        result = {
            "status": "blocked" if isinstance(exc, LifeBlocked) else "failed",
            "summary": BLOCKED_SUMMARIES.get(
                ports.details["reason"], "本轮条件尚未满足，已保留观察和调用记录。"
            ),
        }
    finally:
        await ports.drain_writes()
    with life_operation("settle"):
        return ports.finish(result)


async def tick_async() -> dict[str, Any]:
    from modstore_server.xiaoc_life_reconciliation import (
        reconcile_goals,
        reconcile_usage,
    )
    from modstore_server.xiaoc_self_model import execution_scope, record_identity_check

    with life_operation("tick"):
        closed = await _recover_native_act(closing=True)
        with life_operation("reconcile"):
            reconcile_usage()
            reconcile_goals()
        if closed is not None:
            settled: dict[str, Any] = _store().read_state()
            return settled
        resumed = await _recover_native_act(closing=False)
        if resumed is not None:
            return resumed
        store = _store()
        state = store.read_state()
        # Revalidate only the persistent identity against the original SQL ledger.
        # This is not a model call, budget action or grant of new permission.
        if execution_scope(state) is not None:
            checked = await asyncio.to_thread(record_identity_check, only_if_due=True)
            if checked["status"] != "not_due":
                state = store.read_state()
        for domain in _domain_order(state):
            claim = store.claim_cycle(
                domain=domain, reserve_tokens=_cycle_reservation(state, domain)
            )
            if claim is not None:
                claim["state"]["events"] = state.get("events", [])
                # Do not pass revision-bound evidence from a stale snapshot to a new claim.
                same_revision = state["revision"] == claim["policy_revision"]
                claim["state"]["experience_review_facts"] = (
                    state.get("experience_review_facts", []) if same_revision else []
                )
                claim["state"]["self_identity_checks"] = (
                    state.get("self_identity_checks", []) if same_revision else []
                )
                claim["state"]["self_promptfoo_checks"] = state.get("self_promptfoo_checks", [])
                return await run_claimed_cycle(claim)
        return {"status": "idle", "identity_id": state["identity_id"]}


def tick() -> dict[str, Any]:
    """Existing APScheduler adapter; opening a chat never starts this loop."""
    return asyncio.run(tick_async())
