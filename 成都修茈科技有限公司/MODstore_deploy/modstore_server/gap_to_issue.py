"""把 LLM 提议转成 GitHub issue（打 ai-implement 标签）。

调用 gh CLI 创建 issue。body 含完整 LLM 提议 JSON。

T-C14：相同 proposal_id（"gap" 的唯一身份）永不重复开 issue——
:func:`dedupe_signal` 默认 ``permanent=True``，扫描全部历史 ``issue_opened``
事件，发现同 proposal_id 即抛 :class:`DuplicateProposalError`。这保证
演化调度器/LLM 即使重复触发同一个 gap 信号，也只会在 GitHub 上创建一个 issue。
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from modstore_server.evolution_ledger import append_event, list_events

AI_IMPLEMENT_LABEL = "ai-implement"
# Legacy 短窗口去重常量，仅 ``permanent=False`` 时使用。
# 保留是为了向后兼容（早期测试 / 旧版调用方），新代码应默认 permanent。
DEDUP_WINDOW_MINUTES = 5


class DuplicateProposalError(ValueError):
    """同一 proposal_id 已经开过 issue。

    T-C14 起默认 permanent=True：同 proposal_id 一旦在 ledger 留下
    ``issue_opened`` 记录，再次调用 :func:`open_issue_for_proposal` 必然抛本异常。
    """


def build_issue_body(proposal: Dict[str, Any]) -> str:
    """构造 issue body，含 LLM 提议 JSON code block。"""
    return f"""# 自动演化提议：{proposal.get('employee_pack', {}).get('name', '<unnamed>')}

**Department**: {proposal.get('department')}
**Triggered by**: {proposal.get('triggered_by')}
**Signal score**: {proposal.get('signal_score')}
**Estimated files**: {proposal.get('estimated_files')}
**Estimated tokens**: {proposal.get('estimated_tokens')}

## Employee Pack Proposal

```json
{json.dumps(proposal, ensure_ascii=False, indent=2)}
```

## Acceptance Criteria

{chr(10).join('- ' + c for c in proposal.get('employee_pack', {}).get('acceptance_criteria', []))}

---

此 issue 由演化闭环自动创建。打 `ai-implement` 标签后将触发 `ai-issue-implement.yml` workflow。
"""


def dedupe_signal(proposal: Dict[str, Any], *, permanent: bool = True) -> None:
    """检查同 proposal_id 是否已开过 issue。

    T-C14 调度幂等契约：

    - ``permanent=True``（默认）：扫描全部历史 ``issue_opened`` 事件，只要
      任意一条事件的 ``llm_proposal.proposal_id`` 与当前 proposal 相同，即抛
      :class:`DuplicateProposalError`。这是 :func:`open_issue_for_proposal`
      的默认行为——保证同一个 gap 永远只开一个 GitHub issue。
    - ``permanent=False``（legacy）：仅在 :data:`DEDUP_WINDOW_MINUTES` 分钟
      窗口内去重。保留是为了让旧测试可以显式 opt-out 永久去重。

    缺失 ``proposal_id`` 时跳过校验（与原行为一致），调用方有责任保证
    proposal 已通过 :func:`employee_autonomy_service.validate_proposal`。
    """
    proposal_id = proposal.get("proposal_id")
    if not proposal_id:
        return

    # 直接用 event_type 过滤，避免在 dedupe 里二次过滤全量 ledger。
    events = list_events(event_type="issue_opened")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=DEDUP_WINDOW_MINUTES)

    for evt in events:
        evt_pid = (evt.get("llm_proposal") or {}).get("proposal_id")
        if evt_pid != proposal_id:
            continue
        if not permanent:
            # legacy 短窗口模式：只阻断 DEDUP_WINDOW_MINUTES 内的重复
            try:
                ts = datetime.fromisoformat(
                    evt.get("timestamp", "").replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue
            if ts < cutoff:
                continue
        raise DuplicateProposalError(
            f"proposal {proposal_id} already has issue opened at "
            f"{evt.get('timestamp', '?')}"
        )


def open_issue_for_proposal(proposal: Dict[str, Any]) -> str:
    """调 gh CLI 创建 issue，返回 issue URL。

    T-C14：先 :func:`dedupe_signal` 永久幂等校验——同 proposal_id 重复调用
    必然抛 :class:`DuplicateProposalError`，不会触发 ``gh issue create``。
    """
    dedupe_signal(proposal)  # 默认 permanent=True

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
        "--label",
        AI_IMPLEMENT_LABEL,
    ]
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
