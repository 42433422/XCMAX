# mypy: disable-error-code="no-any-return"
"""读取 capability_proposal.jsonl → 创建受控 GitHub 治理 issue。

CI 用法（在 capability-proposal-to-issue.yml workflow 中）:
    python scripts/dev/capability_proposal_to_issue.py \\
        --repo "$GITHUB_REPOSITORY" \\
        --token "$GITHUB_TOKEN" \\
        --max-issues 5 \\
        --apply

本地 dry-run:
    python scripts/dev/capability_proposal_to_issue.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 通过 sys.path 注入让脚本能 import app.services.capability_proposal_recorder
_FHD_ROOT = Path(__file__).resolve().parents[2]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

from app.services.capability_proposal_recorder import (  # noqa: E402  pylint: disable=wrong-import-position
    list_pending_proposals,
    mark_proposals_processed,
)
from app.services.work_order_ssot import (
    derive_wo_id,  # noqa: E402  pylint: disable=wrong-import-position
)
from app.utils.operational_errors import (  # noqa: E402  pylint: disable=wrong-import-position
    BOUNDARY_ERRORS,
)


def _derive_wo_id(source: str, dedup_key: str) -> str:
    """由提案来源 + 去重键派生唯一工单 ID（与 work_order_ssot 同一口径）。"""
    if not str(dedup_key or "").strip():
        return ""
    return derive_wo_id(str(source or "").strip() or "unknown", str(dedup_key).strip())


def _build_acceptance_criteria(
    reason: str, intent_ctx: dict[str, Any], skill_ctx: dict[str, Any]
) -> str:
    """从提案上下文模板化生成可验证验收标准（无 LLM，可机器核对）。"""
    criteria = [
        "同类用户输入不再落入 capability_proposal 未命中队列（意图基准回归通过）",
        "新增能力按预期完成意图识别与槽位校验，全流程本地测试通过",
        "既有意图识别无回归（intent benchmark 棘轮不下降）",
        "发布后 macOS 与 Windows 客户机安装回执均为 installed，无未解决 failed/rolled_back",
    ]
    candidate_slots = skill_ctx.get("candidate_slots") or []
    if candidate_slots:
        criteria.insert(1, f"必需槽位 {', '.join(candidate_slots)} 缺失时正确追问")
    if not intent_ctx.get("classifier_fields_present"):
        criteria.append("意图分类器对该类输入产出稳定 primary_intent")
    _ = reason
    return "\n".join(f"- [ ] {item}" for item in criteria) + "\n\n"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_post(url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_gh_headers(token), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")}


def _gh_get(url: str, token: str) -> Any:
    req = urllib.request.Request(url, headers=_gh_headers(token), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")}


def _gh_api_find_existing(repo: str, title: str, token: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"q": f'repo:{repo} is:issue in:title "{title}"'})
    response = _gh_get(f"https://api.github.com/search/issues?{query}", token)
    if isinstance(response, dict) and response.get("_error"):
        return response
    items = response.get("items") if isinstance(response, dict) else []
    for item in items or []:
        if isinstance(item, dict) and item.get("title") == title:
            return {"html_url": item.get("html_url") or ""}
    return {}


def _gh_cli_create(repo: str, title: str, body: str, labels: list[str]) -> dict[str, Any]:
    """使用本机已认证 gh 创建 issue，供本地调度中继使用。"""
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    for label in labels:
        cmd.extend(["--label", label])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"_error": "gh_cli_failed", "_body": str(exc)}
    if result.returncode != 0:
        return {"_error": result.returncode, "_body": result.stderr}
    return {"html_url": result.stdout.strip()}


def _gh_cli_find_existing(repo: str, title: str) -> dict[str, Any]:
    cmd = [
        "gh",
        "issue",
        "list",
        "--repo",
        repo,
        "--state",
        "all",
        "--search",
        f'"{title}" in:title',
        "--json",
        "title,url",
        "--limit",
        "10",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"_error": "gh_cli_failed", "_body": str(exc)}
    if result.returncode != 0:
        return {"_error": result.returncode, "_body": result.stderr}
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return {"_error": "gh_cli_invalid_json", "_body": result.stdout[:300]}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("title") == title:
            return {"html_url": row.get("url") or ""}
    return {}


def _is_actionable_skill_proposal(proposal: dict[str, Any]) -> bool:
    """仅接受新技能路由器产出的结构化提案，拒绝历史 ``intent_unknown`` 噪音。"""
    context = proposal.get("context")
    skill = context.get("skill_proposal") if isinstance(context, dict) else None
    return bool(
        proposal.get("reason") == "skill_proposal"
        and isinstance(skill, dict)
        and str(skill.get("proposed_skill_id") or "").strip()
        and str(skill.get("status") or "").strip() == "proposed"
    )


def _build_issue_body(proposal: dict[str, Any]) -> str:
    reason = proposal.get("reason") or "intent_unknown"
    ts = proposal.get("ts") or ""
    ctx = proposal.get("context") or {}
    intent_ctx = ctx.get("intent_result") or {}
    skill_ctx = ctx.get("skill_proposal") or {}

    def safe_name(value: Any) -> str:
        text = str(value or "")
        return text if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", text) else ""

    slot_names = [
        name
        for name in (safe_name(value) for value in (intent_ctx.get("slot_names") or []))
        if name
    ]
    candidate_slots = [
        name
        for name in (safe_name(value) for value in (skill_ctx.get("candidate_slots") or []))
        if name
    ]
    safe_intent_ctx = {
        "classifier_fields_present": [
            key
            for key in ("primary_intent", "tool_key", "deepseek_intent")
            if intent_ctx.get(key) is not None
        ],
        "slot_names": slot_names,
    }
    rationale = str(skill_ctx.get("rationale") or "")
    safe_skill_ctx = {
        "candidate_slots": candidate_slots,
        "rationale": (
            rationale if rationale == "classifier_miss_or_low_confidence" else "unspecified"
        ),
        "status": "proposed",
    }
    dedup_key = str(proposal.get("dedup_key") or "")
    source = str(proposal.get("source") or "intent_confirmation_service")
    wo_id = _derive_wo_id(source, dedup_key)

    return (
        "## 来源：能力提案 (capability_proposal)\n\n"
        f"- **工单 ID (Work Order SSOT)**: `{wo_id}`\n"
        f"- **未命中时间**: `{ts}`\n"
        f"- **未命中原因**: `{reason}`\n"
        f"- **来源**: `{proposal.get('source') or '-'}`\n\n"
        f"- **本地去重引用**: `{dedup_key}`\n\n"
        "## 结构化上下文（已移除用户原文和槽位值）\n\n```json\n"
        f"{json.dumps({'intent': safe_intent_ctx, 'skill': safe_skill_ctx}, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
        "## 验收标准（进入 AI 开发前必须可验证）\n\n"
        f"{_build_acceptance_criteria(reason, safe_intent_ctx, safe_skill_ctx)}\n"
        "## 治理门禁\n\n"
        "1. 本 issue 只登记能力缺口，不直接触发任意代码生成。\n"
        "2. 用户原文与槽位值留在本地，不写入 GitHub。\n"
        "3. 先确认能力边界、风险、验收与回滚；满足受控实现策略后再进入实现队列。\n"
        "4. 实现、审核、合并、上架和部署收据必须分别留证。\n"
        "5. 仓库所有者确认后，单独评论 `确认实现` 或 `/approve-implementation`；"
        "系统将显式派发实现工作流，批准本身不能直接合并代码。\n"
        "6. CI 通过 ≠ 客户能用：发布后须 macOS 与 Windows 客户机安装回执双平台健康，"
        "方可验收关闭；任一平台失败自动重开本 issue，不另起新单。\n"
    )


def _build_issue_title(proposal: dict[str, Any]) -> str:
    dedup_key = str(proposal.get("dedup_key") or "unknown")[:12]
    return f"[capability-proposal] 新能力候选 {dedup_key}"


def _parse_issue_number(issue_url: str) -> int:
    """从 issue URL 解析编号（gh cli 创建只回 URL）。"""
    match = re.search(r"/issues/(\d+)", str(issue_url or ""))
    return int(match.group(1)) if match else 0


def _link_work_order(proposal: dict[str, Any], issue_url: str, issue_number: int = 0) -> None:
    """主线接线：issue 创建/调和后把工单推进到 routed（候选期终点）。

    工单写入失败不阻塞 issue 流程 —— issue 本身是对外观测载体。
    """
    key = str(proposal.get("dedup_key") or "").strip()
    if not key:
        return
    source = str(proposal.get("source") or "intent_confirmation_service")
    number = int(issue_number or 0) or _parse_issue_number(issue_url)
    try:
        from app.services.work_order_ssot import link_issue, upsert_candidate

        upsert_candidate(
            source=source,
            dedup_key=key,
            reason=str(proposal.get("reason") or ""),
        )
        link_issue(
            derive_wo_id(source, key),
            issue_number=number,
            issue_url=str(issue_url or ""),
        )
    except BOUNDARY_ERRORS:  # noqa: BLE001 - CI/中继边界兜底，不影响 issue 流程
        logger.debug("work_order link skipped", exc_info=True)


def _mark_verified(
    keys: list[str],
    *,
    disposition: str,
    issue_urls: dict[str, str] | None = None,
) -> bool:
    if not keys:
        return True
    mark_proposals_processed(keys, disposition=disposition, issue_urls=issue_urls)
    pending_keys = {str(row.get("dedup_key") or "") for row in list_pending_proposals()}
    return not (set(keys) & pending_keys)


def run(args: argparse.Namespace) -> int:
    pending = list_pending_proposals()
    if not pending:
        logger.info("no pending capability_proposal")
        return 0

    ignored = [row for row in pending if not _is_actionable_skill_proposal(row)]
    actionable = [row for row in pending if _is_actionable_skill_proposal(row)]
    limited = actionable[: args.max_issues]
    logger.info("pending=%d processing=%d", len(pending), len(limited))

    if args.dry_run:
        logger.info("[dry-run] would ignore non-actionable=%d", len(ignored))
        for p in limited:
            logger.info(
                "[dry-run] would create issue: title=%s",
                _build_issue_title(p),
            )
        return 0

    if not args.repo:
        logger.error("--repo required for apply mode")
        return 1
    if not args.token and not args.gh_cli:
        logger.error("--token or --gh-cli required for apply mode")
        return 1

    ignored_keys = [str(row.get("dedup_key") or "") for row in ignored]
    if not _mark_verified(ignored_keys, disposition="ignored_non_skill_proposal"):
        logger.error("failed to persist ignored proposal receipts")
        return 1

    created_keys: list[str] = []
    reconciled_keys: list[str] = []
    issue_urls: dict[str, str] = {}
    created_count = 0
    labels = ["capability-proposal", "auto-generated", "needs-human"]
    for proposal in limited:
        body = _build_issue_body(proposal)
        title = _build_issue_title(proposal)
        existing = (
            _gh_cli_find_existing(args.repo, title)
            if args.gh_cli
            else _gh_api_find_existing(args.repo, title, args.token)
        )
        if existing.get("_error"):
            logger.error("issue dedupe lookup failed: %s", existing.get("_error"))
            return 1
        if existing.get("html_url"):
            key = str(proposal.get("dedup_key") or "")
            reconciled_keys.append(key)
            issue_urls[key] = str(existing["html_url"])
            logger.info("existing issue reconciled: %s", existing["html_url"])
            continue
        if args.gh_cli:
            resp = _gh_cli_create(args.repo, title, body, labels)
        else:
            resp = _gh_post(
                f"https://api.github.com/repos/{args.repo}/issues",
                args.token,
                {"title": title, "body": body, "labels": labels},
            )
        if resp.get("_error"):
            logger.error(
                "create issue failed: status=%s body=%s",
                resp.get("_error"),
                (resp.get("_body") or "")[:300],
            )
            continue
        issue_url = resp.get("html_url") or ""
        issue_number = resp.get("number") or 0
        logger.info("issue created: #%s %s", issue_number, issue_url)
        key = str(proposal.get("dedup_key") or "")
        created_keys.append(key)
        issue_urls[key] = str(issue_url)
        _link_work_order(proposal, str(issue_url), int(issue_number or 0))
        created_count += 1

    if created_keys:
        if not _mark_verified(
            created_keys,
            disposition="issue_created",
            issue_urls=issue_urls,
        ):
            logger.error("issue created but processed receipt was not durable")
            return 1
    if reconciled_keys and not _mark_verified(
        reconciled_keys,
        disposition="issue_reconciled",
        issue_urls=issue_urls,
    ):
        logger.error("existing issue found but reconciliation receipt was not durable")
        return 1
    logger.info("done: created=%d/%d", created_count, len(limited))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="capability_proposal → GitHub issue")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--max-issues", type=int, default=5, help="单次最多创建 issue 数")
    parser.add_argument("--gh-cli", action="store_true", help="使用本机已认证 gh")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(run(args))


if __name__ == "__main__":
    main()
