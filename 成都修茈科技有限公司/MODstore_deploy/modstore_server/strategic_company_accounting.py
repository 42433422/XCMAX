"""Project actual task/call encumbrances into one atomic company envelope."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from modstore_server.strategic_company_resources import (
    CompanyConflict,
    active_budget,
    load_row,
    totals,
    write_row,
)
from modstore_server.strategic_portfolio import RESOURCES, PortfolioError, _date


def task_allocation(proposal: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    allocation: dict[str, Any] = {
        "kind": "portfolio",
        "owner_user_id": proposal["owner_user_id"],
        "proposal_sha256": proposal["proposal_sha256"],
        "spent": dict.fromkeys(RESOURCES, 0),
        "held": dict.fromkeys(RESOURCES, 0),
        "slots": 0,
    }
    for task in state.get("tasks", {}).values():
        calls = list(task.get("calls", {}).values())
        settled = [call for call in calls if call["status"] == "settled"]
        known_terminal = (
            task["status"] in {"completed", "failed"}
            and len(settled) == len(calls)
            and all(
                key in task for key in ("actual_tokens", "accrued_cost_cents", "compute_seconds")
            )
        )
        spent = {
            "tokens": sum(call["actual_tokens"] for call in settled),
            "cost_cents": sum(call["accrued_cost_cents"] for call in settled),
            "compute_seconds": max(0, math.ceil(task.get("compute_seconds", 0))),
        }
        if known_terminal:
            spent.update(tokens=task["actual_tokens"], cost_cents=task["accrued_cost_cents"])
        for key in RESOURCES:
            allocation["spent"][key] += spent[key]
            if not known_terminal:
                allocation["held"][key] += max(0, task["reservation"][key] - spent[key])
        capacity = task.get("worker_capacity") or {}
        adapter = (task.get("worker_binding") or {}).get("adapter")
        remote_state = task.get("remote_state") or {}
        idle_phase = (
            task["status"] == "waiting"
            and len(settled) == len(calls)
            and capacity.get("state") == "idle"
            and adapter in {"github_opencode_workspace", "original_pr_repair"}
            and (
                adapter != "original_pr_repair"
                or (
                    remote_state.get("phases", {}).get("execute", {}).get("status") == "closed"
                    and not remote_state.get("model_grant")
                    and bool(remote_state.get("task_grants"))
                    and all(
                        grant.get("status") == "closed" for grant in remote_state["task_grants"]
                    )
                )
            )
            and str(capacity.get("phase_receipt_id") or "").startswith("github:")
            and ":job:" in str(capacity.get("phase_receipt_id") or "")
        )
        allocation["slots"] += int(not known_terminal and not idle_phase)
    return allocation


def require_no_unmanaged_work(session: Any) -> None:
    """First activation cannot discard the deployment's pre-company liabilities."""
    import json

    from sqlalchemy import select

    from modstore_server.db.llm_chat import LlmClientRequest
    from modstore_server.db.strategic import StrategicDecision

    rows = session.execute(
        select(StrategicDecision).where(StrategicDecision.scope == "strategy_portfolio")
    ).scalars()
    for row in rows:
        proposal = json.loads(row.decision_payload_json or "{}")
        if proposal.get("limits", {}).get("company_budget_id"):
            continue
        allocation = task_allocation(proposal, json.loads(row.execution_result_json or "{}"))
        if allocation["slots"] or any(allocation["held"].values()):
            raise PortfolioError("pre-company task liabilities require terminal reconciliation")
    if session.execute(
        select(LlmClientRequest.id)
        .where(
            LlmClientRequest.client_request_id.startswith("strategy-discovery-"),
            LlmClientRequest.state.in_(("processing", "unknown")),
        )
        .limit(1)
    ).first():
        raise PortfolioError("pre-company planning liabilities require terminal reconciliation")


def _admitting(before: dict[str, Any], after: dict[str, Any]) -> bool:
    old = before.get("tasks", {})
    return any(
        key not in old or set(task.get("calls", {})) - set(old[key].get("calls", {}))
        for key, task in after.get("tasks", {}).items()
    )


