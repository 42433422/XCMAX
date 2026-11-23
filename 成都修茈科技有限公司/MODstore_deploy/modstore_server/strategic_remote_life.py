"""Explicitly approved engineering phases retain one original life reservation.

The cognition lease remains 300 seconds. Only the persisted remote work order
can use the separately approved absolute task deadline; it cannot claim another
cycle, task, report, or local worker. Native phase receipts still own renewal.
"""

from __future__ import annotations

import contextvars
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from modstore_server.db.xiaoc_life import XiaoCLifeState
from modstore_server.strategic_portfolio import PortfolioError, _date, _json, digest
from modstore_server.xiaoc_life_policy import IDENTITY_ID, LifePolicyError

MODE = "persistent_phases"
SCHEMA = "strategic-life-phases/v1"
_REMOTE: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "strategic_remote_life", default=None
)


def register(
    session: Session,
    row: Any,
    proposal: dict[str, Any],
    state: dict[str, Any],
    request: dict[str, Any],
) -> None:
    """Register in the existing dispatch transaction, never a nested commit."""
    from modstore_server import xiaoc_life_store as life
    from modstore_server.strategic_company_resources import active_budget

    option = request.get("life_lease")
    if option is None:
        return
    binding = request["binding"]
    claim = binding.get("life_scope")
    if (
        not isinstance(option, dict)
        or set(option) != {"mode", "expires_at"}
        or option.get("mode") != MODE
        or request["kind"] != "github_opencode_workspace"
        or not str(proposal["period"]).startswith("xiaoc-life:")
        or not claim
        or row.decided_by != "user"
        or state.get("authorization", {}).get("user_id") != binding["owner_user_id"]
        or state["authorization"].get("proposal_sha256") != proposal["proposal_sha256"]
    ):
        raise PortfolioError("persistent phases require explicit original administrator approval")
    persisted = session.get(XiaoCLifeState, IDENTITY_ID)
    if persisted is None:
        raise PortfolioError("persistent phases require the original life cycle")
    data = json.loads(persisted.state_json)
    active = data.get("active_cycle") or {}
    if (
        any(active.get(key) != value for key, value in claim.items())
        or active.get("remote_task")
        or active.get("policy_revision") != data["revision"]
        or data["paused"]
        or _date(active["deadline"]) <= life.utcnow()
    ):
        raise PortfolioError("persistent phases cannot replace or revive an original life lease")
    budget_id = proposal["limits"].get("company_budget_id", "")
    company = active_budget(session, binding["owner_user_id"], budget_id) if budget_id else None
    if company is None:
        raise PortfolioError("persistent phases require the original approved company budget")
    expiry = _date(str(option["expires_at"]))
    limit = min(
        _date(data["policy"]["authorization_expires_at"]),
        _date(proposal["limits"]["expires_at"]),
        _date(company[1]["limits"]["expires_at"]),
    )
    if not life.utcnow() < expiry <= limit:
        raise PortfolioError("persistent phase expiry exceeds the original approved authorities")
    request["deadline"] = expiry.isoformat()
    active["remote_task"] = {
        "schema": SCHEMA,
        "request_id": binding["receipt_id"],
        "request_sha256": digest(request),
        "decision_id": binding["decision_id"],
        "opportunity_id": binding["opportunity_id"],
        "binding_id": binding["binding_id"],
        "owner_user_id": binding["owner_user_id"],
        "proposal_sha256": proposal["proposal_sha256"],
        "company_budget_id": budget_id,
        "company_proposal_sha256": company[1]["proposal_sha256"],
        "repository": request["repository"],
        "source_sha": request["source_sha"],
        "life_scope": claim,
        "expires_at": expiry.isoformat(),
    }
    changed = cast(
        CursorResult[Any],
        session.execute(
            update(XiaoCLifeState)
            .where(
                XiaoCLifeState.identity_id == IDENTITY_ID,
                XiaoCLifeState.version == persisted.version,
            )
            .values(state_json=_json(data), version=persisted.version + 1, updated_at=life.utcnow())
            .execution_options(synchronize_session=False)
        ),
    ).rowcount
    if changed != 1:
        raise PortfolioError("life approval changed during original remote registration")


def _registered(data: dict[str, Any]) -> dict[str, Any] | None:
    active = data.get("active_cycle") or {}
    record = active.get("remote_task")
    if (
        not isinstance(record, dict)
        or record.get("schema") != SCHEMA
        or record.get("owner_user_id") != data.get("owner_user_id")
        or active.get("policy_revision") != data["revision"]
        or not record.get("life_scope")
        or any(active.get(key) != value for key, value in record["life_scope"].items())
    ):
        return None
    return record


def waiting_deadline(data: dict[str, Any]) -> datetime:
    """An outstanding approved remote task remains reserved, without a new cycle."""
    record = _registered(data)
    return (
        min(_date(record["expires_at"]), _date(data["policy"]["authorization_expires_at"]))
        if record
        else _date(data["active_cycle"]["deadline"])
    )


def execution_deadline(data: dict[str, Any], claim: dict[str, Any]) -> datetime:
    record = _registered(data)
    if record and _REMOTE.get() == record and record["life_scope"] == claim:
        return waiting_deadline(data)
    return _date(data["active_cycle"]["deadline"])


def require_step(kind: str, details: dict[str, Any]) -> None:
    record = _REMOTE.get()
    if record and (
        kind != "model"
        or details.get("decision_id") != record["decision_id"]
        or details.get("opportunity_id") != record["opportunity_id"]
    ):
        raise LifePolicyError("持久远程授权只能登记原工程任务的模型调用")


def require_portfolio(proposal: dict[str, Any], decision_id: str) -> None:
    record = _REMOTE.get()
    if record and (
        decision_id != record["decision_id"]
        or proposal["proposal_sha256"] != record["proposal_sha256"]
        or proposal["owner_user_id"] != record["owner_user_id"]
    ):
        raise LifePolicyError("持久远程授权不能用于另一批准组合")


def require_new_task() -> None:
    if _REMOTE.get() is not None:
        raise LifePolicyError("持久远程授权只能恢复原任务，不能领取新任务")


@contextmanager
def execution_scope(request: dict[str, Any]) -> Iterator[None]:
    from modstore_server import xiaoc_life_store as life
    from modstore_server.strategic_company_resources import active_budget

    with life.get_session_factory()() as session:
        persisted = session.get(XiaoCLifeState, IDENTITY_ID)
        data = json.loads(persisted.state_json) if persisted else {}
        record = _registered(data)
        if (
            request["kind"] != "github_opencode_workspace"
            or not record
            or record["request_sha256"] != digest(request)
            or record["life_scope"] != request["binding"].get("life_scope")
        ):
            raise PortfolioError("persistent scope is not the original registered work order")
        company = active_budget(session, record["owner_user_id"], record["company_budget_id"])
        if company is None or company[1]["proposal_sha256"] != record["company_proposal_sha256"]:
            raise PortfolioError("persistent scope company approval changed")
    token = _REMOTE.set(record)
    try:
        with life.life_execution_scope(record["life_scope"]):
            yield
    finally:
        _REMOTE.reset(token)
