"""把 LLM 提议转成 GitHub issue（打 ai-implement 标签）。

调用 gh CLI 创建 issue。body 含完整 LLM 提议 JSON。
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any, Dict

from modstore_server.evolution_ledger import append_event, list_events

AI_IMPLEMENT_LABEL = "ai-implement"
DEDUP_WINDOW_MINUTES = 5


class DuplicateProposalError(ValueError):
    """同一 proposal_id 在去重窗口内已开过 issue。"""


def build_issue_body(proposal: Dict[str, Any]) -> str:
    """构造 issue body，含 LLM 提议 JSON code block。"""
    return f"""# 自动演化提议：{proposal.get("employee_pack", {}).get("name", "<unnamed>")}

**Department**: {proposal.get("department")}
**Triggered by**: {proposal.get("triggered_by")}
**Signal score**: {proposal.get("signal_score")}
**Estimated files**: {proposal.get("estimated_files")}
**Estimated tokens**: {proposal.get("estimated_tokens")}

## Employee Pack Proposal

```json
{json.dumps(proposal, ensure_ascii=False, indent=2)}
```

## Acceptance Criteria

{chr(10).join("- " + c for c in proposal.get("employee_pack", {}).get("acceptance_criteria", []))}

---

此 issue 由演化闭环自动创建。打 `ai-implement` 标签后将触发 `ai-issue-implement.yml` workflow。
"""


def dedupe_signal(proposal: Dict[str, Any]) -> None:
    """检查去重窗口内是否已开过同 proposal_id 的 issue。"""
    proposal_id = proposal.get("proposal_id")
    if not proposal_id:
        return
    recent = list_events(since_days=1)
    cutoff = datetime.now(UTC) - timedelta(minutes=DEDUP_WINDOW_MINUTES)
    for evt in recent:
        if evt.get("event_type") != "issue_opened":
            continue
        evt_pid = (evt.get("llm_proposal") or {}).get("proposal_id")
        if evt_pid != proposal_id:
            continue
        try:
            ts = datetime.fromisoformat(evt.get("timestamp", "").replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ts >= cutoff:
            raise DuplicateProposalError(
                f"proposal {proposal_id} already has issue opened at {ts.isoformat()}"
            )


def open_issue_for_proposal(
    proposal: Dict[str, Any],
    *,
    add_implement_label: bool = True,
) -> str:
    """调 gh CLI 创建 issue，返回 issue URL。

    Args:
        proposal: LLM 提议字典。
        add_implement_label: 默认 True（兼容旧路径：靠标签间接触发 implement）。
            演化 ledger 连接点 4 显式 dispatch 时应传 False，避免双重触发。
    """
    dedupe_signal(proposal)

    repo = os.environ.get("GITHUB_REPO", "")
    if not repo:
        raise RuntimeError("GITHUB_REPO env var not set")

    body = build_issue_body(proposal)
    title = f"[evolution] {proposal.get('employee_pack', {}).get('name', 'unnamed')} ({proposal.get('department')})"

    cmd = [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body",
        body,
    ]
    if add_implement_label:
        cmd.extend(["--label", AI_IMPLEMENT_LABEL])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh issue create failed (rc={result.returncode}): {result.stderr}")

    issue_url = result.stdout.strip()
    append_event(
        {
            "event_type": "issue_opened",
            "triggered_by": proposal.get("triggered_by"),
            "signal_score": proposal.get("signal_score"),
            "llm_proposal": proposal,
            "issue_url": issue_url,
        }
    )
    return issue_url
