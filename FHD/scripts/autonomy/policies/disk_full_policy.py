"""Policy：disk_full → clear_logs（low，max_attempts=2）。

触发：disk_full 信号（由 watcher.tick 从 truth.disk_usage_percent >= 90 派生，
      与桌面端 runtime-truth.ts deriveSignalsFromTruth 阈值一致）
决策：
  - 至少 1 条 disk_full 信号 → clear_logs（low, max_attempts=2）

风险分级：low（自动执行）
理由：clear_logs 仅清理 7 天前的日志，对当前业务无影响；max_attempts=2 允许
      一次清理不够时再清一次（日志持续生成）。

设计：纯函数，禁止 time.time() / datetime.now()
"""

from __future__ import annotations

from ..rca_rules import diagnose_root_cause
from ..types import Action, ActionType, Diagnosis, Plan, Policy, RiskLevel, Signal


class DiskFullPolicy:
    """disk_full → clear_logs。"""

    id = "disk-full"
    matches = ["disk_full"]
    gate = "auto"

    def plan(self, signals: list[Signal]) -> Plan:
        diagnosis: Diagnosis = diagnose_root_cause(signals)
        full = [s for s in signals if s.kind == "disk_full"]
        if not full:
            return Plan(diagnosis=diagnosis, actions=[])
        latest = max(full, key=lambda s: s.ts)
        reason = f"disk_full 信号: {latest.detail}"
        action = Action(
            type=ActionType.CLEAR_LOGS,
            params={"reason": reason, "source_kind": "disk_full", "ts": latest.ts},
            idempotency_key="clear_logs:disk_full",
            max_attempts=2,
            risk=RiskLevel.LOW,
        )
        return Plan(diagnosis=diagnosis, actions=[action])


# 模块级单例
disk_full_policy: Policy = DiskFullPolicy()
