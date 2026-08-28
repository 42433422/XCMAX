"""Authenticated approval callbacks for autonomous actions."""

from __future__ import annotations

import hmac
import os
import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.application.autonomy.approval_center import list_pending_actions
from app.application.autonomy.approval_resume import (
    ApprovalStateError,
    complete_action,
    get_action_state,
    mark_approval_requested,
    reject_action,
    request_action,
    resume_action,
)
from app.domain.autonomy.autonomy_guard import ProhibitedActionError, evaluate_risk
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(prefix="/api/ops/autonomy", tags=["ops-autonomy"])

_WORKFLOW_ACTIONS = {
    "apply_release_to_cvm": "apply-latest",
    "restart_service": "restart-only",
    "freeze_manifest": "freeze-manifest",
    "unfreeze_manifest": "unfreeze-manifest",
}
_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _validated_action_id(value: Any, *, required: bool = False) -> str | None:
    action_id = str(value or "").strip()
    if not action_id and not required:
        return None
    if not _ACTION_ID_RE.fullmatch(action_id):
        raise HTTPException(
            status_code=400,
            detail="action_id must be 1-128 characters from A-Z a-z 0-9 . _ : -",
        )
    return action_id


def _expected_token() -> str:
    return (
        os.environ.get("AUTONOMY_WEBHOOK_TOKEN")
        or os.environ.get("MODSTORE_OPS_INGEST_TOKEN")
        or ""
    ).strip()


def _auth(
    authorization: str | None,
    x_autonomy_token: str | None,
    request: Request | None = None,
) -> None:
    # admin session 旁路：管理端浏览器访问时放行
    if request is not None:
        try:
            from app.enterprise.mod_entitlements import is_admin_account_session

            if is_admin_account_session():
                return
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - 旁路失败走 webhook token
            pass
    expected = _expected_token()
    supplied = str(x_autonomy_token or "").strip()
    bearer = str(authorization or "").strip()
    if bearer.lower().startswith("bearer "):
        supplied = bearer[7:].strip()
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid autonomy webhook token")


@router.get("/health")
async def autonomy_approval_health() -> dict[str, Any]:
    return {"ok": True, "service": "ops-autonomy-approval"}


@router.get("/actions/pending")
async def pending_autonomy_actions(
    request: Request,
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
) -> dict[str, Any]:
    _auth(authorization, x_autonomy_token, request=request)
    items = list_pending_actions()
    return {"ok": True, "count": len(items), "items": items}


@router.post("/actions/evaluate")
async def evaluate_autonomy_action(
    request: Request,
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
) -> dict[str, Any]:
    """Evaluate a proposed action without invoking an executor."""

    _auth(authorization, x_autonomy_token, request=request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="json object required")
    action = str(body.get("action") or "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="action is required")
    try:
        result = evaluate_risk(
            action,
            action_id=_validated_action_id(body.get("action_id")),
            source="ops_autonomy.evaluate",
        )
    except ProhibitedActionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"ok": True, "decision": result.to_dict()}


@router.post("/actions/request")
async def request_autonomy_action(
    request: Request,
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
) -> dict[str, Any]:
    """Persist a deploy action for the GitHub environment dispatcher."""

    _auth(authorization, x_autonomy_token, request=request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="json object required")
    action = str(body.get("action") or "").strip()
    workflow_action = _WORKFLOW_ACTIONS.get(action)
    if not workflow_action:
        raise HTTPException(status_code=400, detail="action has no GitHub deploy executor")
    action_id = _validated_action_id(body.get("action_id"))
    raw_payload = body.get("payload")
    payload: dict[str, Any] = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    source = str(body.get("source") or "").strip() or "ops_autonomy.request"
    decision, pending = request_action(
        action,
        action_id=action_id,
        payload={**payload, "workflow_action": workflow_action},
        source=source,
        executor_name="github_deploy",
    )
    if pending is None:
        raise HTTPException(
            status_code=409,
            detail=f"action does not require GitHub approval: {decision.decision}",
        )
    return {
        "ok": True,
        "state": pending["state"],
        "action_id": pending["action_id"],
        "workflow_action": workflow_action,
        "decision": decision.to_dict(),
    }


@router.post("/actions/ingest")
async def ingest_autonomy_action(
    request: Request,
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
) -> dict[str, Any]:
    """Escalate 旁路写入 approval ledger（不限 action 白名单）。

    供 CI 自愈 / CVM watcher / escalate_to_human 等脚本 fire-and-forget 写入
    待办，不绑定 GitHub deploy executor。与 /actions/request 的区别：
    - 不校验 _WORKFLOW_ACTIONS 白名单
    - 不设 executor_name="github_deploy"
    - action 无需审批时返回 200（而非 409）
    """

    _auth(authorization, x_autonomy_token, request=request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="json object required")
    action = str(body.get("action") or "").strip()
    if not action:
        raise HTTPException(status_code=400, detail="action is required")
    action_id = _validated_action_id(body.get("action_id"))
    raw_payload = body.get("payload")
    payload: dict[str, Any] = dict(raw_payload) if isinstance(raw_payload, dict) else {}
    source = str(body.get("source") or "").strip() or "ops_autonomy.ingest"
    decision, pending = request_action(
        action,
        action_id=action_id,
        payload=payload,
        source=source,
    )
    if pending is None:
        return {
            "ok": True,
            "state": "no_approval_needed",
            "action_id": action_id,
            "decision": decision.to_dict(),
        }
    return {
        "ok": True,
        "state": pending["state"],
        "action_id": pending["action_id"],
        "decision": decision.to_dict(),
    }


