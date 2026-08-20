"""Policy：manifest_drift → freeze_manifest（low）+ open_incident_issue 兜底。

触发：manifest_drift 信号（由 watcher.tick 从 truth.manifest_exists=True +
      manifest_frozen=False + 部署 digest 与 manifest 不一致派生）
决策：
  - 至少 1 条 manifest_drift 信号 → freeze_manifest（low, max_attempts=1）
  - 兜底：open_incident_issue（low, max_attempts=1）—— 仅当 freeze_manifest 失败时
    由 adapter._action_open_incident_issue 读 audit 判定前置失败后真正创建 issue

风险分级：low（自动执行，无 cooldown）
理由：manifest 冻结是非破坏性操作（创建 .frozen marker），可逆，且防止 cron
      反复重试错误制品。

设计：纯函数，禁止 time.time() / datetime.now()
"""

from __future__ import annotations

from typing import Literal

from ..rca_rules import diagnose_root_cause
from ..types import Action, ActionType, Diagnosis, Plan, Policy, RiskLevel, Signal


class ManifestDriftPolicy:
    """manifest_drift → freeze_manifest + open_incident_issue 兜底。"""

    id = "manifest-drift"
    matches = ["manifest_drift"]
    gate: Literal["auto", "approve", "manual"] = "auto"

    def plan(self, signals: list[Signal]) -> Plan:
        diagnosis: Diagnosis = diagnose_root_cause(signals)
        drift = [s for s in signals if s.kind == "manifest_drift"]
        if not drift:
            return Plan(diagnosis=diagnosis, actions=[])
        latest = max(drift, key=lambda s: s.ts)
        reason = f"manifest_drift 信号: {latest.detail}"
        remediation_action = Action(
            type=ActionType.FREEZE_MANIFEST,
            params={"reason": reason, "source_kind": "manifest_drift", "ts": latest.ts},
            idempotency_key="freeze_manifest:manifest_drift",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )
        # 兜底 action：仅当 remediation 失败时真正创建 issue（adapter 内判定）
        incident_action = Action(
            type=ActionType.OPEN_INCIDENT_ISSUE,
            params={
                "incident_type": "manifest_drift",
                "previous_action_key": remediation_action.idempotency_key,
                "source_kind": "manifest_drift",
                "reason": reason,
                "diagnosis_root_cause": diagnosis.root_cause,
                "ts": latest.ts,
            },
            idempotency_key="open_incident_issue:manifest_drift",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )
        return Plan(diagnosis=diagnosis, actions=[remediation_action, incident_action])


# 模块级单例
manifest_drift_policy: Policy = ManifestDriftPolicy()
