"""Read back existing execution evidence even while autonomous work is paused."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import aliased

from modstore_server.db.llm_chat import LlmClientRequest
from modstore_server.db.xiaoc_life import XiaoCLifeEvent
from modstore_server.strategic_portfolio import PortfolioError, digest, portfolio_status
from modstore_server.xiaoc_life_policy import IDENTITY_ID, parse_time, utcnow
from modstore_server.xiaoc_life_store import _event, _mutate, get_session_factory, read_state


def _verified_usage(steps: list[dict[str, Any]], owner: int) -> int | None:
    if not steps:
        return None
    portfolios = [step for step in steps if step["kind"] == "portfolio"]
    if portfolios:
        total = 0
        for step in portfolios:
            try:
                record = portfolio_status(step["decision_id"], owner_user_id=owner)
            except PortfolioError:
                return None
            tasks = [
                task
                for key, task in record.get("tasks", {}).items()
                if key not in step.get("before_task_ids", [])
            ]
            if any(task.get("status") not in {"completed", "failed"} for task in tasks):
                return None
            calls = [call for task in tasks for call in task.get("calls", {}).values()]
            if any(
                call.get("status") != "settled" or type(call.get("actual_tokens")) is not int
                for call in calls
            ):
                return None
            total += sum(call["actual_tokens"] for call in calls)
        return total
    total = 0
    with get_session_factory()() as session:
        for step in steps:
            if step["kind"] != "model" or step.get("decision_id"):
                return None
            row = session.scalar(
                select(LlmClientRequest).where(
                    LlmClientRequest.user_id == owner,
                    LlmClientRequest.client_request_id == step["request_id"],
                )
            )
            if row is None or row.state != "completed":
                return None
            receipt = json.loads(row.done_json or "{}")
            if receipt.get("status") != "settled" or type(receipt.get("actual_tokens")) is not int:
                return None
            total += receipt["actual_tokens"]
    return total


def reconcile_usage() -> dict[str, int]:
    """Resolve only the original persisted receipt, never replay an uncertain call."""
    from modstore_server.strategic_usage_reconciliation import reconcile_pending_usage

    reconcile_pending_usage()

    def collect(data: dict[str, Any], session: Any) -> list[dict[str, Any]]:
        active = data.get("active_cycle")
        pending = []
        if active and (active.get("awaiting_worker") or parse_time(active["deadline"]) <= utcnow()):
            pending.append(
                {
                    "cycle_id": active["cycle_id"],
                    "domain": active["domain"],
                    "reservation": active["reserved_tokens"],
                    "steps": active.get("steps", []),
                    "owner_user_id": active["owner_user_id"],
                    "outbound_journal_version": active.get("outbound_journal_version"),
                    "active": True,
                }
            )
        reconciled = aliased(XiaoCLifeEvent)
        query = (
            select(XiaoCLifeEvent)
            .where(
                XiaoCLifeEvent.identity_id == IDENTITY_ID,
                XiaoCLifeEvent.actual_tokens.is_(None),
                XiaoCLifeEvent.id.startswith("cycle:"),
                ~select(reconciled.id)
                .where(
                    reconciled.identity_id == XiaoCLifeEvent.identity_id,
                    reconciled.id == "reconciled:" + XiaoCLifeEvent.id,
                )
                .exists(),
            )
            .order_by(XiaoCLifeEvent.id)
            .limit(100)
        )
        cursor = data.get("usage_reconciliation_cursor", "")
        events = list(session.scalars(query.where(XiaoCLifeEvent.id > cursor)))
        if not events and cursor:
            events = list(session.scalars(query))
        # Persist progress before receipt I/O. Immutable reconciled facts never
        # consume the limit; unresolved facts rotate back into a later pass.
        data["usage_reconciliation_cursor"] = events[-1].id if events else ""
        for event in events:
            pending.append(
                {
                    **json.loads(event.details_json),
                    "cycle_id": event.id.removeprefix("cycle:"),
                    "domain": event.kind,
                    "active": False,
                }
            )
        return pending

    pending = _mutate(collect)
    resolved = 0
    for item in pending:
        steps = item.get("steps", [])
        actual = (
            0
            if not steps and item.get("outbound_journal_version") == 1
            else _verified_usage(steps, item["owner_user_id"])
        )
        if actual is None or not 0 <= actual <= item["reservation"]:
            continue

        def settle(
            current: dict[str, Any],
            session: Any,
            *,
            item: dict[str, Any] = item,
            steps: list[dict[str, Any]] = steps,
            actual: int = actual,
        ) -> bool:
            event_id = "reconciled:cycle:" + item["cycle_id"]
            if session.get(XiaoCLifeEvent, event_id) is not None:
                return False
            if item["active"]:
                running = current.get("active_cycle") or {}
                if running.get("cycle_id") != item["cycle_id"] or running.get("steps", []) != steps:
                    return False
                current["active_cycle"] = None
            budget = current["budget"]
            budget["reserved_tokens"] -= item["reservation"]
            budget["used_tokens"] += actual
            if item["domain"] == "exploration":
                budget["exploration_reserved_tokens"] -= item["reservation"]
                budget["exploration_tokens"] += actual
            current["unknown_usage"] = budget["reserved_tokens"] > 0
            current["last_status"] = "waiting"
            _event(
                session,
                event_id,
                kind="reconciliation",
                status="verified",
                summary="已核对原运行账本并结算模型用量，没有重新执行原调用。",
                evidence_refs=["cycle:" + item["cycle_id"]],
                actual_tokens=actual,
                details={"steps": item["steps"]},
            )
            return True

        resolved += int(_mutate(settle))
    return {"resolved": resolved, "waiting": len(pending) - resolved}


def reconcile_goals() -> dict[str, Any]:
    from modstore_server.xiaoc_life_cognition import portfolio_feedback

    snapshot = read_state()
    updates = []
    for goal in snapshot["goals"]:
        decision_id = goal.get("decision_id")
        if not decision_id:
            continue
        try:
            record = portfolio_status(decision_id, owner_user_id=snapshot["owner_user_id"])
        except PortfolioError:
            continue
        selected = record.get("plan", {}).get("selected", [])
        tasks = record.get("tasks", {})
        states = [tasks.get(key, {}).get("status", "pending") for key in selected]
        if record.get("halted"):
            status, label = "stopped", "原组合已停止"
        elif states and all(state == "completed" for state in states):
            status, label = (
                "execution_verified",
                "原员工执行回执已核验",
            )
        elif any(state in {"failed", "unknown"} for state in states):
            status, label = "blocked", "原任务已停止或回执待核对"
        elif record["status"] in {"approved", "executing"}:
            status, label = "approved", "原预算已批准，任务等待或正在由现有执行器推进"
        else:
            status, label = "awaiting_approval", "企业提案等待原审批流程"
        feedback = portfolio_feedback(record)
        receipt = digest(
            [
                decision_id,
                record["status"],
                states,
                record.get("halted", False),
                feedback["evidence_ref"],
            ]
        )
        if goal.get("execution_receipt") != receipt:
            updates.append((goal["id"], decision_id, status, label, receipt, feedback))

    def apply(data: dict[str, Any], session: Any) -> None:
        if data.get("owner_user_id") != snapshot.get("owner_user_id"):
            return
        for goal_id, decision_id, status, label, receipt, feedback in updates:
            target = next(
                (
                    goal
                    for goal in data["goals"]
                    if goal["id"] == goal_id and goal.get("decision_id") == decision_id
                ),
                None,
            )
            if target is None or target.get("execution_receipt") == receipt:
                continue
            target.update(
                status=status,
                execution_receipt=receipt,
                outcome_status=feedback["outcome_status"],
                outcome_feedback=feedback["metrics"],
                outcome_ref=feedback["evidence_ref"],
            )
            event_id = "execution:" + receipt
            if session.get(XiaoCLifeEvent, event_id) is None:
                _event(
                    session,
                    event_id,
                    kind="execution",
                    status=status,
                    summary=f"{target['title']}：{label}。{feedback['summary']}",
                    evidence_refs=[
                        f"portfolio:{decision_id}",
                        f"receipt:{receipt}",
                        feedback["evidence_ref"],
                    ],
                    details={"outcome_feedback": feedback},
                )

    if updates:
        _mutate(apply)
    from modstore_server.xiaoc_life_evolution import reconcile

    return {"observed": len(updates) + reconcile()}
