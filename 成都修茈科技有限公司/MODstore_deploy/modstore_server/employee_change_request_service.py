"""员工变更申请：暂存 Agent 写入，批准后落盘。"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


def defer_write_as_change_request(
    source_employee_id: str,
    workspace_root: str,
    path: str,
    content: str,
    *,
    scope_globs: Optional[Sequence[str]] = None,
    forbidden_globs: Optional[Sequence[str]] = None,
    approval_required_globs: Optional[Sequence[str]] = None,
) -> int:
    """不落盘，写入 ``EmployeeChangeRequest``；返回记录 id。"""
    resolved = _guard_under_workspace(workspace_root, path)
    if resolved:
        sg = [str(x).strip() for x in (scope_globs or []) if str(x).strip()]
        fg = [str(x).strip() for x in (forbidden_globs or []) if str(x).strip()]
        if sg or fg:
            from modstore_server.employee_scope_policy import (
                relative_path_under_repo,
                validate_agent_repo_write,
            )

            rel_repo = relative_path_under_repo(Path(resolved))
            if not rel_repo:
                raise ValueError("无法在仓库根下解析路径（审批暂存仍需 scope 校验）")
            ok_sc, msg_sc = validate_agent_repo_write(rel_repo, sg, fg)
            if not ok_sc:
                raise ValueError(msg_sc)

    from modstore_server.incident_bus import publish
    from modstore_server.models import EmployeeChangeRequest, get_session_factory

    ws = str(workspace_root or "").strip()
    summary = f"write {path} ({len(content or '')} chars)"
    sg = [str(x).strip() for x in (scope_globs or []) if str(x).strip()]
    fg = [str(x).strip() for x in (forbidden_globs or []) if str(x).strip()]
    ag = [str(x).strip() for x in (approval_required_globs or []) if str(x).strip()]
    blob = json.dumps(
        {
            "path": path,
            "content": content or "",
            "workspace_root": ws,
            "scope_globs_snapshot": sg,
            "forbidden_globs_snapshot": fg,
            "approval_required_globs_snapshot": ag,
        },
        ensure_ascii=False,
    )
    paths_json = json.dumps([path], ensure_ascii=False)

    # 评估风险等级
    try:
        from modstore_server.auto_approve_policy import evaluate_risk

        risk_level, _reason = evaluate_risk(
            path,
            content or "",
            scope_globs=sg,
            forbidden_globs=fg,
            approval_required_globs=ag,
        )
    except Exception:
        risk_level = "medium"

    sf = get_session_factory()
    with sf() as session:
        row = EmployeeChangeRequest(
            source_employee_id=source_employee_id[:128],
            change_kind="code_patch",
            workspace_root_hint=ws[:512],
            target_paths_json=paths_json,
            diff_summary=summary,
            diff_blob=blob[:500_000],
            status="pending",
            risk_level=risk_level,
            approval_required_globs_json=json.dumps(ag, ensure_ascii=False)[:8000],
        )
        session.add(row)
        session.flush()
        cid = int(row.id)
        session.commit()

    rel_for_branch = ""
    if resolved:
        try:
            from modstore_server.employee_scope_policy import relative_path_under_repo

            rel_for_branch = relative_path_under_repo(Path(resolved))
        except Exception:
            rel_for_branch = ""

    if rel_for_branch:
        try:
            from modstore_server.cr_git_pipeline import stage_file_to_employee_branch

            stage_out = stage_file_to_employee_branch(
                cid,
                source_employee_id,
                rel_for_branch,
                content or "",
            )
            if stage_out.get("ok"):
                sf2 = get_session_factory()
                with sf2() as session:
                    row2 = session.get(EmployeeChangeRequest, cid)
                    if row2:
                        row2.git_branch = str(stage_out.get("branch") or "")[:256]
                        row2.base_commit_sha = str(stage_out.get("base_commit") or "")[:64]
                        row2.staged_commit_sha = str(stage_out.get("staged_commit") or "")[:64]
                        session.commit()
            else:
                logger.info(
                    "cr_git_pipeline.stage skipped CR %d: %s",
                    cid,
                    stage_out.get("reason"),
                )
        except Exception:
            logger.exception("cr_git_pipeline.stage failed for CR %d", cid)

    try:
        publish(
            "change_request.created",
            {
                "change_request_id": cid,
                "path": path[:500],
                "summary": summary[:500],
                "risk_level": risk_level,
            },
            source=source_employee_id,
        )
    except Exception:
        logger.exception("publish change_request.created failed")
    try:
        publish(
            "ops.change_request.submitted",
            {
                "change_request_id": cid,
                "path": path[:500],
                "summary": summary[:500],
                "risk_level": risk_level,
                "source_employee_id": source_employee_id[:128],
            },
            source=source_employee_id,
            fingerprint=None,
        )
    except Exception:
        logger.exception("publish ops.change_request.submitted failed")

    # 低风险尝试自动审批
    try:
        from modstore_server.auto_approve_policy import maybe_auto_approve

        maybe_auto_approve(cid)
    except Exception:
        logger.exception("auto_approve check failed for CR %d", cid)

    return cid


def _guard_under_workspace(workspace_root: str, rel_path: str) -> Optional[str]:
    """与 mod_employee_agent_runner._guard_path 一致。"""
    import os

    resolved = os.path.normpath(os.path.join(workspace_root, rel_path))
    workspace_abs = os.path.abspath(workspace_root)
    if not resolved.startswith(workspace_abs + os.sep) and resolved != workspace_abs:
        return None
    return resolved


def _git_suggestions(
    change_request_id: int,
    rel_repo_path: str,
    *,
    git_branch: str = "",
    staged_commit: str = "",
) -> List[str]:
    """返回管理员可以拷贝执行的 git 命令清单。

    若 ``git_branch`` 已落地（``cr_git_pipeline`` 成功），则返回基于该分支的真实
    合并 / PR 命令；否则退回到旧的"自己 checkout 一条分支"的建议。
    """
    rp = (rel_repo_path or "").replace("\\", "/").strip()
    if git_branch:
        cmds = [
            f"# 该 CR 已暂存到分支 {git_branch} (staged_commit={staged_commit[:10] or 'n/a'})",
            f"git fetch . refs/heads/{git_branch}:refs/heads/{git_branch}  # no-op if already local",
            f"git merge --no-ff {git_branch} -m 'merge CR-{change_request_id}'",
            "git push origin HEAD",
        ]
        return cmds
    return [
        f"git checkout -b chore/employee-cr-{change_request_id}",
        f"git add -- {rp}" if rp else "git add -p",
        f'git commit -m "chore: apply employee change request {change_request_id}"',
        "# gh pr create --fill",
    ]


def _maybe_run_post_apply_pytest(repo_root: Path) -> Dict[str, Any]:
    raw = (os.environ.get("MODSTORE_POST_APPLY_PYTEST") or "").strip().lower()
    if raw not in ("1", "true", "yes", "on"):
        return {"ran": False}
    tests_dir = repo_root / "MODstore_deploy" / "tests"
    if not tests_dir.is_dir():
        return {"ran": False, "reason": "MODstore_deploy/tests not found"}
    try:
        timeout = float(os.environ.get("MODSTORE_POST_APPLY_PYTEST_TIMEOUT", "300"))
    except ValueError:
        timeout = 300.0
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests_dir), "-q", "--tb=no", "-x"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    out = (proc.stdout or "")[-12_000:]
    err = (proc.stderr or "")[-4000:]
    return {
        "ran": True,
        "exit_code": int(proc.returncode),
        "stdout_tail": out,
        "stderr_tail": err,
        "ok": proc.returncode == 0,
    }


def _maybe_run_post_apply_consistency(
    repo_root: Path,
    *,
    change_request_id: int = 0,
    source_employee_id: str = "",
) -> Dict[str, Any]:
    raw = (os.environ.get("MODSTORE_POST_APPLY_CONSISTENCY", "1") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return {"ran": False}
    try:
        from modstore_server.tools.doc_consistency_checker import run_full_consistency_check

        out = run_full_consistency_check(
            repo_root,
            publish_event=False,
            source="change_request_verify",
            source_ref=f"cr-{int(change_request_id or 0)}:{(source_employee_id or '')[:128]}",
            trigger_autofix=False,
        )
    except TypeError:
        # 兼容旧签名
        from modstore_server.tools.doc_consistency_checker import run_full_consistency_check

        out = run_full_consistency_check(repo_root)
    except Exception as exc:
        return {"ran": True, "ok": False, "error": str(exc)[:500]}

    issues = out.get("issues") if isinstance(out.get("issues"), list) else []
    sample = []
    for it in issues[:30]:
        if not isinstance(it, dict):
            continue
        sample.append(
            {
                "employee": str(it.get("employee") or ""),
                "type": str(it.get("type") or ""),
                "severity": str(it.get("severity") or ""),
                "description": str(it.get("description") or "")[:300],
            }
        )
    total_errors = int(out.get("total_errors") or 0)
    total_issues = int(out.get("total_issues") or 0)
    return {
        "ran": True,
        "ok": total_errors == 0,
        "status": str(out.get("status") or ""),
        "total_errors": total_errors,
        "total_issues": total_issues,
        "issues_sample": sample,
    }


def _run_post_apply_verification(
    repo_root: Path,
    *,
    change_request_id: int,
    source_employee_id: str,
) -> Dict[str, Any]:
    pytest_out = _maybe_run_post_apply_pytest(repo_root)
    consistency_out = _maybe_run_post_apply_consistency(
        repo_root,
        change_request_id=change_request_id,
        source_employee_id=source_employee_id,
    )
    checks: List[Dict[str, Any]] = []
    if pytest_out.get("ran"):
        checks.append(
            {
                "name": "pytest",
                "ok": bool(pytest_out.get("ok")),
                "error": str(pytest_out.get("stderr_tail") or "")[:400],
            }
        )
    if consistency_out.get("ran"):
        checks.append(
            {
                "name": "consistency",
                "ok": bool(consistency_out.get("ok")),
                "error": str(consistency_out.get("error") or "")[:400],
            }
        )
    failed = [c for c in checks if not bool(c.get("ok"))]
    reason = ""
    if failed:
        reason = "failed: " + ", ".join(str(c.get("name") or "?") for c in failed)
    return {
        "ok": len(failed) == 0,
        "checks": checks,
        "failed_checks": failed,
        "reason": reason,
        "pytest": pytest_out,
        "consistency": consistency_out,
    }


def _request_post_apply_self_repair(
    *,
    change_request_id: int,
    source_employee_id: str,
    repo_relative_path: str,
    verify_out: Dict[str, Any],
) -> Dict[str, Any]:
    src = str(source_employee_id or "").strip()
    if not src:
        return {"ok": False, "reason": "source employee empty"}
    try:
        from modstore_server.employee_autonomy_service import create_employee_suggestion

        detail = (
            f"CR-{change_request_id} 已落盘，但后置验证失败。\n"
            f"失败项：{', '.join(str(x.get('name') or '') for x in (verify_out.get('failed_checks') or [])) or 'unknown'}\n"
            f"路径：{repo_relative_path}\n"
            f"请自行修复并重新提交 CR。\n\n"
            f"verify={json.dumps(verify_out, ensure_ascii=False)[:12000]}"
        )
        out = create_employee_suggestion(
            source_employee_id="cr-verifier",
            summary=f"CR-{change_request_id} 后置验证失败，回流给 {src}",
            detail=detail,
            payload={
                "kind": "change_request_verify_failed",
                "change_request_id": int(change_request_id),
                "employee_id": src,
                "repo_relative_path": (repo_relative_path or "")[:500],
                "verify": verify_out,
                "target_employee_ids": [src],
            },
            target_employee_ids=[src],
            kind="change_request_verify_failed",
            risk_level="low",
            emit_event=True,
            auto_dispatch=True,
        )
        return out if isinstance(out, dict) else {"ok": False, "reason": "invalid result"}
    except Exception as exc:
        logger.exception("request post-apply self repair failed for CR %d", change_request_id)
        return {"ok": False, "error": str(exc)[:500]}


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
    from modstore_server.models import EmployeeChangeRequest, get_session_factory

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
        row.approved_by_user_id = int(rejected_by_user_id)
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
