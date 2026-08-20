"""Policy：compose_unhealthy → restart_service（medium + cooldown 5min）+ open_incident_issue 兜底。

触发：compose_unhealthy 信号（由 watcher.tick 从 truth.compose_status != 'running'
      或 truth.service_running=False 派生）
决策：
  - 至少 1 条 compose_unhealthy 信号 → restart_service（medium, max_attempts=1）
  - 兜底：open_incident_issue（low, max_attempts=1）—— 仅当 restart_service 失败时
    由 adapter._action_open_incident_issue 读 audit 判定前置失败后真正创建 issue
  - max_attempts 耗尽后由 watcher 守护链转 escalate

风险分级：medium（自动执行 + cooldown 5min，与 health_down 一致）
理由：compose restart 是非破坏性操作，但 5min cooldown 防止反复重启。

设计：纯函数，禁止 time.time() / datetime.now()
"""

from __future__ import annotations

from typing import Literal

from ..rca_rules import diagnose_root_cause
from ..types import Action, ActionType, Diagnosis, Plan, Policy, RiskLevel, Signal


class ComposeUnhealthyPolicy:
    """compose_unhealthy → restart_service + open_incident_issue 兜底。"""

    id = "compose-unhealthy"
    matches = ["compose_unhealthy"]
    gate: Literal["auto", "approve", "manual"] = "auto"

    def plan(self, signals: list[Signal]) -> Plan:
        diagnosis: Diagnosis = diagnose_root_cause(signals)
        unhealthy = [s for s in signals if s.kind == "compose_unhealthy"]
        if not unhealthy:
            return Plan(diagnosis=diagnosis, actions=[])
        latest = max(unhealthy, key=lambda s: s.ts)
        reason = f"compose_unhealthy 信号: {latest.detail}"
        remediation_action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": reason, "source_kind": "compose_unhealthy", "ts": latest.ts},
            idempotency_key="restart_service:compose_unhealthy",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        # 兜底 action：仅当 remediation 失败时真正创建 issue（adapter 内判定）
        incident_action = Action(
            type=ActionType.OPEN_INCIDENT_ISSUE,
            params={
                "incident_type": "compose_unhealthy",
                "previous_action_key": remediation_action.idempotency_key,
                "source_kind": "compose_unhealthy",
                "reason": reason,
                "diagnosis_root_cause": diagnosis.root_cause,
                "ts": latest.ts,
            },
            idempotency_key="open_incident_issue:compose_unhealthy",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )
        return Plan(diagnosis=diagnosis, actions=[remediation_action, incident_action])


# 模块级单例
compose_unhealthy_policy: Policy = ComposeUnhealthyPolicy()
