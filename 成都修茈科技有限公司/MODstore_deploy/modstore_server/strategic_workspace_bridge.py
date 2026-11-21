"""Attach one approved Retort work order to its existing portfolio lease.

Retort and the incident team still own dispatch, publication, acceptance and
delivery. This adapter only binds their original request to the shared budget.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from modstore_server import strategic_remote_bridge as remote
from modstore_server.db.mac_control import MacControlTask
from modstore_server.models import RetortEvolutionRun
from modstore_server.para_execution_isolation import feedback_allocation_isolated
from modstore_server.strategic_portfolio import PortfolioError, _date, require_authorization

KIND = "github_opencode_workspace"
ACTOR = "service:strategy-workspace"
SCHEMA = "strategic-workspace/v1"
ACTIVE = {"waiting_execution", "waiting_credential_isolation"}


def original(session: Any, request: dict[str, Any], *, active: bool = False):
    """Verify the original dispatch approval, including its immutable private plan."""
    from modstore_server.integrations.repository_packages import load_repository_module

    row = session.get(RetortEvolutionRun, request["original_request_id"])
    if row is None or row.user_id != request["binding"]["owner_user_id"]:
        raise PortfolioError("workspace original owner or request changed")
    protocol, effects = json.loads(row.protocol_json), json.loads(row.effects_json)
    approval = effects.get("authorization") or {}
    contract = load_repository_module("retort_engine.evolution_contract")
    expected = contract.digest(
        {
            "protocol": protocol,
            "plan": effects.get("plan"),
            "optimization": effects.get("optimization"),
        }
    )
    if (
        protocol.get("request_id") != row.id
        or protocol.get("repository") != request["repository"]
        or protocol.get("source_sha") != request["source_sha"]
        or protocol.get("protocol_digest") != request["protocol_digest"]
        or approval.get("approved") is not True
        or type(approval.get("actor_id")) is not int
        or approval["actor_id"] <= 0
        or approval.get("digest") != expected
        or expected != request["approval_digest"]
        or (active and row.status not in ACTIVE)
    ):
        raise PortfolioError("workspace original approval or frozen source changed")
    return row, protocol, effects


def authorized(row, proposal, state, saved, request, session):
    from modstore_server.strategic_company_resources import require_company_authorization

    require_authorization(row, proposal, state)
    if not proposal["limits"].get("company_budget_id"):
        raise PortfolioError("engineering execution requires its approved company budget")
    require_company_authorization(proposal, session)
    if saved["status"] not in {"running", "waiting"} or _date(request["deadline"]) <= datetime.now(
        UTC
    ):
        raise PortfolioError("workspace portfolio lease is no longer active")
    original(session, request, active=True)


def attach_workspace(task: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.mac_control_dispatch_api import _configured_digests
    from modstore_server.para_execution_isolation import feedback_executor_configured
    from modstore_server.strategic_execution_contract import freeze_execution

    if (
        os.environ.get("MODSTORE_STRATEGIC_WORKSPACES_ENABLED") != "1"
        or not _configured_digests()
        or not feedback_executor_configured()
    ):
        raise PortfolioError("strategic engineering worker is not configured")
    freeze_execution(task["owner_user_id"], task)
    spec = (task.get("input_data") or {}).get("remote_execution")
    extra = {"original_request_id", "protocol_digest", "approval_digest"}
    base = {"kind", "repository", "source_sha", "provider", "model"}
    if (
        not isinstance(spec, dict)
        or spec.keys() - {"life_lease"} != base | extra
        or spec.get("kind") != KIND
    ):
        raise PortfolioError("engineering execution requires its approved original work order")
    remote.contract(
        {"input_data": {"remote_execution": {**{k: spec[k] for k in base}, "kind": remote.KIND}}}
    )
    try:
        request_id = str(uuid.UUID(spec["original_request_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PortfolioError("invalid original workspace request") from exc
    if request_id != spec["original_request_id"]:
        raise PortfolioError("original request must use its canonical identity")

    def validate(session, proposal):
        from modstore_server.strategic_company_resources import require_company_authorization

        if not proposal["limits"].get("company_budget_id"):
            raise PortfolioError("engineering execution requires its approved company budget")
        require_company_authorization(proposal, session)
        _, _, effects = original(
            session, {**spec, "binding": {"owner_user_id": task["owner_user_id"]}}, active=True
        )
        if effects.get("runner_intent") or effects.get("run_id"):
            raise PortfolioError(
                "an already dispatched workspace cannot acquire a retrospective budget"
            )

    remote.prepare_request(task, spec, request_id, actor=ACTOR, validate=validate)
    # Retort's existing scheduler resumes its own checkpoint. No new issue,
    # event, model task or workflow is dispatched by this strategic adapter.
    return {
        "ok": True,
        "accepted": True,
        "completed": False,
        "status": "queued",
        "worker_receipt_id": request_id,
        "executor": KIND,
    }


def attached(request_id: str, session: Any = None) -> bool:
    if session is None:
        with remote.get_session_factory()() as db:
            return attached(request_id, db)
    row = session.get(MacControlTask, uuid.UUID(request_id).hex)
    return row is not None and row.actor == ACTOR


def ready(request_id: str) -> bool:
    """Original runner admission calls this before any dispatch/device creation."""
    if not attached(request_id):
        return False
    request, _, _ = remote.read_request(request_id)

    def check(row, proposal, state, saved, record, snapshot, session):
        authorized(row, proposal, state, saved, request, session)
        return record.state not in {"execution_completed", "failed"}

    try:
        return bool(remote.authorized_mutate(request_id, check))
    except PortfolioError:
        return False


def descriptor(request_id: str) -> dict[str, Any]:
    if not attached(request_id):
        return {}
    request, snapshot, state = remote.read_request(request_id)
    return {
        "kind": KIND,
        "request_id": request_id,
        "binding_id": request["binding"]["binding_id"],
        "model": request["model"],
        "provider": request["provider"],
        "source_sha": request["source_sha"],
        "status": state,
        "phase": snapshot.get("phase"),
        "deadline": request["deadline"],
    }


def verify_allocation(request: dict[str, Any], effects: dict[str, Any]) -> None:
    allocation = effects.get("model_allocation") or {}
    if (
        not feedback_allocation_isolated(allocation)
        or allocation.get("model") != request["model"]
        or allocation.get("provider") != request["provider"]
    ):
        raise PortfolioError("workspace model allocation differs from the approved isolated route")


def token_matches(token: str, expected: str) -> bool:
    return bool(
        len(token) >= 32
        and expected
        and hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)
    )


def authenticate_model(request_id: str, token: str) -> dict[str, Any]:
    request, _, _ = remote.read_request(request_id)

    def check(row, proposal, state, saved, record, snapshot, session):
        authorized(row, proposal, state, saved, request, session)
        grant = snapshot.get("model_grant") or {}
        if (
            record.state != "claimed"
            or grant.get("phase") != snapshot.get("phase")
            or not token_matches(token, grant.get("token_sha256", ""))
        ):
            raise PortfolioError("workspace model task grant is invalid or no longer active")
        original_row, _, effects = original(session, request, active=True)
        verify_allocation(request, effects)
        if original_row.event_id != grant.get("event_id"):
            raise PortfolioError("workspace original event changed")
        from modstore_server.strategic_workspace_grants import current_attempt

        current_attempt(session, request, effects, original_row.event_id, grant)
        return {
            **request,
            "caller_binding": {
                "grant_id": grant["grant_id"],
                "event_id": grant["event_id"],
                "task_id": grant["task_id"],
                "subtask_id": grant["subtask_id"],
                "attempt": grant["attempt_id"],
                "phase": grant["phase"],
                "github_run_id": grant["run_id"],
                "run_attempt": 1,
            },
        }

    return cast(dict[str, Any], remote._mutate(request_id, check))


def candidate_metered(request_id: str, candidate: dict[str, Any]) -> bool:
    """An attached work order cannot publish a different or unmetered fix."""
    request, _, _ = remote.read_request(request_id)

    def check(row, proposal, state, saved, _record, snapshot, session):
        authorized(row, proposal, state, saved, request, session)
        matches = [
            grant
            for grant in snapshot.get("task_grants", [])
            if grant.get("role") == "fix"
            and grant.get("phase") == "execute"
            and all(
                grant.get(key) == candidate.get(key)
                for key in ("task_id", "subtask_id", "attempt_id")
            )
        ]
        if len(matches) == 1:
            from modstore_server.strategic_workspace_grants import current_attempt

            original_row, _, effects = original(session, request, active=True)
            current_attempt(session, request, effects, original_row.event_id, matches[0])
        calls = list(saved["calls"].values())
        return bool(
            len(matches) == 1
            and calls
            and all(call.get("status") == "settled" for call in calls)
            and any(
                (call.get("caller_binding") or {}).get("grant_id") == matches[0]["grant_id"]
                for call in calls
            )
        )

    try:
        return bool(remote.authorized_mutate(request_id, check))
    except PortfolioError:
        return False
