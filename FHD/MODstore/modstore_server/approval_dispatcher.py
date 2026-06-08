"""邮件 token 校验后的部署链：git push → 本地 sync 脚本 → 健康检查。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from modstore_server.datetime_utils import as_utc_aware
from modstore_server.email_service import send_simple_html_email
from modstore_server.employee_change_request_service import apply_employee_change_request
from modstore_server.integrations.ops_action_handlers import (
    APPROVAL_DISPATCHER_EMPLOYEE_ID,
    dispatch_ops_handler,
)
from modstore_server.models import OpsApprovalToken, OpsStagedChange, User, get_session_factory

logger = logging.getLogger(__name__)


def _first_admin_user_id() -> int:
    sf = get_session_factory()
    with sf() as session:
        u = session.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()  # noqa: E712
        if u:
            return int(u.id)
        u2 = session.query(User).order_by(User.id.asc()).first()
        return int(u2.id) if u2 else 0


def _shell_cfg(command_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {"shell_exec": {"command_id": command_id, "args": args}}


def _run_cmd(command_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return dispatch_ops_handler(
        "shell_exec",
        _shell_cfg(command_id, args),
        {},
        "email approval token",
        APPROVAL_DISPATCHER_EMPLOYEE_ID,
        0,
        force_real_run=True,
    )


def _notify_failure(subject: str, html: str) -> None:
    to_email = os.environ.get("MODSTORE_DAILY_DIGEST_EMAIL", "1499383833@qq.com").strip()
    if not to_email:
        return
    try:
        send_simple_html_email(to_email, subject, html)
    except Exception:
        logger.exception("approval notify email failed")


def deploy_staged_change(staged_id: int) -> Dict[str, Any]:
    """对单条待审记录执行 push + sync + probe（不写 token 状态）。"""
    sf = get_session_factory()
    with sf() as session:
        row = session.get(OpsStagedChange, staged_id)
        if not row or row.status != "pending":
            return {"ok": False, "error": "staged change not pending"}
        branch = row.branch
        remote = os.environ.get("MODSTORE_DEPLOY_PUSH_REMOTE", "origin").strip() or "origin"

    audit_ids: List[int] = []
    r1 = _run_cmd("git-push-branch", {"branch": branch, "remote": remote})
    if r1.get("audit_log_id"):
        audit_ids.append(r1["audit_log_id"])
    if not r1.get("ok"):
        _mark_staged_failed(staged_id, audit_ids)
        _notify_failure(
            f"MODstore 部署失败（git push）· {branch}",
            f"<p>git-push-branch 失败。</p><pre>{json.dumps(r1, ensure_ascii=False)[:4000]}</pre>",
        )
        return {"ok": False, "error": "git push failed", "detail": r1, "audit_ids": audit_ids}

    r2 = _run_cmd("local-sync-deploy", {})
    if r2.get("audit_log_id"):
        audit_ids.append(r2["audit_log_id"])
    if not r2.get("ok"):
        _mark_staged_failed(staged_id, audit_ids)
        _notify_failure(
            f"MODstore 部署失败（sync）· {branch}",
            f"<p>local-sync-deploy 失败。</p><pre>{json.dumps(r2, ensure_ascii=False)[:4000]}</pre>",
        )
        return {"ok": False, "error": "sync failed", "detail": r2, "audit_ids": audit_ids}

    r3 = _run_cmd("http-probe-after-deploy", {})
    probe_id = r3.get("audit_log_id")
    if probe_id:
        audit_ids.append(probe_id)
    if not r3.get("ok"):
        _mark_staged_failed(staged_id, audit_ids)
        _notify_failure(
            f"MODstore 部署失败（健康检查）· {branch}",
            f"<p>http-probe-after-deploy 失败。</p><pre>{json.dumps(r3, ensure_ascii=False)[:4000]}</pre>",
        )
        return {"ok": False, "error": "health probe failed", "detail": r3, "audit_ids": audit_ids}

    from modstore_server.post_deploy_smoke import run_post_deploy_smoke

    smoke = run_post_deploy_smoke()
    if not smoke.get("ok") and not smoke.get("skipped"):
        _mark_staged_failed(staged_id, audit_ids)
        _notify_failure(
            f"MODstore 部署失败（发布后 smoke）· {branch}",
            f"<p>post_deploy_smoke 失败（health + market/download）。</p>"
            f"<pre>{json.dumps(smoke, ensure_ascii=False)[:4000]}</pre>",
        )
        return {"ok": False, "error": "post deploy smoke failed", "detail": smoke, "audit_ids": audit_ids}

    _mark_staged_deployed(staged_id, probe_id, audit_ids)
    try:
        from modstore_server.digest_action_items import sync_merged_on_deploy

        sync_merged_on_deploy()
    except Exception:
        logger.exception("action_items merge writeback failed staged_id=%s", staged_id)

    # 自动 merge PR（若启用）
    auto_pr = os.environ.get("MODSTORE_AUTO_PR_ENABLED", "1").strip().lower() in ("1", "true", "yes", "on")
    if auto_pr:
        try:
            _maybe_merge_pr(branch)
        except Exception as _merr:
            logger.warning("auto PR merge failed for branch %s: %s", branch, _merr)

    return {"ok": True, "audit_ids": audit_ids, "probe_audit_id": probe_id, "post_deploy_smoke": smoke}


def _mark_staged_failed(staged_id: int, audit_ids: List[int]) -> None:
    sf = get_session_factory()
    with sf() as session:
        row = session.get(OpsStagedChange, staged_id)
        if row:
            row.status = "failed"
            session.commit()


def _mark_staged_deployed(staged_id: int, probe_audit_id: Optional[int], audit_ids: List[int]) -> None:
    sf = get_session_factory()
    now = datetime.now(timezone.utc)
    with sf() as session:
        row = session.get(OpsStagedChange, staged_id)
        if row:
            row.status = "deployed"
            row.deployed_at = now
            row.approved_at = row.approved_at or now
            row.deploy_audit_id = probe_audit_id
            session.commit()


def handle_token_row(token_id: int, *, message_id: str = "") -> Dict[str, Any]:
    """消费一条已解析的 OpsApprovalToken（按 id）。"""
    sf = get_session_factory()
    with sf() as session:
        tok = session.get(OpsApprovalToken, token_id)
        if not tok:
            return {"ok": False, "error": "token not found"}
        if tok.used_at is not None:
            return {"ok": False, "error": "token already used"}
        if as_utc_aware(tok.expires_at) < datetime.now(timezone.utc):
            return {"ok": False, "error": "token expired"}

        kind = (tok.kind or "").strip()
        payload = json.loads(tok.payload_json or "{}")

        tok.used_at = datetime.now(timezone.utc)
        tok.consumed_message_id = (message_id or "")[:512]
        session.commit()

    all_audit: List[int] = []

    try:
        if kind == "reject_all":
            return _do_reject_all(token_id, all_audit)

        if kind == "approve_one":
            sid = int(payload.get("staged_change_id") or 0)
            if not sid:
                _finalize_token_audit(token_id, all_audit)
                return {"ok": False, "error": "missing staged_change_id"}
            res = deploy_staged_change(sid)
            if res.get("audit_ids"):
                all_audit.extend(res["audit_ids"])
            _finalize_token_audit(token_id, all_audit)
            return res

        if kind == "apply_change_request":
            cr_id = int(payload.get("change_request_id") or 0)
            if not cr_id:
                _finalize_token_audit(token_id, all_audit)
                return {"ok": False, "error": "missing change_request_id"}
            approver = int(payload.get("approved_by_user_id") or 0)
            if approver <= 0:
                approver = _first_admin_user_id()
            res = apply_employee_change_request(cr_id, approver)
            _finalize_token_audit(token_id, all_audit)
            return res

        if kind == "approve_all":
            sf2 = get_session_factory()
            with sf2() as session:
                pending = (
                    session.query(OpsStagedChange)
                    .filter(OpsStagedChange.status == "pending")
                    .order_by(OpsStagedChange.id.asc())
                    .all()
                )
                ids = [r.id for r in pending]
            results: List[Dict[str, Any]] = []
            for sid in ids:
                res = deploy_staged_change(sid)
                results.append(res)
                if res.get("audit_ids"):
                    all_audit.extend(res["audit_ids"])
                if not res.get("ok"):
                    _finalize_token_audit(token_id, all_audit)
                    return {"ok": False, "error": "approve_all stopped on failure", "results": results}
            _finalize_token_audit(token_id, all_audit)
            return {"ok": True, "results": results}

        if kind == "digest_identity":
            _finalize_token_audit(token_id, all_audit)
            return {"ok": True, "identity_ack": True}

        _finalize_token_audit(token_id, all_audit)
        return {"ok": False, "error": f"unknown token kind: {kind}"}
    except Exception as e:  # noqa: BLE001
        logger.exception("handle_token_row failed: %s", e)
        _finalize_token_audit(token_id, all_audit)
        _notify_failure("MODstore 审批执行异常", f"<pre>{str(e)[:4000]}</pre>")
        return {"ok": False, "error": str(e)}


def _do_reject_all(token_id: int, all_audit: List[int]) -> Dict[str, Any]:
    sf = get_session_factory()
    with sf() as session:
        q = session.query(OpsStagedChange).filter(OpsStagedChange.status == "pending").all()
        n = 0
        for row in q:
            row.status = "rejected"
            n += 1
        session.commit()
    _finalize_token_audit(token_id, all_audit)
    return {"ok": True, "rejected": n}


def _finalize_token_audit(token_id: int, audit_ids: List[int]) -> None:
    sf = get_session_factory()
    with sf() as session:
        tok = session.get(OpsApprovalToken, token_id)
        if tok:
            tok.dispatched_audit_ids_json = json.dumps(audit_ids[-50:])
            session.commit()


def _maybe_merge_pr(branch: str) -> None:
    """尝试 merge 对应分支的 PR（CI 通过后）。"""
    import subprocess

    from modstore_server.integrations.ops_action_handlers import repo_root

    root = repo_root()
    proc = subprocess.run(
        ["gh", "pr", "merge", "--merge", "--auto", branch],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        logger.info("auto merge PR for branch %s: %s", branch, proc.stderr[:200])


def handle_incoming_approval_email(*, from_addr: str, body: str, message_id: str) -> Dict[str, Any]:
    """解析一封回信：From 白名单 + 正文中的 6 位 hex token。"""
    import hashlib
    import re

    auth = os.environ.get("MODSTORE_APPROVAL_AUTHORIZED_FROM", "1499383833@qq.com").strip().lower()
    if (from_addr or "").strip().lower() != auth:
        return {"ok": False, "skip": True, "reason": "from not authorized"}

    found: List[str] = []
    for m in re.finditer(r"\b[A-F0-9]{6}\b", body or "", re.IGNORECASE):
        found.append(m.group(0).upper())
    if not found:
        return {"ok": False, "skip": True, "reason": "no token in body"}

    for plain in found:
        h = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        sf = get_session_factory()
        with sf() as session:
            tok = (
                session.query(OpsApprovalToken)
                .filter(
                    OpsApprovalToken.token_hash == h,
                    OpsApprovalToken.used_at.is_(None),
                    OpsApprovalToken.expires_at > datetime.now(timezone.utc),
                )
                .first()
            )
            if not tok:
                continue
            tid = int(tok.id)
        return handle_token_row(tid, message_id=message_id)

    return {"ok": False, "skip": True, "reason": "no matching token"}
