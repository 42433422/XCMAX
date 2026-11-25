"""Read back existing execution evidence even while autonomous work is paused."""

from __future__ import annotations

import json
from contextlib import nullcontext
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import aliased

from modstore_server.db.llm_chat import LlmClientRequest
from modstore_server.db.xiaoc_life import XiaoCLifeEvent, XiaoCLifeState
from modstore_server.strategic_portfolio import PortfolioError, digest, portfolio_status
from modstore_server.xiaoc_life_checkpoint import (
    recover_checkpoint,
    zero_usage_checkpoint_compatible,
)
from modstore_server.xiaoc_life_policy import IDENTITY_ID, utcnow
from modstore_server.xiaoc_life_store import (
    _event,
    _mutate,
    get_session_factory,
    read_state,
    try_cycle_lock,
)


def _verified_usage(steps: list[dict[str, Any]], owner: int) -> int | None:
    if not steps:
        return None
    total = 0
    portfolios: set[str] = set()
    verified_calls: set[tuple[str, str, str]] = set()
    for step in steps:
        if step["kind"] != "portfolio":
            continue
        decision_id = step["decision_id"]
        if decision_id in portfolios or "before_call_ids" not in step:
            return None
        portfolios.add(decision_id)
        try:
            record = portfolio_status(decision_id, owner_user_id=owner)
        except PortfolioError:
            return None
        tasks = record.get("tasks", {})
        before_calls = set(step["before_call_ids"])
        # An existing task can receive additional calls when resumed; task IDs
        # alone are not sufficient to identify the current cycle's consumption.
        if any(task.get("status") not in {"completed", "failed"} for task in tasks.values()):
            return None
        for task_id, task in tasks.items():
            for call_id, call in task.get("calls", {}).items():
                if call_id in before_calls:
                    continue
                actual = call.get("actual_tokens")
                if call.get("status") != "settled" or type(actual) is not int or actual < 0:
                    return None
                verified_calls.add((decision_id, task_id, call_id))
                total += actual

    direct_calls: set[str] = set()
    with get_session_factory()() as session:
        for step in steps:
            if step["kind"] == "portfolio":
                continue
            if step["kind"] != "model":
                return None
            request_id = step["request_id"]
            if step.get("decision_id"):
                # Every journaled portfolio call must have an original settled
                # ledger entry, including calls on an already-known task.
                if (
                    step["decision_id"],
                    step.get("opportunity_id"),
                    request_id,
                ) not in verified_calls:
                    return None
                continue
            if request_id in direct_calls:
                continue
            direct_calls.add(request_id)
            row = session.scalar(
                select(LlmClientRequest).where(
                    LlmClientRequest.user_id == owner,
                    LlmClientRequest.client_request_id == request_id,
                )
            )
            if row is None or row.state != "completed":
                return None
            receipt = json.loads(row.done_json or "{}")
            actual = receipt.get("actual_tokens")
            if receipt.get("status") != "settled" or type(actual) is not int or actual < 0:
                return None
            total += actual
    return total


