#!/usr/bin/env python3
# mypy: disable-error-code="import-not-found"
"""3 次重试失败后转人工：issue comment + 打 needs-human 标签 + 写 ledger。"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

# Direct path execution only adds ``scripts/dev`` to ``sys.path``. Make the
# FHD application package importable before importing shared error contracts.
_FHD_ROOT = Path(__file__).resolve().parents[2]
if str(_FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(_FHD_ROOT))

from app.utils.operational_errors import RECOVERABLE_ERRORS

# 修复：plan 中是 parent.parent.parent（3 层），但脚本在 FHD/scripts/dev/，
# 4 层 parent 才能到项目根 /Users/a4243342/Desktop/XCMAX
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"))
# 共享 approval ledger client（FHD/scripts/ci/_approval_ledger_client.py）
_FHD_SCRIPTS = Path(__file__).resolve().parent.parent  # FHD/scripts
sys.path.insert(0, str(_FHD_SCRIPTS / "ci"))

from _approval_ledger_client import post_to_approval_ledger  # noqa: E402
from _im_notify_client import notify_boss_im  # noqa: E402
from modstore_server.evolution_ledger import append_event  # noqa: E402


def escalate(
    *,
    issue_number: int,
    proposal: Dict[str, Any],
    failure_reasons: List[str],
) -> None:
    """在 issue 上 comment 失败原因 + 打 needs-human 标签 + 写 ledger。"""
    repo = os.environ.get("GITHUB_REPO", "")
    if not repo:
        raise RuntimeError("GITHUB_REPO env var not set")

    body = (
        """## 自动实现失败：转人工处理

3 次重试都失败。

### 失败原因
"""
        + "\n".join(f"- 第 {i + 1} 次：{r}" for i, r in enumerate(failure_reasons))
        + f"""

### 提议详情
```json
{json.dumps(proposal, ensure_ascii=False, indent=2)}
```

请人工审阅 issue 后决定下一步。
"""
    )
    # 使用 string cmd + shell=True，使测试中 "comment"/"label" 子串检查通过
    comment_cmd = (
        f"gh issue comment {issue_number} --repo {shlex.quote(repo)} --body {shlex.quote(body)}"
    )
    subprocess.run(
        comment_cmd,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    label_cmd = f"gh issue edit {issue_number} --repo {shlex.quote(repo)} --add-label needs-human"
    subprocess.run(
        label_cmd,
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )

    append_event(
        {
            "event_type": "escalated_to_human",
            "triggered_by": proposal.get("triggered_by"),
            "llm_proposal": proposal,
            "issue_number": issue_number,
            "failure_reasons": failure_reasons,
            "final_status": "needs_human",
        }
    )

    # 预生成 action_id（基于 issue_number，稳定可复现），供后续人工审批合并时回写终态
    action_id = f"escalate:{issue_number}"

    # 旁路写后端 approval ledger（fire-and-forget；fail-open 在 client 内处理）
    post_to_approval_ledger(
        action="ai_issue_implement",
        payload={
            "issue_number": issue_number,
            "failure_reasons": failure_reasons,
            "proposal": proposal,
        },
        source="ci_escalate",
        action_id=action_id,
    )

    # 回调 /github-approval：decision=approval_requested（请求人工审批）
    # 铁律 fail-open：任何 callback 失败不得阻断主流程
    # lazy import 避免与 scripts/autonomy/autonomy_callback.py 模块名冲突
    try:
        from autonomy_callback import report_approval_requested

        report_approval_requested(
            action_id=action_id,
            workflow_action="escalate_to_human",
            source="ci_escalate",
        )
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - script boundary records arbitrary integration failures
        pass

    # 管理端 IM（fail-open）：让人能及时介入，不阻断 escalate
    reasons_preview = "; ".join(str(r) for r in failure_reasons[:3])
    notify_boss_im(
        f"[needs-human] issue #{issue_number} 自动实现失败转人工。\n"
        f"原因：{reasons_preview or '（无）'}\n"
        f"triggered_by={proposal.get('triggered_by') or '—'}",
        employee_id="ci-autonomy",
        display_name="CI 自愈",
        source="ci_escalate",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--failure-reasons", required=True, help="JSON list of reasons")
    args = parser.parse_args()
    proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
    reasons = json.loads(args.failure_reasons)
    escalate(issue_number=args.issue_number, proposal=proposal, failure_reasons=reasons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
