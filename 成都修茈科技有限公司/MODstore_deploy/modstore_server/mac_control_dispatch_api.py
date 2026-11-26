"""Authenticated CI identity for code dispatch and private training transport.

Task routes create and read only the service's own Mac control code tasks.
Training routes return redacted operational failures and exact structured
reproductions selected by configured cohorts and current source grants. They
submit proposed candidates, never grant approval or general admin access.

Tokens are never stored in plaintext. Production keeps only SHA-256 digests in
``MODSTORE_PARA_DISPATCH_TOKEN_SHA256`` (comma separated), so a token can be
rotated by adding the new digest, switching callers, then removing the old one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from modstore_server.api.deps import get_db
from modstore_server.db.mac_control import MacControlTask
from modstore_server.mac_control_store import TERMINAL, accept, digest, transition, view
from modstore_server.para_github_repair import REPAIR_ACTOR, REPAIR_KIND

router = APIRouter(prefix="/api/service/mac-control", tags=["mac-control-dispatch"])

SERVICE_ACTOR = "service:para-dispatch"
TOKEN_DIGESTS_ENV = "MODSTORE_PARA_DISPATCH_TOKEN_SHA256"
_MIN_TOKEN_LENGTH = 32
_DB_SESSION = Depends(get_db)


def _configured_digests() -> list[str]:
    raw = os.environ.get(TOKEN_DIGESTS_ENV, "")
    digests = []
    for item in raw.split(","):
        item = item.strip().lower()
        if len(item) == 64 and all(c in "0123456789abcdef" for c in item):
            digests.append(item)
    return digests


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_dispatch_service(authorization: str = Header(default="")) -> str:
    """Authenticate the dispatch-only service token; never accepts user/admin JWTs."""
    digests = _configured_digests()
    if not digests:
        raise HTTPException(503, "派单服务令牌尚未配置")
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or len(token) < _MIN_TOKEN_LENGTH:
        raise HTTPException(401, "需要派单服务令牌")
    presented = token_digest(token)
    matched = False
    for expected in digests:
        # Compare against every digest so timing does not reveal which one matched.
        matched = hmac.compare_digest(presented, expected) or matched
    if not matched:
        raise HTTPException(401, "派单服务令牌无效")
    return SERVICE_ACTOR


@router.get("/release-train/state")
def release_train_state(actor: str = Depends(require_dispatch_service)):
    """只读版本状态，供 CI 的 version-ssot-sync 对齐 VERSION.md 与锚点。"""
    from modstore_server.release_train import snapshot_public

    state = dict(snapshot_public())
    state.pop("ssot_path", None)
    return {"success": True, "state": state}


@router.get("/github-runs/{request_id}")
def github_run_status(
    request_id: uuid.UUID,
    actor: str = Depends(require_dispatch_service),
    db: Session = _DB_SESSION,
):
    from modstore_server.para_github_runner import run_status

    return run_status(db, request_id)


class DispatchRequest(BaseModel):
    request_key: str = Field(min_length=8, max_length=128)
    message: str = Field(min_length=1, max_length=12000)
    tool: str = Field(default="cursor", pattern=r"^(cursor|codex|claude_code|trae|opencode)$")
    source_sha: str = Field(default="", pattern=r"^(?:[0-9a-f]{40})?$")
    github_issue: int | None = Field(default=None, gt=0)
    repository: str = Field(default="", max_length=200)
    base_branch: str = Field(default="", max_length=250)


@router.get("/training/failures")
def training_failures(
    days: int = 14, min_count: int = 2, actor: str = Depends(require_dispatch_service)
):
    from modstore_server.capability_trainer import mine
    from modstore_server.dot_ticket_dispatch import redact_ticket_text
    from modstore_server.maintenance_loop.store import ledger_path

    clusters = mine(
        ledger_path(), days=max(1, min(90, days)), min_count=max(1, min(50, min_count))
    )[:20]
    for cluster in clusters:
        if cluster.get("surface") in {"workflow_nl_prompt", "rag_context_prompt"}:
            # Authenticated private training transport must preserve exact
            # reproduction bytes; public evidence contains only their hashes.
            continue
        cluster["failure_reason"] = redact_ticket_text(cluster["failure_reason"], ())[:300]
        for sample in cluster["samples"]:
            sample["task"] = redact_ticket_text(sample.get("task", ""), ())[:2000]
            sample["failure_reason"] = redact_ticket_text(sample["failure_reason"], ())[:300]
    return {"success": True, "clusters": clusters}


class TrainingCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=128)
    surface: str = Field(
        default="employee_prompt",
        pattern=r"^(employee_prompt|workflow_nl_prompt|rag_context_prompt)$",
    )
    employee_id: str = Field(default="", pattern=r"^(?:[A-Za-z0-9_-]{1,128})?$")
    resource_id: str = Field(
        default="", pattern=r"^(?:workflow_nl_generator|employee_rag_context)?$"
    )
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    failure_run_ids: list[str] = Field(min_length=1, max_length=20)
    workflow_run_id: int = Field(gt=0)
    bundle_json: str = Field(min_length=2, max_length=100000)
    files: dict[str, str]
    result_json: str = Field(min_length=2, max_length=1500000)


@router.post("/training/candidates", status_code=202)
def training_candidate(
    body: TrainingCandidateRequest,
    background: BackgroundTasks,
    actor: str = Depends(require_dispatch_service),
):
    from modstore_server.retort_evolution_api import _advance
    from modstore_server.retort_training_candidates import create_training_candidate

    try:
        request_id = create_training_candidate(body.model_dump(exclude_unset=True))
    except TimeoutError:
        raise HTTPException(409, "training_candidate_busy") from None
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from None
    background.add_task(_advance, request_id)
    return {
        "success": True,
        "request_id": request_id,
        "status": "proposed",
        "approval_required": True,
    }


class PullRequestDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=128)
    message: str = Field(min_length=1, max_length=12000)
    source_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    github_issue: int = Field(gt=0)
    pull_request: int = Field(gt=0)
    source_run_id: int = Field(gt=0)
    source_run_attempt: int = Field(gt=0)


def _service_view(task: MacControlTask) -> dict:
    payload = view(task)
    # Only the fields the dispatcher needs; no customer facts or delivery traces.
    keys = (
        "id",
        "state",
        "reason",
        "para_task_id",
        "device_id",
        "created_at",
        "updated_at",
    )
    result = {key: payload[key] for key in (*keys, "execution")} | {
        "terminal": task.state in TERMINAL
    }
    if task.actor == REPAIR_ACTOR:
        result.update(executor=REPAIR_KIND, github_run_id=payload["execution"].get("run_id"))
    return result


def _require_control_enabled():
    if os.environ.get("MODSTORE_MAC_CONTROL_ENABLED") != "1":
        raise HTTPException(503, "Mac 主控尚未启用，原有入口不受影响")
    if not os.environ.get("XCMAX_FACTORY_CAPABILITY_TOKEN"):
        raise HTTPException(503, "工厂执行能力尚未配置")


def _accept_task(db, *, actor, key, request):
    try:
        task = accept(db, actor=actor, key=key, request=request)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"success": True, "task": _service_view(task), "accepted": True}


@router.post("/github-pr-tasks", status_code=202)
def create_github_pr_task(
    body: PullRequestDispatchRequest,
    _actor: str = Depends(require_dispatch_service),
    db: Session = _DB_SESSION,
):
    from modstore_server.customer_ticket_github import configuration

    _require_control_enabled()
    config = configuration()
    if not config["configured"] or not config["para_configured"]:
        raise HTTPException(503, "Para 云端派工尚未配置")
    request = {
        **body.model_dump(exclude={"request_key"}),
        "source": REPAIR_KIND,
        "repository": config["repository"],
        "target": "github",
        "tool": "codex",
        "mode": "code",
    }
    result = _accept_task(db, actor=REPAIR_ACTOR, key=body.request_key, request=request)
    task = db.get(MacControlTask, result["task"]["id"])
    if task is None:
        raise HTTPException(409, "原 PR 请求回执尚未确认")
    if task.state == "queued" and not json.loads(task.snapshot_json).get("strategic_request"):
        transition(db, task, "awaiting_approval", "original_pr_company_budget_required")
        result["task"] = _service_view(task)
    return result


def _issue_key(repository: str, number: int) -> str:
    return f"gh-issue-{number}-v2-{hashlib.sha256(repository.lower().encode()).hexdigest()}"


def _issue_scope(repository: str, base_branch: str) -> tuple[str, str]:
    owner, separator, repo = repository.partition("/")
    if (
        not (owner and separator and repo)
        or any(not (c.isascii() and (c.isalnum() or c in "_.-")) for c in owner + repo)
        or not base_branch
        or len(base_branch) > 250
        or any(c.isspace() or ord(c) < 32 for c in base_branch)
    ):
        raise HTTPException(409, "工单仓库或目标分支身份无效")
    return repository.lower(), base_branch


def _message_scope(message: str, number: int) -> tuple[str, str]:
    # Historical callers persisted scope only in the fixed script-generated header.
    prefix = f"修复 GitHub issue #{number}（"
    header, _, rest = message.partition("\n\n基线分支：")
    repository, repo_boundary, _ = header.removeprefix(prefix).partition("）：")
    base_branch, branch_boundary, _ = rest.partition("。只做 issue 要求的最小改动，")
    if not header.startswith(prefix) or "\n" in header or not repo_boundary or not branch_boundary:
        raise HTTPException(409, "派单消息身份不可核验")
    return _issue_scope(repository, base_branch)


def _find_issue_task(
    db: Session, actor: str, number: int, repository: str, base_branch: str
) -> MacControlTask | None:
    key = _issue_key(repository, number)
    matches = (
        db.query(MacControlTask)
        .filter(
            MacControlTask.actor == actor,
            (MacControlTask.request_key == key)
            | MacControlTask.request_key.like(f"gh-issue-{number}-run-%"),
        )
        .limit(2)
        .all()
    )
    if len(matches) > 1:
        raise HTTPException(409, "同一工单存在多个历史任务，须独立对账")
    if not matches:
        return None
    task = matches[0]
    try:
        request = json.loads(task.request_json)
        if (
            not isinstance(request, dict)
            or digest(request) != task.request_digest
            or request.get("source") != "github_issue_dispatch"
            or request.get("github_issue") != number
        ):
            raise ValueError("invalid persisted issue identity")
        scope = _message_scope(request["message"], number)
        if task.request_key == key and scope != _issue_scope(
            request["repository"], request["base_branch"]
        ):
            raise ValueError("stored request scope mismatch")
    except (ValueError, TypeError, KeyError):
        raise HTTPException(409, "历史派单身份不可核验") from None
    if scope != (repository, base_branch):
        raise HTTPException(409, "原工单仓库或目标分支不同，拒绝重新派单")
    return task


@router.get("/issues/{issue_number}/task")
def find_code_issue_task(
    issue_number: int,
    repository: str,
    base_branch: str,
    actor: str = Depends(require_dispatch_service),
    db: Session = _DB_SESSION,
):
    if issue_number < 1:
        raise HTTPException(409, "工单身份无效")
    repository, base_branch = _issue_scope(repository, base_branch)
    task = _find_issue_task(db, actor, issue_number, repository, base_branch)
    # A successful, explicit null is the only proof that a task is absent.
    return {"success": True, "task": _service_view(task) if task is not None else None}


@router.post("/tasks", status_code=202)
def create_code_task(
    body: DispatchRequest,
    actor: str = Depends(require_dispatch_service),
    db: Session = _DB_SESSION,
):
    _require_control_enabled()
    request: dict = {
        "message": body.message,
        "target": "mac",
        "tool": body.tool,
        "mode": "code",
        "source_sha": body.source_sha,
        "ticket_id": None,
        "customer_id": None,
        "source": "github_issue_dispatch",
    }
    key = body.request_key
    if body.github_issue:
        number = body.github_issue
        request["github_issue"] = number
        legacy_prefix = f"gh-issue-{number}-run-"
        old_key = key.startswith(legacy_prefix) and re.fullmatch(
            r"[0-9]+|local", key.removeprefix(legacy_prefix)
        )
        message_scope = _message_scope(body.message, number)
        if old_key and not (body.repository or body.base_branch):
            repository, base_branch = message_scope
        else:
            repository, base_branch = _issue_scope(body.repository, body.base_branch)
        if message_scope != (repository, base_branch):
            raise HTTPException(409, "派单消息与工单身份不同")
        stable_key = _issue_key(repository, number)
        if not old_key and key != stable_key:
            raise HTTPException(409, "普通工单必须使用稳定业务请求身份")
        request.update(repository=repository, base_branch=base_branch)
        existing = _find_issue_task(db, actor, number, repository, base_branch)
        if existing is not None and existing.request_key != stable_key:
            # Never rewrite historical identity or its frozen request.
            previous = json.loads(existing.request_json)
            previous.update(repository=repository, base_branch=base_branch)
            if digest(previous) != digest(request):
                raise HTTPException(409, "历史工单请求内容已变化，请恢复原控制任务")
            return {"success": True, "task": _service_view(existing), "accepted": True}
        key = stable_key
    elif (
        body.repository
        or body.base_branch
        or re.fullmatch(r"gh-issue-[0-9]+-(?:run-.+|v2-.+)", key)
    ):
        raise HTTPException(409, "缺少普通工单身份")
    return _accept_task(db, actor=actor, key=key, request=request)


@router.get("/tasks/{task_id}")
def get_code_task(
    task_id: str,
    actor: str = Depends(require_dispatch_service),
    db: Session = _DB_SESSION,
):
    task = db.get(MacControlTask, task_id)
    # Tasks created by admins or other identities are invisible to this token.
    if task is None or task.actor not in {actor, REPAIR_ACTOR}:
        raise HTTPException(404, "任务不存在")
    if task.actor == actor and task.para_task_id and task.state in TERMINAL:
        from modstore_server.mac_control_transport import (
            ParaClient,
            ParaUnavailable,
            execution_view,
        )

        client = None
        try:
            client = ParaClient()
            snapshot = execution_view(client.task(task.para_task_id))
            if snapshot != view(task)["execution"]:
                transition(db, task, task.state, task.reason, snapshot=snapshot)
        except ParaUnavailable:
            pass
        finally:
            if client:
                client.close()
    return {"success": True, "task": _service_view(task), "checked_at": time.time()}


def _include_strategic_router():
    # Import after service authentication to keep the shared router cycle explicit.
    from modstore_server.strategic_remote_api import router as strategic_remote_router

    router.include_router(strategic_remote_router)


_include_strategic_router()
