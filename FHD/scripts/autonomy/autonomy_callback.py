#!/usr/bin/env python3
"""显式 autonomy callback（SSOT）。

契约符号（供搜索与验收）:
  - autonomy_callback / report_callback / deploy_callback  → POST /actions/ingest
  - report_executed / report_execution_failed / report_rejected /
    report_approval_requested                               → POST /github-approval

设计：
  - ingest：写 pending_approval / 运行态事件
  - github-approval：推进终态（executed / execution_failed / rejected / approval_requested）
  - fail-open：网络/鉴权/依赖缺失只打 stderr，不阻断主流程
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

_CI_SCRIPTS = Path(__file__).resolve().parents[1] / "ci"
if str(_CI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CI_SCRIPTS))

try:
    from _approval_ledger_client import post_to_approval_ledger
except ImportError:  # pragma: no cover
    post_to_approval_ledger = None  # type: ignore[assignment]

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


def autonomy_callback(
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str = "autonomy",
    action_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """通用回调：把 event_type + payload 写入 approval ledger。"""
    if not event_type or not isinstance(payload, dict):
        print(
            f"[autonomy_callback] invalid args event_type={event_type!r}",
            file=sys.stderr,
        )
        return None
    if post_to_approval_ledger is None:
        print(
            "[autonomy_callback] post_to_approval_ledger unavailable, skip",
            file=sys.stderr,
        )
        return None

    body = dict(payload)
    body.setdefault("callback_event", event_type)
    try:
        return post_to_approval_ledger(
            action=str(event_type),
            payload=body,
            source=source,
            action_id=action_id,
        )
    except Exception as exc:  # noqa: BLE001 - script boundary records arbitrary integration failures  # pragma: no cover
        print(f"[autonomy_callback] error: {exc!r}", file=sys.stderr)
        return None


def report_callback(
    report_kind: str,
    payload: dict[str, Any],
    *,
    source: str = "autonomy",
    action_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """报告类回调（ledger / audit / metrics 摘要等）。"""
    kind = (report_kind or "generic").strip() or "generic"
    return autonomy_callback(
        f"report:{kind}",
        payload,
        source=source,
        action_id=action_id,
    )


def deploy_callback(
    phase: str,
    payload: dict[str, Any],
    *,
    source: str = "self_maintenance",
    action_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """部署类回调（dispatch_ok / dispatch_failed / freeze_manifest / …）。"""
    phase_name = (phase or "unknown").strip() or "unknown"
    return autonomy_callback(
        f"deploy:{phase_name}",
        payload,
        source=source,
        action_id=action_id,
    )


def _resolve_github_approval_endpoint() -> Optional[str]:
    base = os.environ.get("FHD_API_BASE_URL") or os.environ.get("MODSTORE_OPS_BASE_URL")
    if not base:
        return None
    return base.rstrip("/") + "/api/ops/autonomy/github-approval"


def _resolve_token() -> Optional[str]:
    return os.environ.get("AUTONOMY_WEBHOOK_TOKEN") or os.environ.get(
        "MODSTORE_OPS_INGEST_TOKEN"
    )


def _post_github_decision(
    *,
    action_id: str,
    decision: str,
    approver: str = "",
    approval_id: str = "",
    reason: str = "",
    outcome: Optional[dict[str, Any]] = None,
    workflow_action: str = "",
    source: str = "autonomy_callback",
) -> Optional[dict[str, Any]]:
    """统一 POST /github-approval；fail-open。"""
    if not action_id:
        print("[autonomy_callback] skip: action_id empty", file=sys.stderr)
        return None
    endpoint = _resolve_github_approval_endpoint()
    token = _resolve_token()
    if not endpoint or not token:
        print(
            f"[autonomy_callback] skip: endpoint or token missing "
            f"(decision={decision} action_id={action_id})",
            file=sys.stderr,
        )
        return None
    if httpx is None:
        print("[autonomy_callback] skip: httpx unavailable", file=sys.stderr)
        return None

    payload: dict[str, Any] = {
        "action_id": action_id,
        "decision": decision,
        "approver": approver or source,
        "approval_id": approval_id,
    }
    if reason:
        payload["reason"] = reason
    if outcome:
        payload["outcome"] = outcome
    if workflow_action:
        payload["workflow_action"] = workflow_action

    try:
        resp = httpx.post(
            endpoint,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Autonomy-Token": token,
                "X-Autonomy-Source": source,
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
    except Exception as exc:  # noqa: BLE001 - script boundary records arbitrary integration failures  # pragma: no cover
        print(f"[autonomy_callback] http error: {exc!r}", file=sys.stderr)
        return None

    if resp.status_code < 200 or resp.status_code >= 300:
        print(
            f"[autonomy_callback] non-2xx status={resp.status_code} "
            f"body={resp.text[:500]} decision={decision} action_id={action_id}",
            file=sys.stderr,
        )
        return None

    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - script boundary records arbitrary integration failures  # pragma: no cover
        print(f"[autonomy_callback] json decode error: {exc!r}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(
            f"[autonomy_callback] unexpected response type: {type(data).__name__}",
            file=sys.stderr,
        )
        return None
    return data


def report_executed(
    action_id: str,
    *,
    approver: str = "",
    approval_id: str = "",
    outcome: Optional[dict[str, Any]] = None,
    workflow_action: str = "",
    source: str = "autonomy_callback",
) -> Optional[dict[str, Any]]:
    """回调 /github-approval：decision=executed。"""
    return _post_github_decision(
        action_id=action_id,
        decision="executed",
        approver=approver,
        approval_id=approval_id,
        outcome=outcome,
        workflow_action=workflow_action,
        source=source,
    )


def report_execution_failed(
    action_id: str,
    *,
    approver: str = "",
    approval_id: str = "",
    error: str = "",
    outcome: Optional[dict[str, Any]] = None,
    workflow_action: str = "",
    source: str = "autonomy_callback",
) -> Optional[dict[str, Any]]:
    """回调 /github-approval：decision=execution_failed。"""
    merged_outcome = dict(outcome or {})
    if error:
        merged_outcome.setdefault("error", error)
    return _post_github_decision(
        action_id=action_id,
        decision="execution_failed",
        approver=approver,
        approval_id=approval_id,
        outcome=merged_outcome or None,
        workflow_action=workflow_action,
        source=source,
    )


def report_rejected(
    action_id: str,
    *,
    approver: str = "",
    reason: str = "",
    approval_id: str = "",
    source: str = "autonomy_callback",
) -> Optional[dict[str, Any]]:
    """回调 /github-approval：decision=rejected。"""
    return _post_github_decision(
        action_id=action_id,
        decision="rejected",
        approver=approver,
        approval_id=approval_id,
        reason=reason,
        source=source,
    )


def report_approval_requested(
    action_id: str,
    *,
    approval_id: str = "",
    workflow_action: str = "",
    source: str = "autonomy_callback",
) -> Optional[dict[str, Any]]:
    """回调 /github-approval：decision=approval_requested。"""
    return _post_github_decision(
        action_id=action_id,
        decision="approval_requested",
        approval_id=approval_id,
        workflow_action=workflow_action,
        source=source,
    )


__all__ = [
    "autonomy_callback",
    "report_callback",
    "deploy_callback",
    "report_executed",
    "report_execution_failed",
    "report_rejected",
    "report_approval_requested",
]
