# mypy: disable-error-code="index"
"""Path guards and post-apply verification for employee change requests."""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def _guard_under_workspace(workspace_root: str, path: str) -> Optional[str]:
    """Reject traversal and symlinks, including links within the workspace."""
    root_path = Path(os.path.abspath(workspace_root))
    try:
        if root_path.is_symlink():
            return None
        root = str(root_path.parent.resolve() / root_path.name)
        relative = os.path.relpath(
            os.path.abspath(os.path.join(root_path, path)), root_path
        )
        resolved = os.path.abspath(os.path.join(root, relative))
        if os.path.commonpath((root, resolved)) != root:
            return None
        if any(part.is_symlink() for part in (Path(resolved), *Path(resolved).parents)):
            return None
    except (OSError, ValueError):
        return None
    return resolved


@contextmanager
def _workspace_fd(
    root: str, path: str, *, write: bool = False, directory: bool = False
):
    """Anchor every component to an open directory; never follow a replaced link."""
    target = _guard_under_workspace(root, path)
    if (
        target is None
        or not hasattr(os, "O_NOFOLLOW")
        or os.open not in os.supports_dir_fd
    ):
        raise OSError("workspace isolation unavailable or path rejected")
    parts = Path(target).parts[1:]
    fd = os.open(os.path.sep, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(parts):
            final = index == len(parts) - 1
            if write and not final:
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
            flags = os.O_NOFOLLOW | os.O_NONBLOCK
            flags |= (os.O_WRONLY | os.O_CREAT) if write and final else os.O_RDONLY
            if not final or directory:
                flags |= os.O_DIRECTORY
            child = os.open(part, flags, 0o600, dir_fd=fd)
            os.close(fd)
            fd = child
        if not directory and not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("workspace target must be a regular file")
        yield fd
    finally:
        os.close(fd)


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
        from modstore_server.tools.doc_consistency_checker import (
            run_full_consistency_check,
        )

        out = run_full_consistency_check(
            repo_root,
            publish_event=False,
            source="change_request_verify",
            source_ref=f"cr-{int(change_request_id or 0)}:{(source_employee_id or '')[:128]}",
            trigger_autofix=False,
        )
    except TypeError:
        # 兼容旧签名
        from modstore_server.tools.doc_consistency_checker import (
            run_full_consistency_check,
        )

        out = run_full_consistency_check(repo_root)
    except RECOVERABLE_ERRORS as exc:
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
        return (
            out if isinstance(out, dict) else {"ok": False, "reason": "invalid result"}
        )
    except RECOVERABLE_ERRORS as exc:
        logger.exception(
            "request post-apply self repair failed for CR %d", change_request_id
        )
        return {"ok": False, "error": str(exc)[:500]}
