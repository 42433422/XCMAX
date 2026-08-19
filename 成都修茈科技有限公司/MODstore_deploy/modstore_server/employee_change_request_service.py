"""员工变更申请：暂存 Agent 写入，批准后落盘。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from modstore_server.employee_change_request_submission import (
    defer_write_as_change_request as defer_write_as_change_request,
)
from modstore_server.employee_change_request_verification import (
    _git_suggestions as _git_suggestions,
)
from modstore_server.employee_change_request_verification import (
    _guard_under_workspace as _guard_under_workspace,
)
from modstore_server.employee_change_request_verification import (
    _maybe_run_post_apply_consistency as _maybe_run_post_apply_consistency,
)
from modstore_server.employee_change_request_verification import (
    _maybe_run_post_apply_pytest as _maybe_run_post_apply_pytest,
)
from modstore_server.employee_change_request_verification import (
    _request_post_apply_self_repair as _request_post_apply_self_repair,
)
from modstore_server.employee_change_request_verification import (
    _run_post_apply_verification as _run_post_apply_verification,
)

logger = logging.getLogger(__name__)


def apply_employee_change_request(
    change_request_id: int, approved_by_user_id: int
) -> Dict[str, Any]:
    """审批通过：落盘并发布 ``change_request.applied``；可选跑 pytest（环境变量）。"""
    from modstore_server.employee_runtime import load_employee_pack
    from modstore_server.employee_scope_policy import (
        relative_path_under_repo,
        validate_agent_repo_write,
        workspace_policy_from_manifest,
    )
    from modstore_server.incident_bus import publish
    from modstore_server.integrations.ops_action_handlers import repo_root as mod_repo_root
    from modstore_server.models import EmployeeChangeRequest, get_session_factory

    risk_level_snapshot = ""
    sf = get_session_factory()
    with sf() as session:
        row = session.get(EmployeeChangeRequest, int(change_request_id))
        if not row:
            return {"ok": False, "error": "not found"}
        if (row.status or "") != "pending":
            return {"ok": False, "error": f"status is {row.status}, expected pending"}

        try:
            data = json.loads(row.diff_blob or "{}")
        except json.JSONDecodeError:
            return {"ok": False, "error": "invalid diff_blob JSON"}

        rel = str(data.get("path") or "").strip()
        content = str(data.get("content") or "")
        ws = str(data.get("workspace_root") or row.workspace_root_hint or "").strip()
        if not rel or not ws:
            return {"ok": False, "error": "missing path or workspace_root"}

        resolved = _guard_under_workspace(ws, rel)
        if not resolved:
            row.status = "failed"
            row.error = "path outside workspace"
            session.commit()
            _publish_cr_result(
                int(change_request_id),
                str(row.source_employee_id or ""),
                False,
                "path outside workspace",
            )
            return {"ok": False, "error": "path outside workspace"}

        try:
            pack = load_employee_pack(session, str(row.source_employee_id or ""))
        except ValueError:
            pack = {"manifest": {}}
        manifest = pack.get("manifest") if isinstance(pack.get("manifest"), dict) else {}
        sg, fg, ag = workspace_policy_from_manifest(manifest)
        if not ag and isinstance(data, dict):
            ag = [
                str(x).strip()
                for x in (data.get("approval_required_globs_snapshot") or [])
                if str(x).strip()
            ]
        if not ag:
            try:
                ag = [
                    str(x).strip()
                    for x in json.loads(row.approval_required_globs_json or "[]")
                    if str(x).strip()
                ]
            except Exception:
                ag = []
        rel_repo = relative_path_under_repo(Path(resolved))
        if sg or fg:
            if not rel_repo:
                row.status = "failed"
                row.error = "path not under repository root for scope check"
                session.commit()
                return {"ok": False, "error": row.error}
            ok_sc, msg_sc = validate_agent_repo_write(rel_repo, sg, fg)
            if not ok_sc:
                row.status = "failed"
                row.error = msg_sc[:2000]
                session.commit()
                return {"ok": False, "error": msg_sc}

        # 冲突检测
        merge_strategy = os.environ.get("MODSTORE_CR_MERGE_STRATEGY", "overwrite").strip().lower()
        if merge_strategy in ("fail_on_conflict", "llm_merge"):
            try:
                from modstore_server.change_merge import detect_conflict, resolve_conflict

                has_conflict, conflicting_ids = detect_conflict(int(change_request_id), rel)
                if has_conflict:
                    logger.info(
                        "apply_CR %d: conflict detected with CRs %s, strategy=%s",
                        change_request_id,
                        conflicting_ids,
                        merge_strategy,
                    )
                    cr_result = resolve_conflict(int(change_request_id), merge_strategy)
                    if not cr_result.get("ok"):
                        _publish_cr_result(
                            int(change_request_id),
                            str(row.source_employee_id or ""),
                            False,
                            cr_result.get("error", "conflict"),
                        )
                        return {
                            "ok": False,
                            "error": cr_result.get("error", "conflict"),
                            "conflicting_crs": conflicting_ids,
                        }
                    merged = cr_result.get("merged_content")
                    if merged is not None:
                        content = merged
            except Exception:
                logger.exception("conflict detection failed for CR %d", change_request_id)

        try:
            Path(resolved).parent.mkdir(parents=True, exist_ok=True)
            Path(resolved).write_text(content, encoding="utf-8")
        except OSError as exc:
            row.status = "failed"
            row.error = str(exc)[:2000]
            session.commit()
            _publish_cr_result(
                int(change_request_id), str(row.source_employee_id or ""), False, str(exc)[:500]
            )
            return {"ok": False, "error": str(exc)[:500]}

        row.status = "applied"
        row.approved_by_user_id = int(approved_by_user_id)
        now = datetime.now(timezone.utc)
        row.approved_at = now
        row.applied_at = now
        session.commit()
        src = str(row.source_employee_id or "")
        diff_summary_snapshot = str(row.diff_summary or "")
        risk_level_snapshot = str(row.risk_level or "")

    try:
        publish(
            "change_request.applied",
            {
                "change_request_id": int(change_request_id),
                "path": rel[:500],
                "approved_by_user_id": int(approved_by_user_id),
            },
            source=src or "system",
        )
    except Exception:
        logger.exception("publish change_request.applied failed")

    repo = mod_repo_root()
    verify_out = _run_post_apply_verification(
        repo,
        change_request_id=int(change_request_id),
        source_employee_id=src or "system",
    )
    ci_out = (
        verify_out.get("pytest") if isinstance(verify_out.get("pytest"), dict) else {"ran": False}
    )
    consistency_out = (
        verify_out.get("consistency")
        if isinstance(verify_out.get("consistency"), dict)
        else {"ran": False}
    )
    try:
        publish(
            "change_request.ci_complete",
            {
                "change_request_id": int(change_request_id),
                **{k: v for k, v in ci_out.items() if k != "stdout_tail"},
                "stdout_tail_chars": len(ci_out.get("stdout_tail") or ""),
                "summary_ok": bool(ci_out.get("ok")),
            },
            source=src or "system",
        )
    except Exception:
        logger.exception("publish change_request.ci_complete failed")

    verify_ok = bool(verify_out.get("ok"))
    failed_checks = (
        verify_out.get("failed_checks") if isinstance(verify_out.get("failed_checks"), list) else []
    )
    failed_names = [str(x.get("name") or "") for x in failed_checks if isinstance(x, dict)]
    verify_reason = (
        f"post apply verify failed: {', '.join(x for x in failed_names if x) or 'unknown'}"
        if not verify_ok
        else "applied+verified"
    )

    try:
        publish(
            "change_request.verify_complete",
            {
                "change_request_id": int(change_request_id),
                "ok": verify_ok,
                "reason": str(verify_out.get("reason") or verify_reason)[:500],
                "failed_checks": failed_names[:10],
                "employee_id": src or "",
                "repo_relative_path": (rel_repo or rel)[:500],
                "consistency_ran": bool(consistency_out.get("ran")),
                "consistency_ok": bool(consistency_out.get("ok")),
                "consistency_total_errors": int(consistency_out.get("total_errors") or 0),
            },
            source=src or "system",
            fingerprint=None,
        )
    except Exception:
        logger.exception("publish change_request.verify_complete failed")

    self_repair_out: Dict[str, Any] = {"ok": False, "reason": "not_required"}
    try:
        sfv = get_session_factory()
        with sfv() as session:
            rv = session.get(EmployeeChangeRequest, int(change_request_id))
            if rv:
                rv.error = "" if verify_ok else verify_reason[:2000]
                session.commit()
    except Exception:
        logger.exception("update CR verify status failed for CR %d", change_request_id)

    if verify_ok:
        _publish_cr_result(int(change_request_id), src or "system", True, verify_reason)
    else:
        _publish_cr_result(int(change_request_id), src or "system", False, verify_reason)
        self_repair_out = _request_post_apply_self_repair(
            change_request_id=int(change_request_id),
            source_employee_id=src or "",
            repo_relative_path=rel_repo or rel,
            verify_out=verify_out,
        )

    git_branch = ""
    staged_commit = ""
    try:
        from modstore_server.models import EmployeeChangeRequest as _CR

        sf3 = get_session_factory()
        with sf3() as session:
            r3 = session.get(_CR, int(change_request_id))
            if r3:
                git_branch = str(r3.git_branch or "")
                staged_commit = str(r3.staged_commit_sha or "")
    except Exception:
        pass

    apply_commit_out: Dict[str, Any] = {"ok": False, "reason": "skipped"}
    pr_out: Dict[str, Any] = {"ok": False, "reason": "skipped"}
    try:
        from modstore_server.cr_git_pipeline import commit_cr_apply, maybe_open_pr_for_cr

        apply_commit_out = commit_cr_apply(
            int(change_request_id), src or "unknown", rel_repo or rel
        )
        if git_branch:
            pr_out = maybe_open_pr_for_cr(
                int(change_request_id),
                git_branch,
                summary=f"path={rel_repo or rel}\nsummary={diff_summary_snapshot[:1000]}",
                risk_level=str(risk_level_snapshot or ""),
            )
    except Exception:
        logger.exception("cr_git_pipeline post-apply hooks failed for CR %d", change_request_id)

    gs = _git_suggestions(
        int(change_request_id),
        rel_repo or rel,
        git_branch=git_branch,
        staged_commit=staged_commit,
    )
    deploy_event_out: Dict[str, Any] = {"ok": False, "reason": "not_required"}
    if verify_ok and (risk_level_snapshot or "").strip().lower() == "high":
        try:
            publish(
                "ops.change_request.approved",
                {
                    "change_request_id": int(change_request_id),
                    "risk_level": risk_level_snapshot,
                    "approved_by_user_id": int(approved_by_user_id or 0),
                    "source_employee_id": src or "",
                    "repo_relative_path": (rel_repo or rel)[:500],
                    "git_branch": git_branch[:256],
                    "staged_commit": staged_commit[:64],
                    "verify_ok": True,
                },
                source="change-request-auditor",
                fingerprint=None,
            )
            deploy_event_out = {"ok": True}
        except Exception as exc:
            logger.exception(
                "publish ops.change_request.approved failed for CR %d", change_request_id
            )
            deploy_event_out = {"ok": False, "error": str(exc)[:300]}
    return {
        "ok": True,
        "path": resolved,
        "repo_relative_path": rel_repo or rel,
        "git_suggestions": gs,
        "git_branch": git_branch,
        "staged_commit": staged_commit,
        "apply_commit": apply_commit_out,
        "pr": pr_out,
        "post_apply_pytest": ci_out,
        "post_apply_verify": verify_out,
        "post_apply_self_repair": self_repair_out,
        "deploy_event": deploy_event_out,
    }


def _publish_cr_result(cr_id: int, source_employee_id: str, ok: bool, reason: str) -> None:
    """发布 change_request.result 事件，让员工订阅自己的 CR 审批结果。"""
    try:
        from modstore_server.incident_bus import publish

        publish(
            "change_request.result",
            {
                "change_request_id": cr_id,
                "ok": ok,
                "reason": reason[:500],
                "employee_id": source_employee_id,
            },
            source=source_employee_id or "system",
            fingerprint=None,
        )
    except Exception:
        logger.exception("_publish_cr_result failed for CR %d", cr_id)


def reject_employee_change_request(
    change_request_id: int,
    *,
    rejected_reason: str,
    rejected_by_user_id: int,
) -> Dict[str, Any]:
    from modstore_server.models import EmployeeChangeRequest, User, get_session_factory

    src = ""
    sf = get_session_factory()
    with sf() as session:
        row = session.get(EmployeeChangeRequest, int(change_request_id))
        if not row:
            return {"ok": False, "error": "not found"}
        if (row.status or "") != "pending":
            return {"ok": False, "error": f"status is {row.status}"}
        src = str(row.source_employee_id or "")
        row.status = "rejected"
        row.rejected_reason = (rejected_reason or "")[:4000]
        actor_id = int(rejected_by_user_id or 0)
        row.approved_by_user_id = actor_id if actor_id > 0 and session.get(User, actor_id) else None
        row.approved_at = datetime.now(timezone.utc)
        session.commit()

    _publish_cr_result(int(change_request_id), src, False, rejected_reason or "rejected")
    return {"ok": True}


__all__ = [
    "defer_write_as_change_request",
    "apply_employee_change_request",
    "reject_employee_change_request",
    "_publish_cr_result",
]
