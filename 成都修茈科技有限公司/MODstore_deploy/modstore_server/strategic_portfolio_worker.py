"""Restore the original XiaoC lease around an existing durable local worker.

The queue binding carries authority identifiers only. It cannot renew a lease,
replace a policy revision, replay a worker, or release an uncertain model hold.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any, Iterator

from sqlalchemy import select

from modstore_server.db.strategic import StrategicActionItem
from modstore_server.strategic_portfolio import (
    PortfolioError,
    _date,
    _json,
    digest,
    mutate_portfolio,
)

_LIFE_FIELDS = {
    "cycle_id",
    "lease_token",
    "owner_user_id",
    "domain",
    "reserved_tokens",
    "policy_revision",
    "deadline",
}


def capture_life_worker_scope() -> dict[str, Any] | None:
    from modstore_server.xiaoc_life_store import current_life_claim

    return current_life_claim()


def _cancel_waiting_worker(binding: dict[str, Any], *, owner_user_id: int) -> bool:
    """Persist cancellation only if this exact queue item has not started."""
    from modstore_server.xiaoc_life_store import cycle_active

    def cancel(_row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any) -> bool:
        key = binding["opportunity_id"]
        task = state.get("tasks", {}).get(key, {})
        if task.get("status") != "waiting" or task.get("worker_binding") != binding:
            return False
        now = datetime.now(UTC)
        if (
            cycle_active(binding["life_scope"])
            and _date(task["deadline"]) > now
            and _date(proposal["limits"]["expires_at"]) > now
        ):
            return False
        calls = list(task.get("calls", {}).values())
        if any(
            call.get("status") != "settled"
            or type(call.get("actual_tokens")) is not int
            or call["actual_tokens"] < 0
            or type(call.get("accrued_cost_cents")) is not int
            or call["accrued_cost_cents"] < 0
            for call in calls
        ):
            return False
        reason = "life_worker_authorization_revoked_before_start"
        receipt = {
            "status": "cancelled",
            "worker_receipt_id": binding["receipt_id"],
            "reason": reason,
            "worker_started": False,
        }
        task.update(
            status="failed",
            completed_at=now.isoformat(),
            reason=reason,
            actual_tokens=sum(call["actual_tokens"] for call in calls),
            accrued_cost_cents=sum(call["accrued_cost_cents"] for call in calls),
            execution_receipt=receipt,
            result_sha256=digest(receipt),
        )
        state.update(halted=True, stop_reason=reason)
        action_id = "portfolio-" + digest([binding["decision_id"], key])[:32]
        action = session.scalar(
            select(StrategicActionItem).where(StrategicActionItem.action_id == action_id)
        )
        if action is not None:
            action.status = "blocked"
            action.completed_at = action.updated_at = now
            action.block_reason = reason
            action.result_json = _json(task)
        return True

    try:
        return bool(mutate_portfolio(binding["decision_id"], cancel, owner_user_id=owner_user_id))
    except PortfolioError:
        # A forged/missing identity must not mutate another queue item. The
        # original admission failure still propagates from the caller.
        return False


@contextlib.contextmanager
def restore_life_worker_scope(binding: dict[str, Any], *, owner_user_id: int) -> Iterator[None]:
    from modstore_server.xiaoc_life_policy import MINIMUM_LEVEL, LifePolicyError
    from modstore_server.xiaoc_life_store import life_execution_scope

    if binding.get("adapter") in {"github_opencode_report", "github_opencode_workspace"}:
        raise PortfolioError(
            "remote work requires its native adapter, never local queue cancellation"
        )
    claim = binding.get("life_scope")
    if claim is None:
        yield
        return
    if (
        not isinstance(claim, dict)
        or set(claim) != _LIFE_FIELDS
        or type(claim.get("owner_user_id")) is not int
        or claim["owner_user_id"] != owner_user_id
        or binding.get("owner_user_id") != owner_user_id
        or claim.get("domain") not in MINIMUM_LEVEL
    ):
        raise PortfolioError("life worker scope does not match its original owner and lease")
    try:
        with life_execution_scope(claim):
            yield
    except LifePolicyError as exc:
        _cancel_waiting_worker(binding, owner_user_id=owner_user_id)
        raise PortfolioError(str(exc)) from exc
    except PortfolioError:
        _cancel_waiting_worker(binding, owner_user_id=owner_user_id)
        raise
