"""XCMAX admin sync inbox 辅助（冲突列表 / 跳过 / 读取）。

历史实现曾独立成服务模块后被收敛；本模块保留稳定 import 路径供
``xcmax_admin`` 与 coverage-ramp 测试使用。
"""

from __future__ import annotations

from typing import Any


def list_sync_conflicts(*, limit: int = 50) -> list[dict[str, Any]]:
    """列出待处理 sync inbox 冲突（默认空列表；生产可接 DB）。"""
    _ = limit
    return []


def fetch_inbox_row(inbox_id: int) -> dict[str, Any] | None:
    _ = inbox_id
    return None


def mark_inbox_skipped(inbox_id: int) -> None:
    _ = inbox_id
