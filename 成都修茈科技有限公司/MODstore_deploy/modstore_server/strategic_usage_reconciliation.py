"""Reconcile original model liabilities; never replay a model or employee."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from modstore_server.db import db_base
from modstore_server.db.llm_chat import LlmClientRequest
from modstore_server.db.strategic import StrategicActionItem, StrategicDecision
from modstore_server.strategic_portfolio import (
    PortfolioError,
    _date,
    _json,
    digest,
    mutate_portfolio,
    require_authorization,
)

logger = logging.getLogger(__name__)
_READBACK_ERRORS = (
    PortfolioError,
    SQLAlchemyError,
    ValueError,
    KeyError,
    TypeError,
    ImportError,
    OverflowError,
)


def bind_transport(reservation: dict[str, Any]) -> dict[str, Any]:
    """Commit the gateway identity before the first byte can leave the process."""
    from modstore_server.llm_usage_readback import transport_identity
    from modstore_server.strategic_company_resources import transaction

    started = datetime.now(UTC)
    binding = {
        "request_id": reservation["request_id"],
        "provider": reservation["provider"],
        "model": reservation["model"],
        "started_at": started.isoformat(),
        "deadline": (started + timedelta(seconds=reservation["timeout_seconds"])).isoformat(),
        **transport_identity(reservation["provider"]),
    }
    if reservation.get("kind") == "strategic_planning":
        binding["owner_user_id"] = reservation["owner_user_id"]

        def persist(session: Any) -> None:
            row = session.scalar(
                select(LlmClientRequest).where(
                    LlmClientRequest.user_id == reservation["owner_user_id"],
                    LlmClientRequest.client_request_id == reservation["request_id"],
                )
            )
            if row is None or row.state != "processing":
                raise PortfolioError("planning transport reservation is no longer pending")
            record = json.loads(row.done_json or "{}")
            if record.get("transport_binding"):
                raise PortfolioError("planning transport already admitted")
            previous = row.done_json
            record["transport_binding"] = binding
            record["transport_binding_sha256"] = digest(binding)
            result = session.execute(
                update(LlmClientRequest)
                .where(
                    LlmClientRequest.id == row.id,
                    LlmClientRequest.done_json == previous,
                )
                .values(done_json=_json(record))
            )
            if result.rowcount != 1:
                raise PortfolioError("planning transport admission changed")

        transaction(persist)
    else:
        binding.update(
            decision_id=reservation["decision_id"],
            opportunity_id=reservation["opportunity_id"],
            lease_token=reservation["lease_token"],
        )

        def persist_call(
            _row: Any, proposal: dict[str, Any], state: dict[str, Any], _session: Any
        ) -> None:
            task = state.get("tasks", {}).get(reservation["opportunity_id"], {})
            call = task.get("calls", {}).get(reservation["request_id"], {})
            if (
                task.get("lease_token") != reservation["lease_token"]
                or call.get("status") != "pending"
                or call.get("transport_binding")
                or (call.get("provider"), call.get("model"))
                != (binding["provider"], binding["model"])
            ):
                raise PortfolioError("model transport reservation changed or already admitted")
            binding["owner_user_id"] = proposal["owner_user_id"]
            call["transport_binding"] = binding
            call["transport_binding_sha256"] = digest(binding)

        mutate_portfolio(reservation["decision_id"], persist_call)
    return binding


def _finish_measured_task(
    decision_id: str, task_id: str, state: dict[str, Any], session: Any
) -> None:
    from modstore_server.strategic_execution_receipts import evaluate_execution_receipt
    from modstore_server.strategic_portfolio_runtime import _action_id

    task = state["tasks"][task_id]
    calls = list(task.get("calls", {}).values())
    if not calls or any(call["status"] != "settled" for call in calls):
        return
    task.update(
        actual_tokens=sum(call["actual_tokens"] for call in calls),
        accrued_cost_cents=sum(call["accrued_cost_cents"] for call in calls),
    )
    original = task.get("execution_receipt")
    if (
        task.get("status") != "unknown"
        or not isinstance(original, dict)
        or digest(original) != task.get("result_sha256")
    ):
        return
    result = evaluate_execution_receipt(original)
    if result.status not in {"completed", "failed"} or "compute_seconds" not in task:
        return
    task.update(
        status=result.status,
        reason=result.reason,
        completed_at=datetime.now(UTC).isoformat(),
    )
    action = session.scalar(
        select(StrategicActionItem).where(
            StrategicActionItem.action_id == _action_id(decision_id, task_id)
        )
    )
    if action is not None:
        action.status = "completed" if result.status == "completed" else "blocked"
        action.completed_at = datetime.now(UTC)
        action.updated_at = datetime.now(UTC)
        action.result_json, action.block_reason = _json(task), result.reason


def _apply_portfolio(
    decision_id: str,
    opportunity_id: str,
    request_id: str,
    binding: dict[str, Any],
    result: dict[str, Any],
) -> bool:
    from modstore_server.strategic_portfolio_usage import _settle_call

    def apply(row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any) -> bool:
        task = state.get("tasks", {}).get(opportunity_id, {})
        call = task.get("calls", {}).get(request_id)
        if (
            not call
            or call.get("status") not in {"pending", "unknown"}
            or call.get("transport_binding") != binding
            or call.get("transport_binding_sha256") != digest(binding)
            or binding.get("request_id") != request_id
            or binding.get("decision_id") != decision_id
            or binding.get("opportunity_id") != opportunity_id
            or (call.get("provider"), call.get("model"))
            != (binding.get("provider"), binding.get("model"))
            or task.get("lease_token") != binding["lease_token"]
            or proposal["owner_user_id"] != binding["owner_user_id"]
        ):
            return False
        prior_stop = (state.get("halted"), state.get("stop_reason"))
        _settle_call(call, state, result)
        if call.get("status") != "settled":
            return False
        call["readback"] = result["readback"]
        _finish_measured_task(decision_id, opportunity_id, state, session)
        if prior_stop[0] and prior_stop[1] != "upstream_usage_unknown":
            state.update(halted=True, stop_reason=prior_stop[1])
        # Settlement is not renewed authority. Only an otherwise live mandate
        # can leave a usage-only hold, and unresolved execution remains stopped.
        else:
            _resume_usage_hold(row, proposal, state, session)
        return True

    return mutate_portfolio(decision_id, apply)


def _resume_usage_hold(
    row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any
) -> None:
    if state.get("stop_reason") == "upstream_usage_unknown" and all(
        item.get("status") in {"completed", "failed", "waiting", "queued"}
        and all(value["status"] == "settled" for value in item.get("calls", {}).values())
        for item in state["tasks"].values()
    ):
        failures = sum(item.get("status") == "failed" for item in state["tasks"].values())
        if failures >= proposal["limits"]["max_failures"]:
            state.update(halted=True, stop_reason="failure_guardrail")
        else:
            prospective = {**state, "halted": False, "stop_reason": ""}
            try:
                require_authorization(row, proposal, prospective, session=session)
            except PortfolioError:
                pass
            else:
                state.update(halted=False, stop_reason="")


def _due(record: dict[str, Any], *, pending: bool) -> bool:
    binding = record.get("transport_binding")
    try:
        if (
            not isinstance(binding, dict)
            or record.get("transport_binding_sha256") != digest(binding)
            or not all(isinstance(binding.get(key), str) for key in ("started_at", "deadline"))
        ):
            return False
        started, deadline = _date(binding["started_at"]), _date(binding["deadline"])
        return started <= deadline and (not pending or deadline <= datetime.now(UTC))
    except (ValueError, KeyError, TypeError, OverflowError):
        return False


def _next_check(previous: datetime | str | None) -> datetime:
    """Rotate fairly even when a clock repeats or moves behind a saved stamp."""
    now = datetime.now(UTC)
    if isinstance(previous, str):
        try:
            previous = _date(previous) if previous else None
        except PortfolioError:
            previous = None
    return max(now, previous.replace(tzinfo=UTC) + timedelta(microseconds=1)) if previous else now


def _rotate(session: Any, row: Any) -> bool:
    model = type(row)
    changed = session.execute(
        update(model)
        .where(model.id == row.id, model.updated_at == row.updated_at)
        .values(updated_at=_next_check(row.updated_at))
        .execution_options(synchronize_session=False)
    )
    return bool(changed.rowcount == 1)


def reconcile_pending_usage(*, limit: int = 10) -> dict[str, int]:
    """Bounded scheduler consumer also runs while the life loop is paused."""
    from modstore_server.llm_usage_readback import read_usage
    from modstore_server.strategic_portfolio_usage import _settle_planning

    limit = max(1, min(limit, 100))
    pending: list[dict[str, Any]] = []
    scanned = []
    with db_base.get_session_factory()() as session:
        portfolios = session.scalars(
            select(StrategicDecision)
            .where(
                StrategicDecision.scope == "strategy_portfolio",
                StrategicDecision.execution_result_json.contains('"transport_binding"'),
            )
            .order_by(StrategicDecision.updated_at, StrategicDecision.decision_id)
            .limit(limit)
        )
        for candidate in portfolios:
            row = cast(Any, candidate)
            # Advance before parsing or upstream I/O. A corrupt or unsupported
            # original ledger retains its hold without starving the next one.
            if not _rotate(session, row):
                continue
            try:
                record = json.loads(row.execution_result_json or "{}")
                if not isinstance(record, dict) or not isinstance(record.get("tasks", {}), dict):
                    raise ValueError("invalid portfolio execution ledger")
                tasks = record.get("tasks", {})
            except _READBACK_ERRORS:
                logger.warning("Invalid original usage ledger: %s", row.decision_id, exc_info=True)
                continue
            scanned.append(row.decision_id)
            calls = sorted(
                (
                    (task_id, request_id, call)
                    for task_id, task in tasks.items()
                    if isinstance(task, dict) and isinstance(task.get("calls", {}), dict)
                    for request_id, call in task.get("calls", {}).items()
                    if isinstance(call, dict)
                ),
                key=lambda item: (str(item[2].get("readback_checked_at", "")), item[0], item[1]),
            )
            for task_id, request_id, call in calls:
                binding = call.get("transport_binding")
                if call.get("status") in {"pending", "unknown"} and _due(
                    call, pending=call["status"] == "pending"
                ):
                    pending.append(
                        {
                            "decision_id": row.decision_id,
                            "opportunity_id": task_id,
                            "request_id": request_id,
                            "binding": binding,
                        }
                    )
                if len(pending) >= limit:
                    break
            if len(pending) >= limit:
                break
        for planning_row in session.scalars(
            select(LlmClientRequest)
            .where(
                LlmClientRequest.client_request_id.startswith("strategy-discovery-"),
                LlmClientRequest.state.in_(("processing", "unknown")),
            )
            .order_by(LlmClientRequest.updated_at, LlmClientRequest.id)
            .limit(limit)
        ):
            if not _rotate(session, planning_row):
                continue
            try:
                record = json.loads(planning_row.done_json or "{}")
                if not isinstance(record, dict):
                    raise ValueError("invalid planning usage ledger")
            except _READBACK_ERRORS:
                logger.warning(
                    "Invalid original planning ledger: %s", planning_row.id, exc_info=True
                )
                continue
            binding = record.get("transport_binding")
            if (
                record.get("request_id") == planning_row.client_request_id
                and record.get("owner_user_id") == planning_row.user_id
                and record.get("status") != "exceeded"
                and _due(record, pending=planning_row.state == "processing")
            ):
                pending.append({"planning": record, "binding": binding})
        session.commit()
    settled = 0
    for item in pending:
        try:
            if "planning" not in item:

                def touch(
                    _row: Any,
                    _proposal: dict[str, Any],
                    state: dict[str, Any],
                    _session: Any,
                ) -> bool:
                    call = (
                        state.get("tasks", {})
                        .get(item["opportunity_id"], {})
                        .get("calls", {})
                        .get(item["request_id"], {})
                    )
                    if (
                        call.get("status") not in {"pending", "unknown"}
                        or call.get("transport_binding") != item["binding"]
                        or call.get("transport_binding_sha256") != digest(item["binding"])
                    ):
                        return False
                    previous = call.get("readback_checked_at")
                    call["readback_checked_at"] = _next_check(
                        previous if isinstance(previous, str) else None
                    ).isoformat()
                    return True

                if not mutate_portfolio(item["decision_id"], touch):
                    continue
            result = read_usage(item["binding"])
            if result is None:
                continue
            if "planning" in item:
                settled += int(
                    _settle_planning(item["planning"], result, reconciliation=item["binding"])
                )
            else:
                settled += int(
                    _apply_portfolio(
                        item["decision_id"],
                        item["opportunity_id"],
                        item["request_id"],
                        item["binding"],
                        result,
                    )
                )
        except _READBACK_ERRORS:
            # Lost connectivity, missing upstream schema, invalid provenance or
            # a concurrent change retain the original hold and can be read later.
            logger.warning("Original usage remains unresolved", exc_info=True)
    for decision_id in scanned:
        try:
            mutate_portfolio(decision_id, _resume_usage_hold)
        except _READBACK_ERRORS:
            logger.warning("Original portfolio remains held: %s", decision_id, exc_info=True)
    return {"checked": len(pending), "settled": settled}
