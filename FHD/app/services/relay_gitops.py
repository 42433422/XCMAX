"""手机端 git 操作（合并/diff/丢弃）——供 relay 任务 kind=git.* 调用。

设计：开发任务每条消息一条分支（基于工程根当前分支 HEAD），手机底部功能键可对该分支：
  - git.diff   ：看分支相对基线分支的改动（只读，合并前 review）
  - git.merge  ：直接合并回基线分支——在独立 detached worktree 里合，**重跑验证**，
                 绿了才 push 基线分支；冲突/验证失败则中止，绝不动基线。
  - git.discard：删除该分支（远端 + 本地 ref）。

基线分支默认 = 工程根当前 checkout 分支（开发任务正是从它 HEAD 切的，合并即最小 diff）；
可用 XCMAX_GIT_MERGE_BASE 覆盖。
"""

from __future__ import annotations

import logging
import os
import py_compile
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GIT_OP_KINDS = ("git.merge", "git.diff", "git.discard")


def _git(cwd: str, *args: str, timeout: float = 120.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout
    )


def _repo_root() -> str:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == "FHD":
            return str(parent.parent)
    return str(here.parents[3])


def _merge_base_branch(repo: str) -> str:
    env = str(os.environ.get("XCMAX_GIT_MERGE_BASE") or "").strip()
    if env:
        return env
    r = _git(repo, "symbolic-ref", "--short", "HEAD", timeout=15)
    return r.stdout.strip() or "main"


def _branch_from_payload(payload: dict[str, Any]) -> str:
    branch = str((payload or {}).get("branch") or "").strip()
    # 容错：手机可能传完整 "origin/xxx" 或带前缀
    if branch.startswith("origin/"):
        branch = branch[len("origin/") :]
    return branch


def _verify_merged(wt: str, base: str) -> tuple[bool, str]:
    """合并后验证：优先 XCMAX_CLAUDE_VERIFY_CMD；否则对该任务改动的 .py 做语法编译。"""
    custom = str(os.environ.get("XCMAX_CLAUDE_VERIFY_CMD") or "").strip()
    if custom:
        try:
            r = subprocess.run(
                custom,
                shell=True,
                cwd=wt,
                capture_output=True,
                text=True,
                timeout=1800,  # nosec B602 – operator-supplied env var, may use shell syntax
            )
            return (
                r.returncode == 0,
                "自定义验证通过" if r.returncode == 0 else (r.stderr or r.stdout)[:800],
            )
        except Exception as e:  # noqa: BLE001
            return False, f"验证命令异常：{str(e)[:300]}"
    # worktree 基于本地 base，故 base..HEAD = 本任务自身的改动（不含本地领先 origin 的历史）。
    diff = _git(wt, "diff", "--name-only", f"{base}..HEAD", timeout=30).stdout
    py = [ln.strip() for ln in diff.splitlines() if ln.strip().endswith(".py")]
    errs: list[str] = []
    for f in py:
        p = Path(wt) / f
        if not p.exists():
            continue
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as e:
            errs.append(str(e)[:300])
    if errs:
        return False, "Python 语法错误：\n" + "\n".join(errs)
    return True, (f"已对 {len(py)} 个 .py 通过语法编译" if py else "无 .py 改动需深度验证")


def git_diff(payload: dict[str, Any], repo: str | None = None) -> dict[str, Any]:
    repo = repo or _repo_root()
    branch = _branch_from_payload(payload)
    if not branch:
        return {"ok": False, "_relay_status": "failed", "reply": "缺少分支名"}
    base = _merge_base_branch(repo)
    _git(repo, "fetch", "origin", branch, timeout=120)
    # 只显示本任务自身的改动：以 branch 与 base 的 merge-base 为对比起点，
    # 排除"本地 base 领先 origin"的历史提交（否则 diff 会混入一堆无关文件）。
    ref = f"origin/{branch}"
    mb = _git(repo, "merge-base", ref, base, timeout=30).stdout.strip()
    if not mb:
        ref = branch  # origin 未抓到 → 退回本地分支
        mb = _git(repo, "merge-base", ref, base, timeout=30).stdout.strip()
    start = mb or base
    r = _git(repo, "diff", f"{start}..{ref}", timeout=60)
    stat = _git(repo, "diff", "--stat", f"{start}..{ref}", timeout=60).stdout
    text = (stat.strip() + "\n\n" + r.stdout).strip()
    if not text:
        return {"ok": True, "reply": f"{branch} 相对 {base} 没有差异。"}
    clipped = text[:6000] + ("\n…(已截断)" if len(text) > 6000 else "")
    return {"ok": True, "reply": f"分支 {branch} 相对 {base} 的改动：\n```diff\n{clipped}\n```"}


