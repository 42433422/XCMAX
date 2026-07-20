"""tests/test_autonomy/test_policies.py — 4 个 Policy 决策正确性测试。

覆盖：
  - health_down → restart_service + open_incident_issue 兜底
  - manifest_drift → freeze_manifest + open_incident_issue 兜底
  - disk_full → clear_logs + open_incident_issue 兜底
  - compose_unhealthy → restart_service + open_incident_issue 兜底
  - max_attempts 耗尽 escalate（由 watcher 守护链处理；此处仅验证 policy.plan 输出）
  - cooldown 窗口外（policy 是纯函数，无 cooldown；由 watcher 状态守护）
  - 空 signals 返回空 actions
  - 多信号去重（同 kind 多条信号只产出一个 remediation + 一个兜底）
"""

from __future__ import annotations

import pytest

from scripts.autonomy.policies import (
    ALL_POLICIES,
    compose_unhealthy_policy,
    disk_full_policy,
    health_down_policy,
    manifest_drift_policy,
)
from scripts.autonomy.policies.compose_unhealthy_policy import ComposeUnhealthyPolicy
from scripts.autonomy.policies.disk_full_policy import DiskFullPolicy
from scripts.autonomy.policies.health_down_policy import HealthDownPolicy
from scripts.autonomy.policies.manifest_drift_policy import ManifestDriftPolicy
from scripts.autonomy.types import Action, ActionType, Plan, RiskLevel, Signal

# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #


def _make_signal(
    kind: str, ts: int = 1_000_000, detail: str = "test", severity: str = "crit"
) -> Signal:
    return Signal(
        source="runtime_truth",
        kind=kind,
        severity=severity,  # type: ignore[arg-type]
        detail=detail,
        ts=ts,
    )


def _assert_incident_fallback(
    action: Action,
    *,
    incident_type: str,
    previous_action_key: str,
    source_kind: str,
) -> None:
    """断言兜底 open_incident_issue action 的字段结构。"""
    assert action.type == ActionType.OPEN_INCIDENT_ISSUE
    assert action.risk == RiskLevel.LOW
    assert action.max_attempts == 1
    assert action.idempotency_key == f"open_incident_issue:{incident_type}"
    assert action.params["incident_type"] == incident_type
    assert action.params["previous_action_key"] == previous_action_key
    assert action.params["source_kind"] == source_kind
    assert "reason" in action.params
    assert "diagnosis_root_cause" in action.params
    assert "ts" in action.params


# --------------------------------------------------------------------------- #
# health_down → restart_service + open_incident_issue 兜底
# --------------------------------------------------------------------------- #


class TestHealthDownPolicy:
    def test_matches_health_down(self) -> None:
        """matches 字段包含 health_down。"""
        assert "health_down" in health_down_policy.matches

    def test_plan_returns_restart_service(
        self,
        health_down_signal: Signal,
    ) -> None:
        """health_down 信号 → restart_service remediation + open_incident_issue 兜底。"""
        plan: Plan = health_down_policy.plan([health_down_signal])

        assert len(plan.actions) == 2
        remediation, incident = plan.actions
        # remediation action
        assert remediation.type == ActionType.RESTART_SERVICE
        assert remediation.risk == RiskLevel.MEDIUM
        assert remediation.max_attempts == 1
        assert remediation.idempotency_key == "restart_service:health_down"
        # 兜底 incident action
        _assert_incident_fallback(
            incident,
            incident_type="health_down",
            previous_action_key="restart_service:health_down",
            source_kind="health_down",
        )

    def test_plan_empty_signals_returns_empty(self) -> None:
        """空 signals → 空 actions（diagnosis 仍生成）。"""
        plan = health_down_policy.plan([])

        assert plan.actions == []
        assert plan.diagnosis.root_cause == "unknown"

    def test_plan_ignores_other_kinds(self) -> None:
        """plan 只处理 health_down，忽略其他 kind。"""
        other = _make_signal("disk_full")
        plan = health_down_policy.plan([other])

        assert plan.actions == []

    def test_plan_uses_latest_signal_for_reason(self) -> None:
        """多信号时取最新 ts 的信号作为 reason。"""
        old = _make_signal("health_down", ts=900_000, detail="old")
        new = _make_signal("health_down", ts=1_000_000, detail="new")
        plan = health_down_policy.plan([old, new])

        assert len(plan.actions) == 2
        remediation, incident = plan.actions
        assert "new" in remediation.params["reason"]
        assert "new" in incident.params["reason"]


# --------------------------------------------------------------------------- #
# manifest_drift → freeze_manifest + open_incident_issue 兜底
# --------------------------------------------------------------------------- #


class TestManifestDriftPolicy:
    def test_matches_manifest_drift(self) -> None:
        assert "manifest_drift" in manifest_drift_policy.matches

    def test_plan_returns_freeze_manifest(self) -> None:
        """manifest_drift 信号 → freeze_manifest + open_incident_issue 兜底。"""
        sig = _make_signal("manifest_drift", severity="warn", detail="sha mismatch")
        plan = manifest_drift_policy.plan([sig])

        assert len(plan.actions) == 2
        remediation, incident = plan.actions
        # remediation
        assert remediation.type == ActionType.FREEZE_MANIFEST
        assert remediation.risk == RiskLevel.LOW
        assert remediation.max_attempts == 1
        assert remediation.idempotency_key == "freeze_manifest:manifest_drift"
        # 兜底
        _assert_incident_fallback(
            incident,
            incident_type="manifest_drift",
            previous_action_key="freeze_manifest:manifest_drift",
            source_kind="manifest_drift",
        )


