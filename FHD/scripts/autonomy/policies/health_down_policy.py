"""Policy：health_down → restart_service（medium + cooldown 5min）+ open_incident_issue 兜底。

触发：health_down 信号（由 watcher.tick 从 truth.health_ok=False 派生）
决策：
  - 至少 1 条 health_down 信号 → restart_service（medium, max_attempts=1）
  - 兜底：open_incident_issue（low, max_attempts=1）—— 仅当 restart_service 失败时
    由 adapter._action_open_incident_issue 读 audit 判定前置失败后真正创建 issue
  - max_attempts 耗尽后由 watcher 守护链转 escalate（不在此处实现）

风险分级：medium（自动执行 + cooldown 5min，与桌面端 restart_backend 一致）

设计：纯函数，禁止 time.time() / datetime.now()
"""

from __future__ import annotations

from typing import Literal

from ..rca_rules import diagnose_root_cause
from ..types import Action, ActionType, Diagnosis, Plan, Policy, RiskLevel, Signal


class HealthDownPolicy:
    """health_down → restart_service + open_incident_issue 兜底。

    注：Python Protocol 通过 duck typing 实现，无需显式继承。
    """

    id = "health-down"
    matches = ["health_down"]
    gate: Literal["auto", "approve", "manual"] = "auto"

    def plan(self, signals: list[Signal]) -> Plan:
        diagnosis: Diagnosis = diagnose_root_cause(signals)
        health_down = [s for s in signals if s.kind == "health_down"]
        if not health_down:
            return Plan(diagnosis=diagnosis, actions=[])
        # 取最新信号作为主因
        latest = max(health_down, key=lambda s: s.ts)
        reason = f"health_down 信号: {latest.detail}"
        remediation_action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": reason, "source_kind": "health_down", "ts": latest.ts},
            idempotency_key="restart_service:health_down",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        # 兜底 action：仅当 remediation 失败时真正创建 issue（adapter 内判定）
        incident_action = Action(
            type=ActionType.OPEN_INCIDENT_ISSUE,
            params={
                "incident_type": "health_down",
                "previous_action_key": remediation_action.idempotency_key,
                "source_kind": "health_down",
                "reason": reason,
                "diagnosis_root_cause": diagnosis.root_cause,
                "ts": latest.ts,
            },
            idempotency_key="open_incident_issue:health_down",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )
        return Plan(diagnosis=diagnosis, actions=[remediation_action, incident_action])


# 模块级单例（与桌面端 backendCrashPolicy 一致）
health_down_policy: Policy = HealthDownPolicy()
