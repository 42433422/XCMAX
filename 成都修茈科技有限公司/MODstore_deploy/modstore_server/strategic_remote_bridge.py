"""Approved read-only business reports on the existing GitHub/OpenCode worker.

MacControlTask supplies the durable request identity; the portfolio transaction
owns its lease and model-call budget. This is intentionally not a code publisher
or an adapter for an uninstrumented external Para/Cursor service.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy.orm import Session

from modstore_server.db.mac_control import MacControlTask
from modstore_server.strategic_portfolio import (
    PortfolioError,
    _date,
    _json,
    digest,
    mutate_portfolio,
    portfolio_status,
    require_authorization,
)

KIND = "github_opencode_report"
ACTOR = "service:strategy-report"
SCHEMA = "strategic-remote-report/v1"


def get_session_factory():
    from modstore_server.db.db_base import get_session_factory as configured_factory

    return configured_factory()


def public_base() -> str:
    origin = (
        os.environ.get("MODSTORE_PUBLIC_ORIGIN")
        or os.environ.get("PUBLIC_ORIGIN")
        or "https://xiu-ci.com"
    ).rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise PortfolioError("remote reports require the configured HTTPS public origin")
    return origin + "/api/service/mac-control/strategic-runs"


def contract(task: dict[str, Any]) -> dict[str, str]:
    from modstore_server.customer_ticket_github import configuration
    from modstore_server.llm_chat_proxy import normalize_model
    from modstore_server.llm_key_resolver import (
        OAI_COMPAT_OPENAI_STYLE_PROVIDERS,
        platform_api_key,
        platform_base_url,
    )

    remote = (task.get("input_data") or {}).get("remote_execution")
    fields = {"kind", "repository", "source_sha", "provider", "model"}
    if not isinstance(remote, dict) or remote.keys() != fields or remote.get("kind") != KIND:
        raise PortfolioError(
            "remote execution requires the approved github_opencode_report contract"
        )
    if remote["repository"] != configuration()["repository"] or not re.fullmatch(
        r"[0-9a-f]{40}", str(remote["source_sha"])
    ):
        raise PortfolioError(
            "remote report requires the configured repository and frozen source SHA"
        )
    provider, model = remote["provider"], remote["model"]
    if provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS or not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}", str(model)
    ):
        raise PortfolioError("remote report requires an approved Responses model route")
    if (
        not platform_api_key(provider)
        or normalize_model(provider, model, platform_base_url(provider)) != model
    ):
        raise PortfolioError("remote report requires a configured canonical platform model")
    return dict(remote)


def _row(session: Session, request_id: str) -> MacControlTask:
    try:
        key = uuid.UUID(str(request_id)).hex
    except ValueError as exc:
        raise PortfolioError("invalid remote request identity") from exc
    row = session.get(MacControlTask, key)
    if row is None or row.actor not in {ACTOR, "service:strategy-workspace"}:
        raise PortfolioError("remote request not found")
    if digest(json.loads(row.request_json)) != row.request_digest:
        raise PortfolioError("remote request integrity changed")
    return row


def read_request(request_id: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    with get_session_factory()() as session:
        row = _row(session, request_id)
        return json.loads(row.request_json), json.loads(row.snapshot_json), row.state


def _mutate(request_id: str, apply: Any) -> Any:
    request, _, _ = read_request(request_id)
    binding = request["binding"]

    def update(row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any):
        remote = _row(session, request_id)
        if json.loads(remote.request_json) != request:
            raise PortfolioError("remote request changed")
        saved = state["tasks"].get(binding["opportunity_id"], {})
        if (
            saved.get("worker_binding") != binding
            or saved.get("lease_token") != binding["lease_token"]
        ):
            raise PortfolioError("remote execution no longer owns its original lease")
        snapshot = json.loads(remote.snapshot_json)
        result = apply(row, proposal, state, saved, remote, snapshot, session)
        remote.snapshot_json, remote.updated_at = _json(snapshot), time.time()
        return result

    return mutate_portfolio(binding["decision_id"], update, owner_user_id=binding["owner_user_id"])


@contextmanager
def authorization_scope(request: dict[str, Any]) -> Iterator[None]:
    """Restore only the original life authority, with no local queue cancellation.

    Remote ``waiting`` can mean a dispatched job or a published candidate. Its
    terminal responsibility is released only by the native receipt readers.
    """
    from modstore_server.strategic_portfolio_worker import _LIFE_FIELDS
    from modstore_server.strategic_remote_life import execution_scope
    from modstore_server.xiaoc_life_policy import MINIMUM_LEVEL, LifePolicyError
    from modstore_server.xiaoc_life_store import life_execution_scope

    binding = request["binding"]
    claim = binding.get("life_scope")
    if claim is None:
        if request.get("life_lease") is not None:
            raise PortfolioError("persistent remote authority requires its original life scope")
        yield
        return
    if (
        not isinstance(claim, dict)
        or set(claim) != _LIFE_FIELDS
        or type(claim.get("owner_user_id")) is not int
        or claim["owner_user_id"] != binding["owner_user_id"]
        or claim.get("domain") not in MINIMUM_LEVEL
        or (
            request.get("life_lease") is None
            and _date(request["deadline"]) > _date(claim["deadline"])
        )
    ):
        raise PortfolioError("remote life scope differs from its original owner or deadline")
    try:
        with execution_scope(request) if request.get("life_lease") else life_execution_scope(claim):
            yield
    except LifePolicyError as exc:
        raise PortfolioError(str(exc)) from exc


def authorized_mutate(request_id: str, apply: Any) -> Any:
    request, _, _ = read_request(request_id)
    with authorization_scope(request):
        return _mutate(request_id, apply)


def prepare_request(
    task: dict[str, Any],
    remote: dict[str, Any],
    request_id: str,
    *,
    actor: str = ACTOR,
    validate: Any = None,
) -> dict[str, Any]:
    """Create one durable worker binding under the original portfolio CAS."""
    from modstore_server.strategic_portfolio_worker import capture_life_worker_scope
    from modstore_server.strategic_remote_life import register

    binding_id, gateway_base = uuid.uuid4().hex, public_base()
    life_scope = capture_life_worker_scope()
    if life_scope is not None and life_scope["owner_user_id"] != task["owner_user_id"]:
        raise PortfolioError("remote life scope does not own the approved portfolio")

    def prepare(row: Any, proposal: dict[str, Any], state: dict[str, Any], session: Any):
        require_authorization(row, proposal, state)
        saved = state["tasks"][task["opportunity_id"]]
        if (
            saved.get("lease_token") != task["lease_token"]
            or saved["status"] != "running"
            or saved.get("worker_binding")
        ):
            raise PortfolioError("remote dispatch lease already owned")
        if _date(saved["deadline"]) <= datetime.now(UTC):
            raise PortfolioError("remote execution deadline expired")
        if not any(
            (item["provider"], item["model"]) == (remote["provider"], remote["model"])
            for item in proposal["limits"]["tariffs"]
        ):
            raise PortfolioError("remote model lacks the approved tariff")
        if validate is not None:
            validate(session, proposal)
        if session.get(MacControlTask, uuid.UUID(request_id).hex) is not None:
            raise PortfolioError("original request already owns a strategic budget")
        binding = {
            "decision_id": task["decision_id"],
            "opportunity_id": task["opportunity_id"],
            "lease_token": task["lease_token"],
            "owner_user_id": task["owner_user_id"],
            "proposal_sha256": proposal["proposal_sha256"],
            "binding_id": binding_id,
            "receipt_id": request_id,
            "adapter": remote["kind"],
        }
        deadline = (
            min(_date(saved["deadline"]), _date(proposal["limits"]["expires_at"]))
            if actor == ACTOR
            else _date(proposal["limits"]["expires_at"])
        )
        if life_scope is not None:
            binding["life_scope"] = life_scope
            deadline = min(deadline, _date(life_scope["deadline"]))
            saved["deadline"] = min(_date(saved["deadline"]), deadline).isoformat()
        request = {
            "schema": SCHEMA if actor == ACTOR else "strategic-workspace/v1",
            **remote,
            "gateway_base": gateway_base,
            "binding": binding,
            "task": task["task"],
            "input_data": task["input_data"],
            "execution_binding": task["execution_binding"],
            "deadline": deadline.isoformat(),
        }
        register(session, row, proposal, state, request)
        now = time.time()
        session.add(
            MacControlTask(
                id=uuid.UUID(request_id).hex,
                actor=actor,
                request_key=binding_id,
                request_digest=digest(request),
                request_json=_json(request),
                state="dispatching",
                reason="",
                para_task_id="",
                device_id="",
                attempt_id="",
                lease_until=0,
                snapshot_json="{}",
                created_at=now,
                updated_at=now,
            )
        )
        saved["worker_binding"] = binding
        return request

    return cast(
        dict[str, Any],
        mutate_portfolio(task["decision_id"], prepare, owner_user_id=task["owner_user_id"]),
    )


def dispatch_report(task: dict[str, Any]) -> dict[str, Any]:
    from modstore_server.customer_ticket_github import github
    from modstore_server.mac_control_dispatch_api import _configured_digests
    from modstore_server.para_github_runner import WORKFLOW
    from modstore_server.strategic_execution_contract import freeze_execution

    if os.environ.get("MODSTORE_STRATEGIC_REPORTS_ENABLED") != "1" or not _configured_digests():
        raise PortfolioError("strategic report worker is not configured")
    # Resolve the same tenant, package and effective policy captured in approval.
    freeze_execution(task["owner_user_id"], task)
    remote = contract(task)
    if (
        github("GET", f"/repos/{remote['repository']}/commits/main").get("sha")
        != remote["source_sha"]
    ):
        raise PortfolioError("approved report controller source is no longer current main")
    request_id = str(uuid.uuid4())
    prepare_request(task, remote, request_id)
    submitted = "requested"
    try:
        github(
            "POST",
            f"/repos/{remote['repository']}/actions/workflows/{WORKFLOW}/dispatches",
            {"ref": "main", "inputs": {"request_id": request_id}},
        )
    except HTTPException:
        submitted = "unknown"  # The durable intent is never dispatched a second time.

    def note(_row, _proposal, _state, _saved, record, _snapshot, _session):
        if record.state == "dispatching":
            record.state = submitted

    _mutate(request_id, note)
    return {
        "ok": True,
        "accepted": True,
        "status": "queued",
        "completed": False,
        "worker_receipt_id": request_id,
        "executor": KIND,
    }


def native_run(request: dict[str, Any], run_id: Any) -> dict[str, Any]:
    from modstore_server.customer_ticket_github import github
    from modstore_server.para_github_repair import _worker_run

    if type(run_id) is not int or run_id < 1:
        raise PortfolioError("remote report requires its native GitHub run")
    run = _worker_run(github, request["repository"], run_id, request["binding"]["receipt_id"])
    if run.get("head_sha") != request["source_sha"]:
        raise PortfolioError("remote controller differs from the approved source SHA")
    return dict(run)


def claim_report(request_id: str, identity: dict[str, Any]) -> dict[str, Any]:
    request, _, _ = read_request(request_id)
    run = native_run(request, identity.get("run_id"))
    if (
        digest(identity)
        != digest(
            {
                "run_id": run["id"],
                "run_attempt": 1,
                "repository": request["repository"],
                "source_sha": request["source_sha"],
            }
        )
        or run.get("status") != "in_progress"
    ):
        raise PortfolioError("remote runner identity is not the approved active execution")
    token = secrets.token_urlsafe(40)

    def claim(row, proposal, state, saved, remote, snapshot, _session):
        require_authorization(row, proposal, state)
        if (
            saved["status"] != "waiting"
            or remote.state not in {"dispatching", "requested", "unknown"}
            or snapshot.get("run_id")
        ):
            raise PortfolioError("remote request cannot be claimed or replayed")
        if _date(request["deadline"]) <= datetime.now(UTC):
            raise PortfolioError("remote execution deadline expired")
        saved["status"], remote.state = "running", "claimed"
        snapshot.update(
            identity,
            token_sha256=hashlib.sha256(token.encode()).hexdigest(),
            claimed_at=datetime.now(UTC).isoformat(),
        )
        return {
            "schema": SCHEMA,
            "request_id": request_id,
            "binding_id": request["binding"]["binding_id"],
            "owner_user_id": request["binding"]["owner_user_id"],
            **identity,
            "kind": KIND,
            "deadline": request["deadline"],
            "task": request["task"],
            "input_data": {
                key: value
                for key, value in request["input_data"].items()
                if key not in {"remote_execution", "project_root", "workspace_root"}
            },
            "model": request["model"],
            "gateway_url": f"{request['gateway_base']}/{request_id}/v1",
            "model_token": token,
        }

    return cast(dict[str, Any], authorized_mutate(request_id, claim))


def authenticate_model(request_id: str, token: str) -> dict[str, Any]:
    request, _, _ = read_request(request_id)
    if request["kind"] == "github_opencode_workspace":
        from modstore_server.strategic_workspace_bridge import authenticate_model as workspace_model

        return workspace_model(request_id, token)

    def authenticate(_row, _proposal, _state, _saved, remote, snapshot, _session):
        expected = snapshot.get("token_sha256", "")
        if (
            remote.state != "claimed"
            or len(token) < 32
            or not expected
            or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), expected)
        ):
            raise PortfolioError("remote model grant is invalid or no longer active")
        return request

    return cast(dict[str, Any], _mutate(request_id, authenticate))


@contextmanager
def model_scope(request_id: str, token: str) -> Iterator[dict[str, Any]]:
    from modstore_server.platform_llm_scope import platform_llm_scope
    from modstore_server.strategic_portfolio_usage import (
        portfolio_usage_scope,
        remaining_execution_seconds,
    )

    request, _, _ = read_request(request_id)
    binding = request["binding"]
    with (
        authorization_scope(request),
        platform_llm_scope(),
        portfolio_usage_scope(
            binding["decision_id"], binding["opportunity_id"], binding["lease_token"]
        ),
    ):
        request = authenticate_model(request_id, token)
        remaining_execution_seconds()
        yield request


def report_result(request_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    request, snapshot, _ = read_request(request_id)
    identity = {
        "schema": SCHEMA,
        "kind": KIND,
        "request_id": request_id,
        "binding_id": request["binding"]["binding_id"],
        "owner_user_id": request["binding"]["owner_user_id"],
        "run_id": snapshot.get("run_id"),
        "run_attempt": 1,
        "repository": request["repository"],
        "source_sha": request["source_sha"],
    }
    if digest({key: receipt.get(key) for key in identity}) != digest(identity) or receipt.get(
        "status"
    ) not in {"completed", "failed"}:
        raise PortfolioError("remote report receipt identity mismatch")
    if receipt["status"] == "completed" and not re.fullmatch(
        r"[0-9a-f]{64}", str(receipt.get("report_sha256", ""))
    ):
        raise PortfolioError("remote report content digest is missing")
    if set(receipt) - (identity.keys() | {"status", "report_sha256", "error"}):
        raise PortfolioError("unexpected remote report receipt fields")
    native_run(request, snapshot["run_id"])

    def accept(_row, _proposal, _state, _saved, remote, saved, _session):
        if remote.state == "reported" and saved.get("controller_receipt") == receipt:
            return {"accepted": True, "status": "pending_artifact_readback"}
        if remote.state != "claimed":
            raise PortfolioError("remote result is already terminal or unclaimed")
        remote.state = "reported"
        saved.pop("token_sha256", None)
        saved.update(controller_receipt=receipt, reported_at=datetime.now(UTC).isoformat())
        return {"accepted": True, "status": "pending_artifact_readback"}

    return cast(dict[str, Any], _mutate(request_id, accept))


def worker_status(request_id: str) -> dict[str, Any]:
    request, snapshot, state = read_request(request_id)
    binding = request["binding"]
    status = portfolio_status(binding["decision_id"], owner_user_id=binding["owner_user_id"])
    saved = status["tasks"][binding["opportunity_id"]]
    return {
        "request_id": request_id,
        "kind": KIND,
        "repository": request["repository"],
        "source_sha": request["source_sha"],
        "run_id": snapshot.get("run_id"),
        "status": state,
        "finished": state in {"execution_completed", "failed"},
        "ready": saved["status"] == "waiting" and not status["halted"],
        "conclusion": "success" if state == "execution_completed" else "unknown",
    }
