"""Submission workflow for deferred employee code changes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Sequence

from modstore_server.employee_change_request_verification import _guard_under_workspace

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
        from modstore_server.auto_approve_policy import classify_change_risk

        risk_level, _reason = classify_change_risk(
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

    # 所有风险等级统一经 autonomy_guard；高风险必须停在人工审批队列。
    try:
        from modstore_server.auto_approve_policy import maybe_auto_approve

        auto_result = maybe_auto_approve(cid, skip_retort_block_check=True)
    except Exception:
        logger.exception("auto_approve check failed for CR %d", cid)
        auto_result = {"auto_approved": False}

    if not auto_result.get("auto_approved"):
        try:
            from modstore_server.retort_clarification_gate import (
                open_clarification_for_change_request,
            )

            open_clarification_for_change_request(
                cid,
                strategy_intent=summary,
                changed_files=[path],
                source_employee_id=source_employee_id,
                risk_level=risk_level,
            )
        except Exception:
            logger.exception("retort clarification open failed for CR %d", cid)

    return cid
