"""每日 07:00 编排：切分支 → 跑 daily-orchestrator 员工 → 本地提交 → 写入 OpsStagedChange。"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _slo_halt_blocks_auto_merge() -> bool:
    """When MODSTORE_RELEASE_SLO_HALT or MODSTORE_SLO_HALT_AUTO_MERGE=1, failed smoke blocks orchestrator."""
    raw_release = (os.environ.get("MODSTORE_RELEASE_SLO_HALT", "0") or "").strip().lower()
    raw_legacy = (os.environ.get("MODSTORE_SLO_HALT_AUTO_MERGE", "0") or "").strip().lower()
    if raw_release not in ("1", "true", "yes", "on") and raw_legacy not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return False
    try:
        from modstore_server.post_deploy_smoke import run_post_deploy_smoke

        smoke = run_post_deploy_smoke()
        if smoke.get("skipped"):
            return False
        return not bool(smoke.get("ok"))
    except Exception:
        logger.exception("slo halt smoke check failed")
        return True


def _run_git(root: str, args: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def run_daily_orchestrator_job(*, bypass_digest_gate: bool = False) -> Dict[str, Any]:
    raw = os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_ENABLED", "1").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return {"ok": True, "skipped": True}

    from modstore_server.automation_primary import skip_daily_automation_result

    delegated = skip_daily_automation_result(job="daily_orchestrator")
    if delegated and not bypass_digest_gate:
        return delegated

    if _slo_halt_blocks_auto_merge():
        logger.warning(
            "daily orchestrator halted: post_deploy_smoke failed (MODSTORE_SLO_HALT_AUTO_MERGE)"
        )
        return {"ok": True, "skipped": True, "reason": "slo_halt_auto_merge"}

    digest_mode = (
        (os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_DIGEST_MODE", "shadow") or "shadow")
        .strip()
        .lower()
    )
    if not bypass_digest_gate and digest_mode in ("primary", "digest"):
        logger.info(
            "daily orchestrator skipped at 07:00 — delegated to release_train orchestrator (digest_mode=%s)",
            digest_mode,
        )
        return {
            "ok": True,
            "skipped": True,
            "reason": "delegated_to_release_train_orchestrator",
            "digest_mode": digest_mode,
        }

    from modstore_server.employee_orchestrator import plan_and_dispatch
    from modstore_server.integrations.ops_action_handlers import dispatch_ops_handler, repo_root
    from modstore_server.models import OpsStagedChange, get_session_factory

    root = str(repo_root())
    # 可靠性守卫：repo_root 必须是 git 工作树，否则后续 checkout/commit 会中途报错。
    # 本地 dev（MODSTORE_REPO_ROOT 指向非 git 的 XCMAX 根）→ 干净跳过，不污染日更结果。
    try:
        from pathlib import Path as _Path

        from modstore_server.cr_git_pipeline import is_git_repo

        if not is_git_repo(_Path(root)):
            logger.warning(
                "daily orchestrator skipped: repo_root 非 git 工作树 (%s) — 跳过 git 编排（本地 dev 正常；生产应指向 modstore-git）",
                root,
            )
            return {"ok": True, "skipped": True, "reason": "repo_root_not_git", "root": root}
    except Exception:
        logger.exception("daily orchestrator: is_git_repo 守卫异常，继续按原逻辑")
    prefix = os.environ.get("MODSTORE_DEPLOY_PUSH_BRANCH_PREFIX", "auto/daily-").strip()
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    # 同日幂等：每日汇总分支名固定（无随机后缀），同一天重跑复用同一分支 + 同一 PR，根治分支爆炸。
    branch = f"{prefix}{day}"

    # base 分支自动探测：优先显式 env → origin/HEAD 默认分支 → main → master → 当前 HEAD。
    # 避免硬编码 main 在默认分支不同时 checkout 失败（BRANCHING.md 规范）。
    base_ref = os.environ.get("MODSTORE_AUTO_PR_BASE_BRANCH", "").strip()
    if not base_ref:
        head_ref = _run_git(
            root, ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"]
        ).stdout.strip()
        if head_ref:
            base_ref = head_ref.rsplit("/", 1)[-1]  # origin/main → main
    if not base_ref or _run_git(root, ["rev-parse", "--verify", base_ref]).returncode != 0:
        if _run_git(root, ["rev-parse", "--verify", "main"]).returncode == 0:
            base_ref = "main"
        elif _run_git(root, ["rev-parse", "--verify", "master"]).returncode == 0:
            base_ref = "master"
        else:
            base_ref = "HEAD"

    chk = _run_git(root, ["checkout", base_ref], timeout=90)
    if chk.returncode != 0:
        logger.warning("daily orchestrator: checkout %s failed: %s", base_ref, chk.stderr)
        return {"ok": False, "error": "checkout base failed", "stderr": chk.stderr}

    _run_git(root, ["fetch", "origin"], timeout=240)  # best-effort

    base_commit = _run_git(root, ["rev-parse", "HEAD"]).stdout.strip()
    if not base_commit:
        return {"ok": False, "error": "no base commit"}

    # 创建或复用：同日已存在则切回该分支（幂等），否则新建。
    if _run_git(root, ["rev-parse", "--verify", branch]).returncode == 0:
        co = _run_git(root, ["checkout", branch], timeout=90)
        if co.returncode != 0:
            return {
                "ok": False,
                "error": "checkout existing daily branch failed",
                "stderr": co.stderr,
            }
        logger.info("daily orchestrator: 复用今日分支 %s（同日幂等）", branch)
    else:
        br = dispatch_ops_handler(
            "shell_exec",
            {"shell_exec": {"command_id": "git-create-branch", "args": {"branch": branch}}},
            {},
            "daily orchestrator job",
            "daily-orchestrator",
            0,
        )
        if not br.get("ok"):
            return {"ok": False, "error": "git-create-branch failed", "detail": br}

    try:
        from modstore_server.services.llm import resolve_platform_bench_llm

        prov, mdl = resolve_platform_bench_llm()
        bench = (prov, mdl) if prov and mdl else None
        if bench is None:
            logger.warning(
                "daily orchestrator: resolve_platform_bench_llm 为空，将依赖员工包内显式模型或 cognition auto（平台密钥）"
            )
        out = plan_and_dispatch(
            "根据仓库状态：阅读 MODstore_deploy 测试与质量问题提示，做最小安全修复；"
            "禁止修改 MODstore_deploy/modstore_server/models.py、migrations、*.db、catalog_data、library。",
            {"project_root": root},
            target_employee_id="daily-orchestrator",
            created_by_user_id=0,
            include_dependencies=True,
            allow_high_risk_real_run=True,
            bench_llm_override=bench,
        )
        if not out.get("ok"):
            logger.warning("daily orchestrator duty graph: %s", out.get("error"))
    except Exception:
        logger.exception("daily-orchestrator plan_and_dispatch failed")

    st = _run_git(root, ["status", "--porcelain"])
    if (st.stdout or "").strip():
        ad = dispatch_ops_handler(
            "shell_exec",
            {"shell_exec": {"command_id": "git-add-all", "args": {}}},
            {},
            "daily orchestrator job",
            "daily-orchestrator",
            0,
        )
        if not ad.get("ok"):
            return {"ok": False, "error": "git-add-all failed", "detail": ad}
        cm = dispatch_ops_handler(
            "shell_exec",
            {
                "shell_exec": {
                    "command_id": "git-commit-msg",
                    "args": {"message": f"chore(daily): orchestrator {day}"},
                }
            },
            {},
            "daily orchestrator job",
            "daily-orchestrator",
            0,
        )
        if not cm.get("ok"):
            return {"ok": False, "error": "git-commit-msg failed", "detail": cm}

    head = _run_git(root, ["rev-parse", "HEAD"]).stdout.strip()
    if head == base_commit:
        return {"ok": True, "message": "no commits to stage", "branch": branch}

    names = _run_git(root, ["diff", "--name-only", f"{base_commit}..{head}"])
    file_lines = [x.strip() for x in (names.stdout or "").splitlines() if x.strip()]
    files_n = len(file_lines)

    stat = _run_git(root, ["diff", "--stat", f"{base_commit}..{head}"])
    diff_summary = (stat.stdout or "")[:8000]

    sf = get_session_factory()
    staged_id: int | None = None
    with sf() as session:
        row = OpsStagedChange(
            branch=branch,
            base_commit=base_commit,
            head_commit=head,
            files_changed_count=files_n,
            diff_summary=diff_summary,
            created_by_employee_id="daily-orchestrator",
            status="pending",
        )
        session.add(row)
        session.flush()
        staged_id = int(row.id)
        session.commit()

    result = {"ok": True, "branch": branch, "staged_id": staged_id, "files": files_n}

    if staged_id:
        try:
            from modstore_server.post_deploy_smoke import slo_halt_blocks_auto_merge

            if slo_halt_blocks_auto_merge():
                logger.warning(
                    "daily orchestrator: SLO halt — skipping auto-deploy staged_id=%s (last post_deploy_smoke failed)",
                    staged_id,
                )
                result["auto_deploy"] = {
                    "ok": False,
                    "skipped": True,
                    "reason": "slo_halt_auto_merge",
                }
            else:
                from modstore_server.ops_staged_auto_approve import try_auto_deploy_staged_change

                auto = try_auto_deploy_staged_change(int(staged_id))
                if auto is not None:
                    result["auto_deploy"] = auto
        except Exception:
            logger.exception("daily orchestrator auto-deploy skipped staged_id=%s", staged_id)

    # 自动创建 GitHub PR（若启用）
    auto_pr = os.environ.get("MODSTORE_AUTO_PR_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if auto_pr:
        try:
            pr_result = _maybe_create_pr(branch, diff_summary, files_n, staged_id)
            result["pr"] = pr_result
        except Exception as _pr_exc:
            result["pr_error"] = str(_pr_exc)

    # 分支自动清理（best-effort，防分支爆炸）：删已合并/超期的 cr/* 与 auto/daily-*。
    try:
        from modstore_server.branch_janitor import prune_stale_branches

        result["branch_cleanup"] = prune_stale_branches(root, base=base_ref)
    except Exception:
        logger.exception("daily orchestrator: branch cleanup skipped")

    return result


def _maybe_create_pr(branch: str, diff_summary: str, files_n: int, staged_id: int) -> dict:
    """尝试通过 ``gh pr create`` 创建 GitHub PR。"""
    import subprocess
    import sys

    from modstore_server.integrations.ops_action_handlers import repo_root

    root = repo_root()
    base = os.environ.get("MODSTORE_AUTO_PR_BASE_BRANCH", "main").strip() or "main"

    # 幂等：同分支若已有开启的 PR，直接复用，不重复创建（每日单 PR 模型）。
    existing = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "url",
            "--jq",
            ".[0].url",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    existing_url = (existing.stdout or "").strip()
    if existing.returncode == 0 and existing_url:
        return {"ok": True, "pr_url": existing_url, "reused": True}

    title = f"chore(auto): daily-orchestrator [{branch}]"
    body = (
        f"**自动编排 PR**\n\n"
        f"- 分支: `{branch}`\n"
        f"- 变更文件: {files_n} 个\n"
        f"- staged_change_id: {staged_id}\n\n"
        f"**diff 摘要**\n```\n{diff_summary[:3000]}\n```"
    )

    proc = subprocess.run(
        ["gh", "pr", "create", "--base", base, "--title", title, "--body", body],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr[:500]}
    pr_url = proc.stdout.strip()
    return {"ok": True, "pr_url": pr_url}


def cron_trigger_for_orchestrator():
    """默认每天 07:00（北京时间），早于摘要邮件。"""
    try:
        from zoneinfo import ZoneInfo

        from apscheduler.triggers.cron import CronTrigger

        tz = ZoneInfo(os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_TZ", "Asia/Shanghai").strip())
        hour = int(os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_HOUR", "7"))
        minute = int(os.environ.get("MODSTORE_DAILY_ORCHESTRATOR_MINUTE", "0"))
        return CronTrigger(hour=hour, minute=minute, timezone=tz)
    except Exception:
        from apscheduler.triggers.cron import CronTrigger

        return CronTrigger(hour=7, minute=0)
