#!/usr/bin/env python3
"""重试机制：任一门禁失败时，最多重试 MAX_RETRIES 次，每次调整 prompt。

3 次都败 → 写 ledger final_status=needs_human。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# 重要：plan 中是 parent.parent.parent（3 层），但脚本在 FHD/scripts/dev/，
# 3 层 parent 只到 FHD/，需要 4 层才能到 /Users/a4243342/Desktop/XCMAX
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "成都修茈科技有限公司" / "MODstore_deploy"))

from modstore_server.evolution_ledger import append_event  # noqa: E402

MAX_RETRIES = 3


def adjust_prompt_for_retry(base_prompt: str, *, retry_count: int, failure_reason: str) -> str:
    """根据重试次数调整 prompt。"""
    if retry_count == 1:
        return f"{base_prompt}\n\n上一次失败原因：{failure_reason}，请避免。"
    if retry_count == 2:
        return f"{base_prompt}\n\n已失败 2 次，请简化设计，文件数 ≤ 3。"
    if retry_count == 3:
        return f"{base_prompt}\n\n已失败 3 次，请最小化实现，只做最核心 1 个文件。"
    return base_prompt


def run_with_retries(
    *,
    base_prompt: str,
    action: Callable[[str], Dict[str, Any]],
    failure_checker: Callable[[Dict[str, Any]], Tuple[bool, Optional[str]]],
    proposal: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行 action，最多重试 MAX_RETRIES 次。

    action: 接收 prompt 返回 dict
    failure_checker: 接收 action 结果，返回 (is_failure: bool, reason: Optional[str])
    """
    failure_reasons: List[str] = []
    current_prompt = base_prompt

    for attempt in range(1, MAX_RETRIES + 1):
        if attempt > 1:
            last_reason = failure_reasons[-1] if failure_reasons else "unknown"
            current_prompt = adjust_prompt_for_retry(
                base_prompt, retry_count=attempt, failure_reason=last_reason
            )

        result = action(current_prompt)
        is_failure, reason = failure_checker(result)
        if not is_failure:
            return {
                "success": True,
                "result": result,
                "attempts": attempt,
                "failure_reasons": failure_reasons,
            }

        if reason:
            failure_reasons.append(reason)
        append_event(
            {
                "event_type": "implement_failed",
                "triggered_by": (proposal or {}).get("triggered_by"),
                "llm_proposal": proposal,
                "retry_count": attempt,
                "failure_reason": reason or "unknown",
            }
        )

    # 全部失败 → 转 needs_human
    append_event(
        {
            "event_type": "implement_failed",
            "triggered_by": (proposal or {}).get("triggered_by"),
            "llm_proposal": proposal,
            "final_status": "needs_human",
            "retry_count": MAX_RETRIES,
            "failure_reasons": failure_reasons,
        }
    )
    return {
        "success": False,
        "attempts": MAX_RETRIES,
        "failure_reasons": failure_reasons,
        "final_status": "needs_human",
    }


def main() -> int:
    """CLI entry：作为可执行脚本时，从 stdin 读 prompt，输出 result JSON。

    实际由 ai-issue-implement.yml 调用 Python import run_with_retries，
    不直接走 main()。这里保留为可执行入口。
    """
    print("This script is meant to be imported, not run directly.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