def reconcile_usage() -> dict[str, int]:
    """Resolve only the original persisted receipt, never replay an uncertain call."""
    from modstore_server.strategic_remote_life import waiting_deadline
    from modstore_server.strategic_usage_reconciliation import reconcile_pending_usage

    reconcile_pending_usage()

    def pending_active(data: dict[str, Any]) -> dict[str, Any] | None:
        active = data.get("active_cycle")
        if not active or not (active.get("awaiting_worker") or waiting_deadline(data) <= utcnow()):
            return None
        return {
            "cycle_id": active["cycle_id"],
            "lease_token": active["lease_token"],
            "domain": active["domain"],
            "reservation": active["reserved_tokens"],
            "steps": active.get("steps", []),
            "owner_user_id": active["owner_user_id"],
            "outbound_journal_version": active.get("outbound_journal_version"),
            "outbound_attempted": bool(active.get("outbound_attempted")),
            "policy_revision": active["policy_revision"],
            "graph_checkpoints": active.get("graph_checkpoints", {}),
            "native_closeout": active.get("native_closeout"),
            "active": True,
        }

    def collect(data: dict[str, Any], session: Any) -> list[dict[str, Any]]:
        active = pending_active(data)
        pending = [active] if active else []
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

    def resolve(item: dict[str, Any]) -> bool:
        steps = item.get("steps", [])
        if not isinstance(steps, list):
            return False
        if not steps:
            # A returned node may contradict an empty or incomplete journal.
            # Keep its reservation rather than inventing a verified zero charge.
            actual = (
                0
                if item.get("outbound_journal_version") == 1
                and not item.get("outbound_attempted")
                and zero_usage_checkpoint_compatible(
                    item.get("graph_checkpoints", {}),
                    cycle_id=item["cycle_id"],
                    owner_user_id=item.get("owner_user_id", 0),
                    policy_revision=item.get("policy_revision", 0),
                )
                else None
            )
        else:
            actual = _verified_usage(steps, item["owner_user_id"])
        if actual is None or not 0 <= actual <= item["reservation"]:
            return False
        verified_actual = actual

        def settle(current: dict[str, Any], session: Any) -> bool:
            event_id = "reconciled:cycle:" + item["cycle_id"]
            if session.get(XiaoCLifeEvent, event_id) is not None:
                return False
            if item["active"]:
                if pending_active(current) != item:
                    return False
                current["active_cycle"] = None
            budget = current["budget"]
            budget["reserved_tokens"] -= item["reservation"]
            budget["used_tokens"] += verified_actual
            if item["domain"] == "exploration":
                budget["exploration_reserved_tokens"] -= item["reservation"]
                budget["exploration_tokens"] += verified_actual
            current["unknown_usage"] = budget["reserved_tokens"] > 0
            current["last_status"] = "waiting"
            checkpoint = None
            if item.get("graph_checkpoints"):
                checkpoint = recover_checkpoint(
                    item["graph_checkpoints"],
                    cycle_id=item["cycle_id"],
                    owner_user_id=item.get("owner_user_id", 0),
                    policy_revision=item.get("policy_revision", 0),
                    actual_tokens=verified_actual,
                )
            _event(
                session,
                event_id,
                kind="reconciliation",
                status="verified",
                summary="已核对原运行账本并结算模型用量，没有重新执行原调用。",
                evidence_refs=["cycle:" + item["cycle_id"]],
                actual_tokens=verified_actual,
                details={
                    "steps": item["steps"],
                    **({"graph_checkpoint_recovery": checkpoint} if checkpoint else {}),
                },
            )
            return True

        return _mutate(settle)

    pending = _mutate(collect)
    resolved = 0
    for item in pending:
        lock = try_cycle_lock(item["cycle_id"]) if item["active"] else nullcontext(True)
        with lock as acquired:
            if not acquired:
                continue
            if item["active"]:
                with get_session_factory()() as session:
                    row = session.get(XiaoCLifeState, IDENTITY_ID)
                    assert row is not None
                    fresh = pending_active(json.loads(row.state_json))
                if (
                    fresh is None
                    or fresh["cycle_id"] != item["cycle_id"]
                    or fresh["lease_token"] != item["lease_token"]
                    or fresh["native_closeout"] is not None
                ):
                    continue
                item = fresh
            resolved += int(resolve(item))
    return {"resolved": resolved, "waiting": len(pending) - resolved}