def record_allocation(
    session: Any, budget_id: str, identity: str, allocation: dict[str, Any], *, admitting: bool
) -> None:
    if admitting:
        budget = active_budget(session, allocation["owner_user_id"], budget_id, touch_policy=True)
        if budget is None:
            raise PortfolioError("company reservation requires an approved mandate")
        row, proposal, state = budget
    else:
        row, proposal, state = load_row(session, budget_id)
    allocations = state.setdefault("allocations", {})
    previous = allocations.get(identity)
    if previous and (
        previous["owner_user_id"] != allocation["owner_user_id"]
        or any(previous["spent"][key] > allocation["spent"][key] for key in RESOURCES)
    ):
        raise PortfolioError("company settlement cannot change owner or erase measured spending")
    allocations[identity] = allocation
    used = totals(state)
    over = used["slots"] > proposal["limits"]["max_parallel"] or any(
        used["spent"][key] + used["held"][key] > proposal["limits"][key] for key in RESOURCES
    )
    if admitting and over:
        if allocation["kind"] == "portfolio":
            raise CompanyConflict("company headroom changed during portfolio admission")
        raise PortfolioError("company resource budget or execution capacity exhausted")
    if over:
        # Actual upstream usage remains truthful even after revocation/overshoot.
        if not state.get("halted"):
            state.update(halted=True, stop_reason="company_measured_resource_budget_exceeded")
        state["resource_budget_exceeded"] = True
    write_row(session, row, state)


def synchronize_portfolio(
    session: Any,
    decision_id: str,
    proposal: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    budget_id = proposal["limits"].get("company_budget_id")
    if not budget_id:
        return
    allocation = task_allocation(proposal, after)
    # Approval/plan have no allocation; the first real claim owns the envelope.
    if not after.get("tasks") and not before.get("tasks"):
        return
    record_allocation(
        session,
        budget_id,
        decision_id,
        allocation,
        admitting=(
            _admitting(before, after)
            or allocation["slots"] > task_allocation(proposal, before)["slots"]
        ),
    )


def reserve_planning(
    session: Any, record: dict[str, Any], prompt_bound: int, output_bound: int
) -> None:
    from modstore_server.strategic_portfolio_usage import _cost

    admission = record["admission"]
    budget = active_budget(
        session, record["owner_user_id"], str(admission.get("company_budget_id") or "")
    )
    if budget is None:
        return
    row, proposal, state = budget
    if admission.get("company_budget_id") != row.decision_id:
        raise PortfolioError("planning admission must bind the approved company budget")
    tariff = next(
        (
            item
            for item in proposal["limits"]["tariffs"]
            if (item["provider"], item["model"]) == (admission["provider"], admission["model"])
        ),
        None,
    )
    if tariff is None:
        raise PortfolioError("planning model has no approved company tariff")
    used = totals(state)
    seconds = min(
        45,
        proposal["limits"]["compute_seconds"]
        - used["spent"]["compute_seconds"]
        - used["held"]["compute_seconds"],
        math.floor((_date(proposal["limits"]["expires_at"]) - datetime.now(UTC)).total_seconds()),
    )
    if seconds <= 0:
        raise PortfolioError("company planning compute budget or expiry exhausted")
    record.update(
        company_budget_id=row.decision_id,
        tariff=tariff,
        reserved_cost_cents=_cost(prompt_bound, output_bound, tariff),
        reserved_compute_seconds=seconds,
    )
    record_allocation(
        session,
        row.decision_id,
        record["request_id"],
        {
            "kind": "planning",
            "owner_user_id": record["owner_user_id"],
            "spent": dict.fromkeys(RESOURCES, 0),
            "held": {
                "tokens": record["reserved_tokens"],
                "cost_cents": record["reserved_cost_cents"],
                "compute_seconds": record["reserved_compute_seconds"],
            },
            "slots": 1,
        },
        admitting=True,
    )


def settle_planning(
    session: Any, report: dict[str, Any], *, prompt: int | None, completion: int | None
) -> None:
    from modstore_server.strategic_portfolio_usage import _cost

    budget_id = report.get("company_budget_id")
    if not budget_id:
        return
    known = prompt is not None and completion is not None
    tokens = (prompt or 0) + (completion or 0) if known else 0
    cents = _cost(prompt or 0, completion or 0, report["tariff"]) if known else 0
    held = {
        "tokens": 0 if known else report["reserved_tokens"],
        "cost_cents": 0 if known else report["reserved_cost_cents"],
        "compute_seconds": 0 if known else report["reserved_compute_seconds"],
    }
    spent = {
        "tokens": tokens,
        "cost_cents": cents,
        "compute_seconds": (
            max(
                0,
                math.ceil(
                    (_date(report["completed_at"]) - _date(report["started_at"])).total_seconds()
                ),
            )
            if known
            else 0
        ),
    }
    report.update(
        accrued_cost_cents=cents if known else None, cost_basis="approved_company_tariff_accrual"
    )
    record_allocation(
        session,
        budget_id,
        report["request_id"],
        {
            "kind": "planning",
            "owner_user_id": report["owner_user_id"],
            "spent": spent,
            "held": held,
            "slots": int(not known),
        },
        admitting=False,
    )
