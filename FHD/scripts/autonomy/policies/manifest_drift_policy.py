"""Policy：manifest_drift → freeze_manifest（low）。

触发：manifest_drift 信号（由 watcher.tick 从 truth.manifest_exists=True +
      manifest_frozen=False + 部署 digest 与 manifest 不一致派生）
决策：
  - 至少 1 条 manifest_drift 信号 → freeze_manifest（low, max_attempts=1）

风险分级：low（自动执行，无 cooldown）
理由：manifest 冻结是非破坏性操作（mv .json → .json.hold），可逆，且防止 cron
      反复重试错误制品。

设计：纯函数，禁止 time.time() / datetime.now()
"""

from __future__ import annotations

from ..rca_rules import diagnose_root_cause
from ..types import Action, ActionType, Diagnosis, Plan, Policy, RiskLevel, Signal


class ManifestDriftPolicy:
    """manifest_drift → freeze_manifest。"""

    id = "manifest-drift"
    matches = ["manifest_drift"]
    gate = "auto"

    def plan(self, signals: list[Signal]) -> Plan:
        diagnosis: Diagnosis = diagnose_root_cause(signals)
        drift = [s for s in signals if s.kind == "manifest_drift"]
        if not drift:
            return Plan(diagnosis=diagnosis, actions=[])
        latest = max(drift, key=lambda s: s.ts)
        reason = f"manifest_drift 信号: {latest.detail}"
        action = Action(
            type=ActionType.FREEZE_MANIFEST,
            params={"reason": reason, "source_kind": "manifest_drift", "ts": latest.ts},
            idempotency_key="freeze_manifest:manifest_drift",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )
        return Plan(diagnosis=diagnosis, actions=[action])


# 模块级单例
manifest_drift_policy: Policy = ManifestDriftPolicy()