@router.post("/github-approval")
async def github_approval_callback(
    request: Request,
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
    x_github_actor: str | None = Header(default=None, alias="X-GitHub-Actor"),
) -> dict[str, Any]:
    """Resume or reject a persisted action after environment review."""

    _auth(authorization, x_autonomy_token, request=request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="json object required")
    raw_review = body.get("review")
    review: dict[str, Any] = dict(raw_review) if isinstance(raw_review, dict) else {}
    raw_reviewer = review.get("reviewer")
    reviewer: dict[str, Any] = dict(raw_reviewer) if isinstance(raw_reviewer, dict) else {}
    action_id = _validated_action_id(body.get("action_id"), required=True)
    if action_id is None:  # defensive: ``required=True`` raises before this branch
        raise HTTPException(status_code=400, detail="action_id is required")
    decision = (
        str(body.get("decision") or review.get("state") or body.get("state") or "").strip().lower()
    )
    approver = str(
        (body or {}).get("approver") or x_github_actor or reviewer.get("login") or ""
    ).strip()
    approval_id = str(body.get("approval_id") or body.get("deployment_id") or "").strip()
    if not decision or not approver:
        raise HTTPException(status_code=400, detail="action_id, decision and approver are required")
    current = get_action_state(action_id)
    current_data: dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    workflow_action = str(body.get("workflow_action") or "").strip()
    expected = _WORKFLOW_ACTIONS.get(str(current_data.get("action") or ""))
    try:
        if (
            expected
            and decision
            in {
                "approved",
                "approve",
                "accepted",
                "executed",
                "success",
                "completed",
                "execution_failed",
                "failed",
                "failure",
            }
            and not workflow_action
        ):
            raise ApprovalStateError("workflow_action is required for deploy action callbacks")
        if expected and workflow_action and workflow_action != expected:
            raise ApprovalStateError(
                f"workflow action mismatch: pending={expected} callback={workflow_action}"
            )
        if decision in {"approved", "approve", "accepted"}:
            item = resume_action(
                action_id,
                approver=approver,
                approval_id=approval_id,
                defer_execution=bool(body.get("defer_execution")),
            )
        elif decision in {"approval_requested", "requested", "dispatched"}:
            item = mark_approval_requested(
                action_id,
                approval_id=approval_id,
                source="github_dispatcher",
            )
        elif decision in {"rejected", "reject", "denied"}:
            item = reject_action(
                action_id,
                approver=approver,
                approval_id=approval_id,
                reason=str(body.get("reason") or "GitHub environment review rejected"),
            )
        elif decision in {"executed", "success", "completed"}:
            item = complete_action(
                action_id,
                success=True,
                approver=approver,
                approval_id=approval_id,
                outcome=body.get("outcome") if isinstance(body.get("outcome"), dict) else {},
            )
        elif decision in {"execution_failed", "failed", "failure"}:
            item = complete_action(
                action_id,
                success=False,
                approver=approver,
                approval_id=approval_id,
                outcome=body.get("outcome") if isinstance(body.get("outcome"), dict) else {},
            )
        else:
            raise HTTPException(status_code=400, detail=f"unsupported decision: {decision}")
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "action": item}


@router.post("/actions/{action_id}/resume")
async def resume_autonomy_action(
    action_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
) -> dict[str, Any]:
    _auth(authorization, x_autonomy_token, request=request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="json object required")
    try:
        item = resume_action(
            action_id,
            approver=str(body.get("approver") or ""),
            approval_id=str(body.get("approval_id") or ""),
            defer_execution=bool(body.get("defer_execution")),
        )
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "action": item}


@router.post("/actions/{action_id}/reject")
async def reject_autonomy_action(
    action_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
) -> dict[str, Any]:
    _auth(authorization, x_autonomy_token, request=request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="json object required")
    approver = str(body.get("approver") or "").strip()
    if not approver:
        raise HTTPException(status_code=400, detail="approver is required")
    try:
        item = reject_action(
            action_id,
            approver=approver,
            reason=str(body.get("reason") or ""),
            approval_id=str(body.get("approval_id") or ""),
        )
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "action": item}


@router.post("/cs-ssot/retrieve")
async def cs_ssot_retrieve(
    request: Request,
    authorization: str | None = Header(default=None),
    x_autonomy_token: str | None = Header(default=None, alias="X-Autonomy-Token"),
) -> dict[str, Any]:
    """小C 客服 SSOT：从管理端 persy-knowledge 检索片段（机器调用）。

    供 MODstore butler / 市场客服同源读取管理端知识库。
    """
    _auth(authorization, x_autonomy_token, request=request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="json object required")
    query = str(body.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    try:
        top_k = int(body.get("top_k") or 5)
    except (TypeError, ValueError):
        top_k = 5
    top_k = max(1, min(top_k, 12))
    dataset_id = str(body.get("dataset_id") or "persy-knowledge").strip() or "persy-knowledge"

    from app.application.dataset_rag_app_service import (
        DATASET_ADMIN_PERMISSION,
        DATASET_READ_PERMISSION,
        DatasetAccessContext,
        get_dataset_rag_app_service,
    )

    access = DatasetAccessContext(
        actor_id="xiaoc-cs-ssot",
        tenant_id="",
        permissions=frozenset({DATASET_READ_PERMISSION, DATASET_ADMIN_PERMISSION}),
        is_admin=True,
    )
    result = get_dataset_rag_app_service().query(
        dataset_id=dataset_id,
        query=query,
        top_k=top_k,
        access_context=access,
    )
    chunks = result.get("chunks") if isinstance(result, dict) else []
    if not isinstance(chunks, list):
        chunks = []
    return {
        "ok": bool(result.get("success")) if isinstance(result, dict) else True,
        "dataset_id": dataset_id,
        "query": query,
        "chunks": chunks,
        "ssot": "admin_persy_knowledge",
    }