# --------------------------------------------------------------------------- #
# disk_full → clear_logs + open_incident_issue 兜底
# --------------------------------------------------------------------------- #


class TestDiskFullPolicy:
    def test_matches_disk_full(self) -> None:
        assert "disk_full" in disk_full_policy.matches

    def test_plan_returns_clear_logs(
        self,
        disk_full_signal: Signal,
    ) -> None:
        """disk_full 信号 → clear_logs + open_incident_issue 兜底。"""
        plan = disk_full_policy.plan([disk_full_signal])

        assert len(plan.actions) == 2
        remediation, incident = plan.actions
        # remediation
        assert remediation.type == ActionType.CLEAR_LOGS
        assert remediation.risk == RiskLevel.LOW
        assert remediation.max_attempts == 2  # disk_full 允许 2 次（清理后仍满可再清）
        assert remediation.idempotency_key == "clear_logs:disk_full"
        # 兜底
        _assert_incident_fallback(
            incident,
            incident_type="disk_full",
            previous_action_key="clear_logs:disk_full",
            source_kind="disk_full",
        )


# --------------------------------------------------------------------------- #
# compose_unhealthy → restart_service + open_incident_issue 兜底
# --------------------------------------------------------------------------- #


class TestComposeUnhealthyPolicy:
    def test_matches_compose_unhealthy(self) -> None:
        assert "compose_unhealthy" in compose_unhealthy_policy.matches

    def test_plan_returns_restart_service(self) -> None:
        """compose_unhealthy 信号 → restart_service + open_incident_issue 兜底。"""
        sig = _make_signal("compose_unhealthy", detail="compose exited")
        plan = compose_unhealthy_policy.plan([sig])

        assert len(plan.actions) == 2
        remediation, incident = plan.actions
        # remediation
        assert remediation.type == ActionType.RESTART_SERVICE
        assert remediation.risk == RiskLevel.MEDIUM
        assert remediation.max_attempts == 1
        assert remediation.idempotency_key == "restart_service:compose_unhealthy"
        # 兜底
        _assert_incident_fallback(
            incident,
            incident_type="compose_unhealthy",
            previous_action_key="restart_service:compose_unhealthy",
            source_kind="compose_unhealthy",
        )


# --------------------------------------------------------------------------- #
# 综合测试
# --------------------------------------------------------------------------- #


class TestAllPolicies:
    def test_all_policies_list_has_4(self) -> None:
        """ALL_POLICIES 包含 4 个 policy。"""
        assert len(ALL_POLICIES) == 4
        ids = {p.id for p in ALL_POLICIES}
        assert ids == {"health-down", "manifest-drift", "disk-full", "compose-unhealthy"}

    def test_each_policy_has_unique_id(self) -> None:
        """每个 policy id 唯一。"""
        ids = [p.id for p in ALL_POLICIES]
        assert len(ids) == len(set(ids))

    def test_each_policy_matches_disjoint_kinds(self) -> None:
        """4 个 policy 的 matches 集合互不重叠。"""
        all_kinds: list[str] = []
        for p in ALL_POLICIES:
            all_kinds.extend(p.matches)
        assert len(all_kinds) == len(set(all_kinds))

    def test_empty_signals_all_return_empty_actions(self) -> None:
        """空 signals 时所有 policy 都返回空 actions。"""
        for policy in ALL_POLICIES:
            plan = policy.plan([])
            assert plan.actions == [], f"{policy.id} 应返回空 actions"

    def test_multi_signals_same_kind_deduplicated(self) -> None:
        """同 kind 多条信号 → policy 仍只产出 remediation + 兜底 共 2 个 action（取最新）。"""
        signals = [
            _make_signal("health_down", ts=900_000, detail="old"),
            _make_signal("health_down", ts=950_000, detail="mid"),
            _make_signal("health_down", ts=1_000_000, detail="new"),
        ]
        plan = health_down_policy.plan(signals)

        assert len(plan.actions) == 2
        remediation, incident = plan.actions
        assert "new" in remediation.params["reason"]
        assert "new" in incident.params["reason"]


# --------------------------------------------------------------------------- #
# Policy 类直接实例化（验证 Protocol duck typing）
# --------------------------------------------------------------------------- #


class TestPolicyClasses:
    def test_health_down_policy_class_instantiable(self) -> None:
        """HealthDownPolicy 类可直接实例化。"""
        p = HealthDownPolicy()
        assert p.id == "health-down"
        assert p.gate == "auto"

    def test_disk_full_policy_class_instantiable(self) -> None:
        p = DiskFullPolicy()
        assert p.id == "disk-full"

    def test_manifest_drift_policy_class_instantiable(self) -> None:
        p = ManifestDriftPolicy()
        assert p.id == "manifest-drift"

    def test_compose_unhealthy_policy_class_instantiable(self) -> None:
        p = ComposeUnhealthyPolicy()
        assert p.id == "compose-unhealthy"


# --------------------------------------------------------------------------- #
# diagnosis 生成验证
# --------------------------------------------------------------------------- #


class TestDiagnosis:
    def test_diagnosis_root_cause_mapped(
        self,
        health_down_signal: Signal,
    ) -> None:
        """health_down 信号 → root_cause='service_unhealthy'。"""
        plan = health_down_policy.plan([health_down_signal])
        assert plan.diagnosis.root_cause == "service_unhealthy"
        assert plan.diagnosis.confidence == 0.8

    def test_diagnosis_evidence_contains_signal_detail(
        self,
        health_down_signal: Signal,
    ) -> None:
        """diagnosis.evidence 包含信号 detail。"""
        plan = health_down_policy.plan([health_down_signal])
        assert any("health check failed" in e for e in plan.diagnosis.evidence)
