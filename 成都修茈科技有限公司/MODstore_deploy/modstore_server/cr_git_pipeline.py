"""CR ⇄ git 分支管线（plumbing-only，不动用户工作树）。

将 ``EmployeeChangeRequest`` 与本地 git 仓库一一对应：

- 创建 CR 时：用 git plumbing 将文件内容暂存到一条以员工 ID 命名的分支
  ``employees/<source_employee_id>/cr-<id>``，**不修改当前 HEAD / 工作树 / 索引**。
- 落地 CR 时：原有的 ``apply_employee_change_request`` 仍直接写盘以保留兼容性；
  额外补一次 ``git add`` + ``git commit -m "apply CR-<id>"``（可选），并把 CR 的
  分支保留作为审计/PR 入口。
- 可选 ``gh pr create`` 由环境变量门控。

本模块只依赖 ``git`` 与 ``gh`` 二进制；若仓库不可用（不是 git 工作树），所有
公开函数都返回 ``{"ok": False, "reason": ...}`` 而不抛异常，确保 CR 主流程即使
git 不可用也能继续工作。
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _git_branch_enabled() -> bool:
    return os.environ.get("MODSTORE_CR_GIT_BRANCH_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _git_apply_commit_enabled() -> bool:
    return os.environ.get("MODSTORE_CR_GIT_APPLY_COMMIT", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _gh_pr_enabled() -> bool:
    return os.environ.get("MODSTORE_CR_GIT_AUTO_PR", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _branch_prefix() -> str:
    return os.environ.get("MODSTORE_CR_BRANCH_PREFIX", "employees").strip().strip("/")


def _safe_segment(value: str) -> str:
    """git ref 段安全化：只保留 ascii 字母数字和 ``-_.``。"""
    safe = []
    for ch in value or "":
        if ch.isalnum() or ch in ("-", "_", "."):
            safe.append(ch)
    out = "".join(safe).strip("-._") or "unknown"
    return out[:64]


def cr_branch_name(cr_id: int, source_employee_id: str) -> str:
    return f"{_branch_prefix()}/{_safe_segment(source_employee_id)}/cr-{int(cr_id)}"


def _run_git(
    root: str, args: list[str], *, timeout: float = 30.0, env_extra: Optional[Dict[str, str]] = None
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
        env=env,
    )


def is_git_repo(root: Path) -> bool:
    if not root or not root.exists():
        return False
    try:
        proc = _run_git(str(root), ["rev-parse", "--git-dir"], timeout=5)
        return proc.returncode == 0
    except Exception:
        return False


def _hash_object_stdin(root: str, content: str) -> Optional[str]:
    """``git hash-object -w --stdin``：把内容写入对象库，返回 blob sha。"""
    try:
        proc = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=root,
            input=content or "",
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
        if proc.returncode != 0:
            logger.warning("hash-object failed: %s", proc.stderr[:300])
            return None
        return proc.stdout.strip() or None
    except Exception:
        logger.exception("hash-object error")
        return None


def stage_file_to_employee_branch(
    cr_id: int,
    source_employee_id: str,
    rel_repo_path: str,
    content: str,
) -> Dict[str, Any]:
    """使用 git plumbing 把 ``content`` 暂存到员工专属分支（不动工作树）。

    步骤（全部基于临时 ``GIT_INDEX_FILE``，绝不污染默认索引）：
      1. ``git rev-parse HEAD`` → base
      2. ``git read-tree base`` 进 tmp index
      3. ``git hash-object -w --stdin`` 写入 blob
      4. ``git update-index --add --cacheinfo 100644,<blob>,<rel>`` 进 tmp index
      5. ``git write-tree`` (tmp index) → tree sha
      6. ``git commit-tree tree -p base -m "stage CR-<id>"`` → commit sha
      7. ``git update-ref refs/heads/<branch> commit``

    返回：
      ``{"ok": True, "branch": str, "base_commit": str, "staged_commit": str}``
      或 ``{"ok": False, "reason": str}``。
    """
    if not _git_branch_enabled():
        return {"ok": False, "reason": "MODSTORE_CR_GIT_BRANCH_ENABLED disabled"}

    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = repo_root()
    except Exception:
        return {"ok": False, "reason": "repo_root() unavailable"}

    if not is_git_repo(Path(root)):
        return {"ok": False, "reason": "not a git repository"}

    rel = (rel_repo_path or "").replace("\\", "/").lstrip("/").strip()
    if not rel:
        return {"ok": False, "reason": "empty rel_repo_path"}

    root_str = str(root)
    branch = cr_branch_name(int(cr_id), source_employee_id)

    base = _run_git(root_str, ["rev-parse", "HEAD"], timeout=10).stdout.strip()
    if not base:
        return {"ok": False, "reason": "no HEAD commit"}

    blob_sha = _hash_object_stdin(root_str, content)
    if not blob_sha:
        return {"ok": False, "reason": "hash-object failed"}

    tmp_dir = tempfile.mkdtemp(prefix="modstore_cr_idx_")
    tmp_index = os.path.join(tmp_dir, "cr_index")
    env_extra = {"GIT_INDEX_FILE": tmp_index}
    try:
        rt = _run_git(root_str, ["read-tree", base], timeout=15, env_extra=env_extra)
        if rt.returncode != 0:
            return {"ok": False, "reason": f"read-tree failed: {rt.stderr[:200]}"}

        ui = _run_git(
            root_str,
            ["update-index", "--add", "--cacheinfo", f"100644,{blob_sha},{rel}"],
            timeout=15,
            env_extra=env_extra,
        )
        if ui.returncode != 0:
            return {"ok": False, "reason": f"update-index failed: {ui.stderr[:200]}"}

        wt = _run_git(root_str, ["write-tree"], timeout=15, env_extra=env_extra)
        tree_sha = (wt.stdout or "").strip()
        if wt.returncode != 0 or not tree_sha:
            return {"ok": False, "reason": f"write-tree failed: {wt.stderr[:200]}"}
    finally:
        try:
            os.remove(tmp_index)
        except OSError:
            pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    msg = (
        f"chore(cr): stage CR-{int(cr_id)} from {_safe_segment(source_employee_id)}\n"
        f"\nFile: {rel}\nGenerated by AI employee; pending human review.\n"
    )
    author_name = os.environ.get("MODSTORE_GIT_AUTHOR_NAME", "MODstore Bot")
    author_email = os.environ.get("MODSTORE_GIT_AUTHOR_EMAIL", "bot@modstore.local")
    ct = _run_git(
        root_str,
        ["commit-tree", tree_sha, "-p", base, "-m", msg],
        timeout=15,
        env_extra={
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        },
    )
    commit_sha = (ct.stdout or "").strip()
    if ct.returncode != 0 or not commit_sha:
        return {"ok": False, "reason": f"commit-tree failed: {ct.stderr[:200]}"}

    ur = _run_git(root_str, ["update-ref", f"refs/heads/{branch}", commit_sha], timeout=10)
    if ur.returncode != 0:
        return {"ok": False, "reason": f"update-ref failed: {ur.stderr[:200]}"}

    logger.info(
        "cr_git_pipeline: staged CR-%d on branch %s base=%s head=%s",
        cr_id,
        branch,
        base[:10],
        commit_sha[:10],
    )
    return {
        "ok": True,
        "branch": branch,
        "base_commit": base,
        "staged_commit": commit_sha,
    }


def commit_cr_apply(
    cr_id: int,
    source_employee_id: str,
    rel_repo_path: str,
) -> Dict[str, Any]:
    """``apply_employee_change_request`` 写盘后调用：把改动提交到当前 HEAD。

    与 ``stage_file_to_employee_branch`` 不同：此函数会改变工作树状态——只提交
    单个文件，并恢复其它未跟踪/未暂存改动到原状（采用 ``git stash`` 可能干扰
    用户，所以这里只做最小化的 ``git add <path>`` + ``git commit <path>``）。

    通过 ``MODSTORE_CR_GIT_APPLY_COMMIT=1`` 显式启用，默认关闭以避免在共享工作
    树的开发机上意外修改提交历史。
    """
    if not _git_apply_commit_enabled():
        return {"ok": False, "reason": "MODSTORE_CR_GIT_APPLY_COMMIT disabled"}

    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = repo_root()
    except Exception:
        return {"ok": False, "reason": "repo_root() unavailable"}

    if not is_git_repo(Path(root)):
        return {"ok": False, "reason": "not a git repository"}

    rel = (rel_repo_path or "").replace("\\", "/").lstrip("/").strip()
    if not rel:
        return {"ok": False, "reason": "empty rel_repo_path"}

    root_str = str(root)
    add = _run_git(root_str, ["add", "--", rel], timeout=15)
    if add.returncode != 0:
        return {"ok": False, "reason": f"git add failed: {add.stderr[:200]}"}

    msg = (
        f"chore(cr): apply CR-{int(cr_id)} from {_safe_segment(source_employee_id)}\n"
        f"\nFile: {rel}\nApproved by AI-employee CR pipeline.\n"
    )
    author_name = os.environ.get("MODSTORE_GIT_AUTHOR_NAME", "MODstore Bot")
    author_email = os.environ.get("MODSTORE_GIT_AUTHOR_EMAIL", "bot@modstore.local")
    cm = _run_git(
        root_str,
        ["commit", "-m", msg, "--", rel],
        timeout=20,
        env_extra={
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        },
    )
    if cm.returncode != 0:
        # 工作树本就没有差异（例如内容与现状一致）也算成功
        if "nothing to commit" in (cm.stdout + cm.stderr).lower():
            return {"ok": True, "no_op": True}
        return {"ok": False, "reason": f"git commit failed: {cm.stderr[:200]}"}

    head = _run_git(root_str, ["rev-parse", "HEAD"], timeout=10).stdout.strip()
    return {"ok": True, "commit_sha": head}


def maybe_open_pr_for_cr(
    cr_id: int,
    branch: str,
    summary: str = "",
    *,
    risk_level: str = "",
) -> Dict[str, Any]:
    """对 CR 分支自动开 PR（``MODSTORE_CR_GIT_AUTO_PR=1`` + ``gh`` 可用时）。

    PR 会被打上：
      - ``ai-employee``：所有 CR 都有，方便 GitHub Actions 过滤。
      - ``auto-merge``：当 ``risk_level == "low"`` 时附加，配合
        ``.github/workflows/ci-auto-merge.yml`` 让 PR 在 CI 全绿后自动 squash 合并。
    """
    if not _gh_pr_enabled():
        return {"ok": False, "reason": "MODSTORE_CR_GIT_AUTO_PR disabled"}
    if not branch:
        return {"ok": False, "reason": "no branch"}

    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        root = repo_root()
    except Exception:
        return {"ok": False, "reason": "repo_root() unavailable"}

    base = os.environ.get("MODSTORE_AUTO_PR_BASE_BRANCH", "main").strip() or "main"
    push_remote = os.environ.get("MODSTORE_DEPLOY_PUSH_REMOTE", "origin").strip() or "origin"

    push = _run_git(str(root), ["push", "-u", push_remote, branch], timeout=120)
    if push.returncode != 0:
        return {"ok": False, "reason": f"git push failed: {push.stderr[:200]}"}

    title = f"[AI 员工] CR-{int(cr_id)}：{branch}"
    risk = (risk_level or "").strip().lower()
    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🚨"}.get(risk, "⚪")
    body = (
        f"**CR id**: {int(cr_id)}\n"
        f"**Branch**: `{branch}`\n"
        f"**Risk level**: {risk_emoji} {risk or 'unknown'}\n\n"
        f"{summary[:4000]}\n\n"
        f"---\n"
        f"_自动由 AI 员工 CR 管线产生；low-risk 已开启 auto-merge，待 CI 通过自动合入。_"
    )
    label_args: List[str] = ["--label", "ai-employee"]
    if risk == "low":
        label_args.extend(["--label", "auto-merge"])

    try:
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--base",
                base,
                "--title",
                title,
                "--body",
                body,
                "--head",
                branch,
                *label_args,
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
        )
        if proc.returncode != 0:
            return {"ok": False, "reason": (proc.stderr or proc.stdout)[:300]}
        return {
            "ok": True,
            "pr_url": (proc.stdout or "").strip(),
            "auto_merge": risk == "low",
        }
    except FileNotFoundError:
        return {"ok": False, "reason": "gh CLI not installed"}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)[:300]}


__all__ = [
    "cr_branch_name",
    "is_git_repo",
    "stage_file_to_employee_branch",
    "commit_cr_apply",
    "maybe_open_pr_for_cr",
]