def reconcile_goals() -> dict[str, Any]:
    from modstore_server.xiaoc_goal_management import portfolio_goal_closed, project_goal_steps
    from modstore_server.xiaoc_life_cognition import goal_review_projection, portfolio_feedback
    from modstore_server.xiaoc_life_reflection import (
        candidate_id,
        candidate_refs,
        review_experiences,
    )

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
        closed = portfolio_goal_closed(record, now=utcnow())
        step_projection = project_goal_steps(goal, record)
        all_steps_verified = (
            not step_projection or step_projection.get("all_steps_verified") is True
        )
        if closed:
            status, label = "stopped", "原组合已停止"
        elif states and all(state == "completed" for state in states):
            if all_steps_verified:
                status, label = "execution_verified", "原员工执行回执已核验"
            else:
                status, label = "blocked", "原子目标或依赖交接回执尚未完整核验"
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
                *([step_projection] if step_projection else []),
                *(["authority_closed"] if closed and not record.get("halted") else []),
            ]
        )
        review = goal_review_projection(
            owner=snapshot["owner_user_id"],
            goal_id=goal["id"],
            decision_id=decision_id,
            status=status,
            feedback=feedback,
        )
        reflection, candidates = review_experiences(record)
        if step_projection and not all_steps_verified:
            candidates = []
        if (
            goal.get("execution_receipt") != receipt
            or goal.get("goal_review") != review
            or (step_projection and goal.get("step_projection") != step_projection)
            or candidates
        ):
            previous = (
                goal.get("execution_receipt"),
                goal.get("outcome_ref"),
                goal.get("status"),
                goal.get("goal_review"),
                goal.get("step_projection"),
            )
            updates.append(
                (
                    goal["id"],
                    decision_id,
                    status,
                    label,
                    receipt,
                    feedback,
                    previous,
                    review,
                    reflection,
                    candidates,
                    step_projection,
                )
            )

    def apply(data: dict[str, Any], session: Any) -> int:
        if data.get("owner_user_id") != snapshot.get("owner_user_id"):
            return 0
        changed = 0
        registered: set[str] = set()
        for (
            goal_id,
            decision_id,
            status,
            label,
            receipt,
            feedback,
            previous,
            review,
            reflection,
            candidates,
            step_projection,
        ) in updates:
            target = next(
                (
                    goal
                    for goal in data["goals"]
                    if goal["id"] == goal_id and goal.get("decision_id") == decision_id
                ),
                None,
            )
            if target is None:
                continue
            if previous != (
                target.get("execution_receipt"),
                target.get("outcome_ref"),
                target.get("status"),
                target.get("goal_review"),
                target.get("step_projection"),
            ):
                continue  # A newer reconciliation or live cycle already changed this goal.
            for candidate in candidates:
                experience_id = candidate_id(candidate)
                if experience_id in registered:
                    continue
                registered.add(experience_id)
                if session.get(XiaoCLifeEvent, experience_id) is None:
                    _event(
                        session,
                        experience_id,
                        kind="experience_candidate",
                        status="pending_review",
                        summary="原任务独立测量形成待审核经验；未采纳。",
                        evidence_refs=candidate_refs(candidate),
                        details={
                            "owner_user_id": snapshot["owner_user_id"],
                            "goal_id": goal_id,
                            "source_execution_event_id": "execution:" + receipt,
                            "outcome_ref": feedback["evidence_ref"],
                            "candidate": candidate,
                            "candidate_sha256": digest(candidate),
                        },
                    )
            if (
                target.get("execution_receipt") == receipt
                and target.get("goal_review") == review
                and (not step_projection or target.get("step_projection") == step_projection)
            ):
                continue
            target.update(
                status=status,
                execution_receipt=receipt,
                outcome_status=feedback["outcome_status"],
                outcome_feedback=feedback["metrics"],
                outcome_ref=feedback["evidence_ref"],
                goal_review=review,
            )
            if step_projection:
                target["step_projection"] = step_projection
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
                    details={
                        "outcome_feedback": feedback,
                        "business_reflection": reflection,
                        "owner_user_id": snapshot["owner_user_id"],
                        "goal_id": goal_id,
                        "decision_id": decision_id,
                    },
                )
            changed += 1
        return changed

    observed = _mutate(apply) if updates else 0
    from modstore_server.xiaoc_life_evolution import reconcile

    return {"observed": observed + reconcile()}
