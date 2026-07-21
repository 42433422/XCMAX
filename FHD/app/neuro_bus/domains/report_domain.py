"""
Report Domain 事件类型定义

报表领域事件类型常量与轻量注册入口。NeuroBus 不强制事件类型预先声明，
但集中定义常量可避免拼写漂移、便于在 ``register_all_domains_complete`` 中
按域聚合注册。

事件命名遵循 ``domain.action_tense`` 约定：
- ``report.monthly_summary_requested``：月报生成请求（由调度器或运维触发）
- ``report.monthly_summary_generated``：月报已生成（成功）
- ``report.monthly_summary_failed``：月报生成失败
"""

from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger(__name__)

# 事件类型常量
REPORT_MONTHLY_SUMMARY_REQUESTED: Final[str] = "report.monthly_summary_requested"
REPORT_MONTHLY_SUMMARY_GENERATED: Final[str] = "report.monthly_summary_generated"
REPORT_MONTHLY_SUMMARY_FAILED: Final[str] = "report.monthly_summary_failed"


# 所有报表域事件类型（便于注册/统计/文档化）
REPORT_EVENT_TYPES: Final[tuple[str, ...]] = (
    REPORT_MONTHLY_SUMMARY_REQUESTED,
    REPORT_MONTHLY_SUMMARY_GENERATED,
    REPORT_MONTHLY_SUMMARY_FAILED,
)


__all__ = [
    "REPORT_MONTHLY_SUMMARY_REQUESTED",
    "REPORT_MONTHLY_SUMMARY_GENERATED",
    "REPORT_MONTHLY_SUMMARY_FAILED",
    "REPORT_EVENT_TYPES",
]
