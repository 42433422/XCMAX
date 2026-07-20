"""读取 capability_proposal.jsonl → 创建 GitHub issue → 打 ai-implement 标签。

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
import sys
import urllib.request
from datetime import datetime, timezone
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gh_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _gh_post(url: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
    import urllib.error

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_gh_headers(token), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"_error": exc.code, "_body": exc.read().decode("utf-8", errors="replace")}


def _build_issue_body(proposal: dict[str, Any]) -> str:
    raw = proposal.get("raw_input") or ""
    reason = proposal.get("reason") or "intent_unknown"
    ts = proposal.get("ts") or ""
    ctx = proposal.get("context") or {}
    intent_ctx = ctx.get("intent_result") or {}

    return (
        "## 来源：能力提案 (capability_proposal)\n\n"
        f"- **未命中时间**: `{ts}`\n"
        f"- **未命中原因**: `{reason}`\n"
        f"- **来源**: `{proposal.get('source') or '-'}`\n\n"
        "## 用户原始输入\n\n```\n"
        f"{raw}\n```\n\n"
        "## 意图识别上下文\n\n```json\n"
        f"{json.dumps(intent_ctx, ensure_ascii=False, indent=2)}\n```\n\n"
        "## 进化状态闭环\n\n"
        "1. 本 issue 由 `capability-proposal-to-issue.yml` workflow 自动创建\n"
        "2. 已打 `ai-implement` 标签\n"
        "3. 命中 `config/auto-implement-allowlist.yaml` 域标签，或 owner 评论「确认」后，"
        "`ai-issue-implement.yml` workflow 将自动实现\n"
        "4. 实现的 PR 标 `needs-human` 待人工 review\n\n"
        "## 实现建议\n\n"
        "- 评估未命中输入是否为新业务意图，若是 → 扩展 `intent_confirmation_service.INTENT_REQUIRED_SLOTS`\n"
        "- 若是已有意图的槽位提取缺陷 → 改进 `intent_service.recognize_intents`\n"
        "- 若是闲聊/无关 → 增加 `intent_golden_set.json` 反例\n"
    )


def _build_issue_title(proposal: dict[str, Any]) -> str:
    raw = str(proposal.get("raw_input") or "").strip()
    if not raw:
        raw = "(empty input)"
    if len(raw) > 60:
        raw = raw[:60] + "..."
    return f"[capability-proposal] 未命中意图: {raw}"


def run(args: argparse.Namespace) -> int:
    since_unix = 0.0
    # 简单策略：每次跑都处理全部 pending（去重已由 recorder 保证）
    pending = list_pending_proposals(since_unix=since_unix)
    if not pending:
        logger.info("no pending capability_proposal")
        return 0

    limited = pending[: args.max_issues]
    logger.info("pending=%d processing=%d", len(pending), len(limited))

    if args.dry_run:
        for p in limited:
            logger.info(
                "[dry-run] would create issue: title=%s",
                _build_issue_title(p),
            )
        return 0

    if not args.token:
        logger.error("--token required for apply mode")
        return 1

    created_keys: list[str] = []
    created_count = 0
    for proposal in limited:
        body = _build_issue_body(proposal)
        title = _build_issue_title(proposal)
        resp = _gh_post(
            f"https://api.github.com/repos/{args.repo}/issues",
            args.token,
            {
                "title": title,
                "body": body,
                "labels": ["ai-implement", "capability-proposal", "auto-generated"],
            },
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
        created_keys.append(str(proposal.get("dedup_key") or ""))
        created_count += 1

    if created_keys:
        mark_proposals_processed(created_keys)
    logger.info("done: created=%d/%d", created_count, len(limited))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="capability_proposal → GitHub issue")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--max-issues", type=int, default=5, help="单次最多创建 issue 数")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(run(args))


if __name__ == "__main__":
    main()
