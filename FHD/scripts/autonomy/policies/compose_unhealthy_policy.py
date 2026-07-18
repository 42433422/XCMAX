"""Policy：compose_unhealthy → restart_service（medium + cooldown 5min）。

触发：compose_unhealthy 信号（由 watcher.tick 从 truth.compose_status != 'running'
      或 truth.service_running=False 派生）
决策：
  - 至少 1 条 compose_unhealthy 信号 → restart_service（medium, max_attempts=1）
  - max_attempts 耗尽后由 watcher 守护链转 escalate

风险分级：medium（自动执行 + cooldown 5min，与 health_down 一致）
理由：compose restart 是非破坏性操作，但 5min cooldown 防止反复重启。

设计：纯函数，禁止 time.time() / datetime.now()
"""

from __future__ import annotations

from ..rca_rules import diagnose_root_cause
from ..types import Action, ActionType, Diagnosis, Plan, Policy, RiskLevel, Signal


class ComposeUnhealthyPolicy:
    """compose_unhealthy → restart_service。"""

    id = "compose-unhealthy"
    matches = ["compose_unhealthy"]
    gate = "auto"

    def plan(self, signals: list[Signal]) -> Plan:
        diagnosis: Diagnosis = diagnose_root_cause(signals)
        unhealthy = [s for s in signals if s.kind == "compose_unhealthy"]
        if not unhealthy:
            return Plan(diagnosis=diagnosis, actions=[])
        latest = max(unhealthy, key=lambda s: s.ts)
        reason = f"compose_unhealthy 信号: {latest.detail}"
        action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": reason, "source_kind": "compose_unhealthy", "ts": latest.ts},
            idempotency_key="restart_service:compose_unhealthy",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        return Plan(diagnosis=diagnosis, actions=[action])


# 模块级单例
compose_unhealthy_policy: Policy = ComposeUnhealthyPolicy()