def git_discard(payload: dict[str, Any], repo: str | None = None) -> dict[str, Any]:
    repo = repo or _repo_root()
    branch = _branch_from_payload(payload)
    if not branch:
        return {"ok": False, "_relay_status": "failed", "reply": "缺少分支名"}
    p = _git(repo, "push", "origin", "--delete", branch, timeout=120)
    _git(repo, "branch", "-D", branch, timeout=30)
    if p.returncode != 0 and "remote ref does not exist" not in (p.stderr + p.stdout):
        return {
            "ok": False,
            "_relay_status": "failed",
            "reply": f"丢弃失败：{(p.stderr or p.stdout)[:200]}",
        }
    return {"ok": True, "reply": f"已丢弃分支 {branch}（远端 + 本地）。"}


def git_merge(payload: dict[str, Any], repo: str | None = None) -> dict[str, Any]:
    repo = repo or _repo_root()
    branch = _branch_from_payload(payload)
    if not branch:
        return {"ok": False, "_relay_status": "failed", "reply": "缺少分支名"}
    base = _merge_base_branch(repo)
    _git(repo, "fetch", "origin", timeout=180)
    uniq = f"{os.getpid()}-{int.from_bytes(os.urandom(3), 'big'):x}"
    wt = str(Path(tempfile.gettempdir()) / f"xcagi-merge-{uniq}")
    try:
        # 基于本地 base（开发分支的切出点）建 worktree：合并即只带该任务的改动，
        # push 时把"本地 base + 任务"推到 origin/base（origin 落后则快进，不会冲突）。
        a = _git(repo, "worktree", "add", "--detach", wt, base, timeout=180)
        if a.returncode != 0:
            return {
                "ok": False,
                "_relay_status": "failed",
                "reply": f"准备合并环境失败：{(a.stderr or a.stdout)[:200]}",
            }
        m = _git(
            wt,
            "merge",
            "--no-ff",
            f"origin/{branch}",
            "-m",
            f"merge {branch} into {base} (手机超级员工)",
            timeout=120,
        )
        if m.returncode != 0:
            _git(wt, "merge", "--abort", timeout=30)
            return {
                "ok": False,
                "_relay_status": "failed",
                "reply": f"合并有冲突，已中止，未改动 {base}：\n{(m.stdout or m.stderr)[:400]}",
            }
        ok, vmsg = _verify_merged(wt, base)
        if not ok:
            return {
                "ok": False,
                "_relay_status": "failed",
                "reply": f"合并后验证未通过，未推送 {base}：\n{vmsg[:400]}",
            }
        p = _git(wt, "push", "origin", f"HEAD:{base}", timeout=240)
        if p.returncode != 0:
            return {
                "ok": False,
                "_relay_status": "failed",
                "reply": f"验证通过但推送 {base} 失败：{(p.stderr or p.stdout)[:300]}",
            }
        return {
            "ok": True,
            "reply": (
                f"✅ 已合并 {branch} → origin/{base} 并推送（验证：{vmsg[:120]}）。\n"
                "本机 checkout 如需同步请 git pull。"
            ),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("git_merge 异常", exc_info=True)
        return {"ok": False, "_relay_status": "failed", "reply": f"合并异常：{str(e)[:300]}"}
    finally:
        _git(repo, "worktree", "remove", "--force", wt, timeout=60)


def handle_git_op(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "git.diff":
        return git_diff(payload)
    if kind == "git.discard":
        return git_discard(payload)
    if kind == "git.merge":
        return git_merge(payload)
    return {"ok": False, "_relay_status": "failed", "reply": f"未知 git 操作：{kind}"}
