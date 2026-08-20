"""Policy：disk_full → clear_logs（low，max_attempts=2）+ open_incident_issue 兜底。

触发：disk_full 信号（由 watcher.tick 从 truth.disk_usage_percent >= 90 派生，
      与桌面端 runtime-truth.ts deriveSignalsFromTruth 阈值一致）
决策：
  - 至少 1 条 disk_full 信号 → clear_logs（low, max_attempts=2）
  - 兜底：open_incident_issue（low, max_attempts=1）—— 仅当 clear_logs 失败时
    由 adapter._action_open_incident_issue 读 audit 判定前置失败后真正创建 issue

风险分级：low（自动执行）
理由：clear_logs 仅清理 7 天前的日志，对当前业务无影响；max_attempts=2 允许
      一次清理不够时再清一次（日志持续生成）。

设计：纯函数，禁止 time.time() / datetime.now()
"""

from __future__ import annotations

from typing import Literal

from ..rca_rules import diagnose_root_cause
from ..types import Action, ActionType, Diagnosis, Plan, Policy, RiskLevel, Signal


class DiskFullPolicy:
    """disk_full → clear_logs + open_incident_issue 兜底。"""

    id = "disk-full"
    matches = ["disk_full"]
    gate: Literal["auto", "approve", "manual"] = "auto"

    def plan(self, signals: list[Signal]) -> Plan:
        diagnosis: Diagnosis = diagnose_root_cause(signals)
        full = [s for s in signals if s.kind == "disk_full"]
        if not full:
            return Plan(diagnosis=diagnosis, actions=[])
        latest = max(full, key=lambda s: s.ts)
        reason = f"disk_full 信号: {latest.detail}"
        remediation_action = Action(
            type=ActionType.CLEAR_LOGS,
            params={"reason": reason, "source_kind": "disk_full", "ts": latest.ts},
            idempotency_key="clear_logs:disk_full",
            max_attempts=2,
            risk=RiskLevel.LOW,
        )
        # 兜底 action：仅当 remediation 失败时真正创建 issue（adapter 内判定）
        incident_action = Action(
            type=ActionType.OPEN_INCIDENT_ISSUE,
            params={
                "incident_type": "disk_full",
                "previous_action_key": remediation_action.idempotency_key,
                "source_kind": "disk_full",
                "reason": reason,
                "diagnosis_root_cause": diagnosis.root_cause,
                "ts": latest.ts,
            },
            idempotency_key="open_incident_issue:disk_full",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )
        return Plan(diagnosis=diagnosis, actions=[remediation_action, incident_action])


# 模块级单例
disk_full_policy: Policy = DiskFullPolicy()
