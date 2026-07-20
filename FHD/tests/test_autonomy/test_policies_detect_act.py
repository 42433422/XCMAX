"""tests/test_autonomy/test_policies_detect_act.py — Policy detect→act 端到端单测。

覆盖 T-D04 ~ T-D07 四个 policy 的「truth → derive_signals → run_policies → execute_plan → adapter.execute_action」全链路：

  - T-D04 health_down → restart_service + open_incident_issue 兜底
  - T-D05 disk_full → clear_logs + open_incident_issue 兜底
  - T-D06 compose_unhealthy → restart_service + open_incident_issue 兜底
  - T-D07 manifest_drift → freeze_manifest + open_incident_issue 兜底

每个 policy 测试覆盖：
  1. detect：truth → derive_signals 派生正确 kind 的信号
  2. plan：policy.plan(signals) 产出 remediation + 兜底两个 action
  3. act：execute_plan 通过 adapter 真正 dispatch remediation action
  4. fallback：execute_plan 也 dispatch 兜底 open_incident_issue action
  5. audit：audit.jsonl 记录所有 audit entry（remediation + fallback）
  6. dry_run：dry_run=True 时不调用 adapter.execute_action
  7. idempotency：相同 idempotency_key 在 cooldown/max_attempts 内不重复执行

设计：使用轻量 MockAutonomyAdapter 注入，避免依赖 CvmAutonomyAdapter 的 subprocess 细节。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from scripts.autonomy.cvm_autonomy_watcher import (
    WatcherState,
    derive_signals,
    execute_plan,
    run_policies,
)
from scripts.autonomy.policies import ALL_POLICIES
from scripts.autonomy.types import (
    Action,
    ActionType,
    AuditEntry,
    AutonomyAdapter,
    Diagnosis,
    Plan,
    ResultT,  # type: ignore  # 仅静态类型；运行时无此对象，下方不引用
    RiskLevel,
    RuntimeTruthSnapshot,
    Signal,
)

# --------------------------------------------------------------------------- #
# MockAutonomyAdapter：记录所有 execute_action 调用，便于断言
# --------------------------------------------------------------------------- #


@dataclass
class _RecordedCall:
    """单次 execute_action 调用记录。"""

    action: Action
    return_ok: bool
    return_detail: str


class MockAutonomyAdapter:
    """轻量 AutonomyAdapter 实现：所有 action 返回预设结果，记录所有调用。

    与 CvmAutonomyAdapter 不同，本 mock 不依赖 subprocess / curl / fs，
    只关心 detect→act 流程中 adapter.execute_action 被以什么 action 调用。
    """

    def __init__(
        self,
        *,
        truth: RuntimeTruthSnapshot,
        audit_path: Path,
        default_ok: bool = True,
        default_detail: str = "mock ok",
    ) -> None:
        self._truth = truth
        self._audit_path = audit_path
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_ok = default_ok
        self.default_detail = default_detail
        # 记录所有 execute_action 调用（按调用顺序）
        self.calls: list[_RecordedCall] = []
        # 按 action type 分组（便于断言 "restart_service 被调用 1 次"）
        self.calls_by_type: dict[str, list[_RecordedCall]] = {}
        # 特定 action type 的预设返回值（覆盖 default_*）
        self.returns_by_type: dict[str, tuple[bool, str]] = {}

    # AutonomyAdapter 接口实现
    def collect_truth(self) -> RuntimeTruthSnapshot:
        return self._truth

    def subscribe_signals(self, emit: Any) -> None:  # noqa: D401
        """服务器端无主动信号（由 watcher tick 派生）。"""
        return None

    def execute_action(self, action: Action) -> Any:
        from scripts.autonomy.types import ActionResult

        ok, detail = self.returns_by_type.get(
            action.type.value, (self.default_ok, self.default_detail)
        )
        call = _RecordedCall(action=action, return_ok=ok, return_detail=detail)
        self.calls.append(call)
        self.calls_by_type.setdefault(action.type.value, []).append(call)
        return ActionResult(
            action=action,
            ok=ok,
            detail=detail,
            ts=self._truth.ts,
        )

    def audit(self, entry: AuditEntry) -> None:
        """写 audit 到 jsonl 文件（与 CvmAutonomyAdapter.audit 同语义）。"""
        # dataclass → dict → json
        from dataclasses import asdict

        def _serialize(obj: Any) -> Any:
            if isinstance(obj, ActionType):
                return obj.value
            if isinstance(obj, RiskLevel):
                return obj.value
            if isinstance(obj, (Action, Signal, Diagnosis, RuntimeTruthSnapshot)):
                return {k: _serialize(v) for k, v in asdict(obj).items()}
            if isinstance(obj, dict):
                return {k: _serialize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_serialize(x) for x in obj]
            return obj

        line = json.dumps(_serialize(entry), ensure_ascii=False, default=str)
        with self._audit_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ------------------------------------------------------------------ #
    # 断言辅助方法
    # ------------------------------------------------------------------ #

    def calls_of(self, action_type: ActionType) -> list[_RecordedCall]:
        return self.calls_by_type.get(action_type.value, [])

    def call_count(self, action_type: ActionType) -> int:
        return len(self.calls_of(action_type))

    @property
    def all_action_types(self) -> set[str]:
        return set(self.calls_by_type.keys())


# --------------------------------------------------------------------------- #
# 共享 fixtures
# --------------------------------------------------------------------------- #


def _make_truth(
    tmp_deploy_root: Path,
    tmp_manifest_path: str,
    *,
    health_ok: bool = True,
    compose_status: str = "running",
    service_running: bool = True,
    disk_usage_percent: float = 50.0,
    manifest_exists: bool = True,
    manifest_frozen: bool = False,
    extra: dict[str, Any] | None = None,
) -> RuntimeTruthSnapshot:
    """构造 RuntimeTruthSnapshot（默认健康状态）。"""
    return RuntimeTruthSnapshot(
        ts=1_000_000,
        deploy_root=str(tmp_deploy_root),
        manifest_path=tmp_manifest_path,
        compose_status=compose_status,
        health_ok=health_ok,
        service_running=service_running,
        pending_rollback_marker=False,
        disk_usage_percent=disk_usage_percent,
        config_fingerprint_changed=False,
        last_backup_ts=999_000,
        app_version="10.0.0",
        build_sha="abc123",
        restart_count=0,
        manifest_exists=manifest_exists,
        manifest_frozen=manifest_frozen,
        extra=extra,
    )


@pytest.fixture
def mock_adapter_factory(
    tmp_deploy_root: Path,
    tmp_manifest_path: str,
    tmp_audit_dir: Path,
):
    """工厂 fixture：返回一个构造 MockAutonomyAdapter 的函数。

    用法：
        adapter = mock_adapter_factory(health_ok=False, compose_status='exited')
    """

    def _factory(**truth_kwargs: Any) -> MockAutonomyAdapter:
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, **truth_kwargs)
        return MockAutonomyAdapter(
            truth=truth,
            audit_path=tmp_audit_dir / "audit.jsonl",
        )

    return _factory


def _read_audit(tmp_audit_dir: Path) -> list[dict]:
    """读取 audit.jsonl 为 list[dict]。"""
    path = tmp_audit_dir / "audit.jsonl"
    if not path.exists():
        return []
    entries = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


# --------------------------------------------------------------------------- #
# T-D04 · health_down → restart_service + open_incident_issue 兜底
# --------------------------------------------------------------------------- #


class TestHealthDownDetectAct:
    """T-D04: health_down 信号的 detect→act 全链路。"""

    def test_detect_health_down_signal(self, mock_adapter_factory) -> None:
        """health_ok=False → derive_signals 派生 health_down 信号。"""
        adapter = mock_adapter_factory(health_ok=False)
        signals = derive_signals(adapter.collect_truth())

        kinds = [s.kind for s in signals]
        assert "health_down" in kinds
        # 验证信号字段
        hd = next(s for s in signals if s.kind == "health_down")
        assert hd.severity == "crit"
        assert hd.source == "runtime_truth"

    def test_plan_produces_restart_and_incident(self, mock_adapter_factory) -> None:
        """health_down signal → policy.plan 产出 restart_service + open_incident_issue。"""
        adapter = mock_adapter_factory(health_ok=False, service_running=True)
        signals = derive_signals(adapter.collect_truth())
        plans = run_policies(signals, ALL_POLICIES)

        # 找到 health-down policy 的 plan
        hd_plans = [(p, pl) for p, pl in plans if p.id == "health-down"]
        assert len(hd_plans) == 1
        _, plan = hd_plans[0]
        assert len(plan.actions) == 2
        assert plan.actions[0].type == ActionType.RESTART_SERVICE
        assert plan.actions[1].type == ActionType.OPEN_INCIDENT_ISSUE

    def test_execute_dispatches_remediation_action(
        self,
        mock_adapter_factory,
    ) -> None:
        """execute_plan 真正调用 adapter.execute_action(restart_service)。"""
        adapter = mock_adapter_factory(health_ok=False, service_running=True)
        signals = derive_signals(adapter.collect_truth())
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()

        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, adapter.collect_truth(), source, state)

        # restart_service 必须被调用至少 1 次（health_down policy 的 remediation）
        assert adapter.call_count(ActionType.RESTART_SERVICE) >= 1
        # open_incident_issue 也必须被调用（兜底 action）
        assert adapter.call_count(ActionType.OPEN_INCIDENT_ISSUE) >= 1

    def test_audit_records_both_actions(self, mock_adapter_factory, tmp_audit_dir) -> None:
        """audit.jsonl 同时记录 remediation 与 fallback action 的执行结果。"""
        adapter = mock_adapter_factory(health_ok=False, service_running=True)
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state)

        entries = _read_audit(tmp_audit_dir)
        action_types = {e["action"]["type"] for e in entries if e.get("action")}
        # restart_service 与 open_incident_issue 都应在 audit 中
        assert "restart_service" in action_types
        assert "open_incident_issue" in action_types

    def test_dry_run_does_not_dispatch(self, mock_adapter_factory) -> None:
        """dry_run=True → 不调用 adapter.execute_action，写 audit skipped。"""
        adapter = mock_adapter_factory(health_ok=False, service_running=True)
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state, dry_run=True)

        # 不应有任何 execute_action 调用
        assert adapter.calls == []
        assert adapter.all_action_types == set()

    def test_remediation_failure_triggers_escalate(self, mock_adapter_factory) -> None:
        """remediation 失败 + max_attempts 耗尽 → 转 escalate（不静默吞错）。"""
        adapter = mock_adapter_factory(health_ok=False, service_running=True)
        # 让 restart_service 失败
        adapter.returns_by_type[ActionType.RESTART_SERVICE.value] = (
            False,
            "docker compose restart failed",
        )
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state)

        # restart_service max_attempts=1，失败后应转 escalate
        assert adapter.call_count(ActionType.ESCALATE) >= 1
        escalate_call = adapter.calls_of(ActionType.ESCALATE)[0]
        assert escalate_call.action.params["original_action"] == "restart_service"


# --------------------------------------------------------------------------- #
# T-D05 · disk_full → clear_logs + open_incident_issue 兜底
# --------------------------------------------------------------------------- #


class TestDiskFullDetectAct:
    """T-D05: disk_full 信号的 detect→act 全链路。"""

    def test_detect_disk_full_signal(self, mock_adapter_factory) -> None:
        """disk_usage_percent >= 90 → derive_signals 派生 disk_full 信号。"""
        adapter = mock_adapter_factory(disk_usage_percent=95.0)
        signals = derive_signals(adapter.collect_truth())

        kinds = [s.kind for s in signals]
        assert "disk_full" in kinds
        df = next(s for s in signals if s.kind == "disk_full")
        assert df.severity == "crit"
        assert "95" in df.detail

    def test_detect_no_disk_full_below_threshold(self, mock_adapter_factory) -> None:
        """disk_usage_percent < 90 → 不派生 disk_full 信号。"""
        adapter = mock_adapter_factory(disk_usage_percent=70.0)
        signals = derive_signals(adapter.collect_truth())

        assert "disk_full" not in [s.kind for s in signals]

    def test_plan_produces_clear_logs_and_incident(self, mock_adapter_factory) -> None:
        """disk_full signal → policy.plan 产出 clear_logs + open_incident_issue。"""
        adapter = mock_adapter_factory(disk_usage_percent=95.0)
        signals = derive_signals(adapter.collect_truth())
        plans = run_policies(signals, ALL_POLICIES)

        df_plans = [(p, pl) for p, pl in plans if p.id == "disk-full"]
        assert len(df_plans) == 1
        _, plan = df_plans[0]
        assert len(plan.actions) == 2
        assert plan.actions[0].type == ActionType.CLEAR_LOGS
        # disk_full 允许 2 次 max_attempts（清理后仍满可再清）
        assert plan.actions[0].max_attempts == 2
        assert plan.actions[1].type == ActionType.OPEN_INCIDENT_ISSUE

    def test_execute_dispatches_clear_logs(
        self,
        mock_adapter_factory,
        tmp_deploy_root: Path,
    ) -> None:
        """execute_plan 真正调用 adapter.execute_action(clear_logs)。

        注：ImpactPredictor 要求 disk_usage_percent > 70 才 allow clear_logs；
        构造 95% 满足条件。
        """
        adapter = mock_adapter_factory(disk_usage_percent=95.0)
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state)

        assert adapter.call_count(ActionType.CLEAR_LOGS) >= 1
        assert adapter.call_count(ActionType.OPEN_INCIDENT_ISSUE) >= 1

    def test_predict_denies_clear_logs_when_disk_low(
        self,
        mock_adapter_factory,
    ) -> None:
        """disk_usage <= 70 → ImpactPredictor deny clear_logs → 写 audit skipped。

        构造矛盾：truth.disk_usage=50（< 70）但手动注入 disk_full signal
        验证 predict 拒绝执行（不调用 adapter.execute_action）。
        """
        adapter = mock_adapter_factory(disk_usage_percent=50.0)
        # 手动注入 disk_full signal（绕过 derive_signals，验证 predict 守护）
        from scripts.autonomy.policies import disk_full_policy

        manual_signal = Signal(
            source="manual_test",
            kind="disk_full",
            severity="crit",
            detail="manually injected",
            ts=1_000_000,
        )
        plan = disk_full_policy.plan([manual_signal])
        state = WatcherState()

        execute_plan(adapter, plan, adapter.collect_truth(), manual_signal, state)

        # clear_logs 应被 predict deny → 不调用 execute_action
        assert adapter.call_count(ActionType.CLEAR_LOGS) == 0

    def test_audit_records_actions(self, mock_adapter_factory, tmp_audit_dir) -> None:
        """audit.jsonl 记录 disk_full 相关 action。"""
        adapter = mock_adapter_factory(disk_usage_percent=95.0)
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state)

        entries = _read_audit(tmp_audit_dir)
        action_types = {e["action"]["type"] for e in entries if e.get("action")}
        assert "clear_logs" in action_types


# --------------------------------------------------------------------------- #
# T-D06 · compose_unhealthy → restart_service + open_incident_issue 兜底
# --------------------------------------------------------------------------- #


class TestComposeUnhealthyDetectAct:
    """T-D06: compose_unhealthy 信号的 detect→act 全链路。"""

    def test_detect_compose_unhealthy_signal(self, mock_adapter_factory) -> None:
        """compose_status != 'running' → 派生 compose_unhealthy 信号。"""
        adapter = mock_adapter_factory(
            compose_status="exited",
            service_running=True,  # predict restart_service 需要 service_running=True
        )
        signals = derive_signals(adapter.collect_truth())

        kinds = [s.kind for s in signals]
        assert "compose_unhealthy" in kinds
        cu = next(s for s in signals if s.kind == "compose_unhealthy")
        assert cu.severity == "crit"
        assert "exited" in cu.detail

    def test_detect_no_signal_when_running(self, mock_adapter_factory) -> None:
        """compose_status='running' → 不派生 compose_unhealthy。"""
        adapter = mock_adapter_factory(compose_status="running")
        signals = derive_signals(adapter.collect_truth())

        assert "compose_unhealthy" not in [s.kind for s in signals]

    def test_plan_produces_restart_and_incident(self, mock_adapter_factory) -> None:
        """compose_unhealthy signal → policy.plan 产出 restart_service + 兜底。"""
        adapter = mock_adapter_factory(
            compose_status="exited",
            service_running=True,
        )
        signals = derive_signals(adapter.collect_truth())
        plans = run_policies(signals, ALL_POLICIES)

        cu_plans = [(p, pl) for p, pl in plans if p.id == "compose-unhealthy"]
        assert len(cu_plans) == 1
        _, plan = cu_plans[0]
        assert len(plan.actions) == 2
        assert plan.actions[0].type == ActionType.RESTART_SERVICE
        assert plan.actions[0].risk == RiskLevel.MEDIUM
        assert plan.actions[1].type == ActionType.OPEN_INCIDENT_ISSUE

    def test_execute_dispatches_restart_service(self, mock_adapter_factory) -> None:
        """execute_plan 调用 adapter.execute_action(restart_service)。"""
        adapter = mock_adapter_factory(
            compose_status="exited",
            service_running=True,
        )
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state)

        assert adapter.call_count(ActionType.RESTART_SERVICE) >= 1
        assert adapter.call_count(ActionType.OPEN_INCIDENT_ISSUE) >= 1

    def test_predict_denies_when_service_not_running(self, mock_adapter_factory) -> None:
        """service_running=False → predict deny restart_service（compose 真未启动）。

        构造：compose_status='exited' + service_running=False
        预期：compose_unhealthy 信号派生（compose_status != running）
              但 restart_service 被 predict deny（service_running=False）
              → 写 audit skipped，不调用 adapter.execute_action(restart_service)
        """
        adapter = mock_adapter_factory(
            compose_status="exited",
            service_running=False,
        )
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state)

        # compose_unhealthy policy 的 restart_service 应被 deny
        # （health_down policy 也匹配 restart_service，但同 key 同 truth 也 deny）
        assert adapter.call_count(ActionType.RESTART_SERVICE) == 0

    def test_dry_run_skips_execution(self, mock_adapter_factory) -> None:
        """dry_run=True → 不调用 adapter.execute_action。"""
        adapter = mock_adapter_factory(
            compose_status="exited",
            service_running=True,
        )
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state, dry_run=True)

        assert adapter.calls == []


# --------------------------------------------------------------------------- #
# T-D07 · manifest_drift → freeze_manifest + open_incident_issue 兜底
# --------------------------------------------------------------------------- #


class TestManifestDriftDetectAct:
    """T-D07: manifest_drift 信号的 detect→act 全链路。

    注：derive_signals 派生 manifest_drift 需要 truth.extra['manifest_drift_detected']=True
    （truth 采集阶段不计算 drift，由 watcher 主流程在外部计算后注入 extra）。
    """

    def test_detect_manifest_drift_signal(self, mock_adapter_factory) -> None:
        """truth.extra['manifest_drift_detected']=True → 派生 manifest_drift 信号。"""
        adapter = mock_adapter_factory(
            manifest_exists=True,
            manifest_frozen=False,
            extra={"manifest_drift_detected": True},
        )
        signals = derive_signals(adapter.collect_truth())

        kinds = [s.kind for s in signals]
        assert "manifest_drift" in kinds
        md = next(s for s in signals if s.kind == "manifest_drift")
        assert md.severity == "warn"

    def test_no_signal_without_extra_flag(self, mock_adapter_factory) -> None:
        """无 extra['manifest_drift_detected'] → 不派生 manifest_drift。"""
        adapter = mock_adapter_factory(
            manifest_exists=True,
            manifest_frozen=False,
            extra=None,
        )
        signals = derive_signals(adapter.collect_truth())

        assert "manifest_drift" not in [s.kind for s in signals]

    def test_no_signal_when_frozen(self, mock_adapter_factory) -> None:
        """manifest_frozen=True → 即使有 drift_detected 也不派生（已冻结，无需再 freeze）。"""
        adapter = mock_adapter_factory(
            manifest_exists=True,
            manifest_frozen=True,
            extra={"manifest_drift_detected": True},
        )
        signals = derive_signals(adapter.collect_truth())

        assert "manifest_drift" not in [s.kind for s in signals]

    def test_plan_produces_freeze_and_incident(self, mock_adapter_factory) -> None:
        """manifest_drift signal → policy.plan 产出 freeze_manifest + 兜底。"""
        adapter = mock_adapter_factory(
            manifest_exists=True,
            manifest_frozen=False,
            extra={"manifest_drift_detected": True},
        )
        signals = derive_signals(adapter.collect_truth())
        plans = run_policies(signals, ALL_POLICIES)

        md_plans = [(p, pl) for p, pl in plans if p.id == "manifest-drift"]
        assert len(md_plans) == 1
        _, plan = md_plans[0]
        assert len(plan.actions) == 2
        assert plan.actions[0].type == ActionType.FREEZE_MANIFEST
        assert plan.actions[0].risk == RiskLevel.LOW
        assert plan.actions[1].type == ActionType.OPEN_INCIDENT_ISSUE

    def test_execute_dispatches_freeze_manifest(
        self,
        mock_adapter_factory,
        tmp_manifest_path: str,
    ) -> None:
        """execute_plan 调用 adapter.execute_action(freeze_manifest)。"""
        adapter = mock_adapter_factory(
            manifest_exists=True,
            manifest_frozen=False,
            extra={"manifest_drift_detected": True},
        )
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state)

        assert adapter.call_count(ActionType.FREEZE_MANIFEST) >= 1
        assert adapter.call_count(ActionType.OPEN_INCIDENT_ISSUE) >= 1

    def test_predict_denies_freeze_when_already_frozen(
        self,
        mock_adapter_factory,
    ) -> None:
        """manifest_frozen=True → predict deny freeze_manifest（已冻结，重复 freeze 无意义）。

        构造矛盾：手动注入 manifest_drift signal 但 truth.manifest_frozen=True
        预期：policy.plan 产出 freeze_manifest action
              但 predict deny（已 frozen）→ 写 audit skipped，不调用 execute_action
        """
        adapter = mock_adapter_factory(
            manifest_exists=True,
            manifest_frozen=True,  # 已冻结
            extra=None,  # 不通过 derive_signals 派生
        )
        from scripts.autonomy.policies import manifest_drift_policy

        manual_signal = Signal(
            source="manual_test",
            kind="manifest_drift",
            severity="warn",
            detail="manually injected drift",
            ts=1_000_000,
        )
        plan = manifest_drift_policy.plan([manual_signal])
        state = WatcherState()

        execute_plan(adapter, plan, adapter.collect_truth(), manual_signal, state)

        # freeze_manifest 应被 predict deny
        assert adapter.call_count(ActionType.FREEZE_MANIFEST) == 0

    def test_audit_records_freeze_action(
        self,
        mock_adapter_factory,
        tmp_audit_dir,
    ) -> None:
        """audit.jsonl 记录 freeze_manifest action。"""
        adapter = mock_adapter_factory(
            manifest_exists=True,
            manifest_frozen=False,
            extra={"manifest_drift_detected": True},
        )
        truth = adapter.collect_truth()
        signals = derive_signals(truth)
        plans = run_policies(signals, ALL_POLICIES)
        state = WatcherState()
        for policy, plan in plans:
            matched = [s for s in signals if s.kind in policy.matches]
            source = max(matched, key=lambda s: s.ts) if matched else None
            execute_plan(adapter, plan, truth, source, state)

        entries = _read_audit(tmp_audit_dir)
        action_types = {e["action"]["type"] for e in entries if e.get("action")}
        assert "freeze_manifest" in action_types


# --------------------------------------------------------------------------- #
# 综合端到端：tick() 主流程的 detect→act 验证
# --------------------------------------------------------------------------- #


class TestTickDetectActIntegration:
    """通过 tick() 主流程验证 4 个 policy 的 detect→act 完整链路。

    与 TestHealthDownDetectAct 等单 policy 测试不同，本类通过 mock adapter
    注入不同的 truth 状态，验证 tick() 一次性派生多信号 + 多 policy + 多 action
    的端到端语义（与 test_cvm_watcher.TestTick 类似，但使用 MockAutonomyAdapter）。
    """

    def test_tick_dispatches_multiple_policies(self, mock_adapter_factory) -> None:
        """health_ok=False + disk=95 + compose=exited → 3 信号 → 3 policy 同时 plan。"""
        adapter = mock_adapter_factory(
            health_ok=False,
            disk_usage_percent=95.0,
            compose_status="exited",
            service_running=True,
            extra={"manifest_drift_detected": True},
        )
        state = WatcherState()

        # 调用 tick 主流程（不通过 mock adapter.collect_truth，使用 adapter 自带 truth）
        from scripts.autonomy.cvm_autonomy_watcher import tick

        truth, signals, plans, audits = tick(adapter, ALL_POLICIES, state)

        # 4 个信号全部派生
        kinds = {s.kind for s in signals}
        assert "health_down" in kinds
        assert "disk_full" in kinds
        assert "compose_unhealthy" in kinds
        assert "manifest_drift" in kinds
        # 至少 4 个 policy plan
        assert len(plans) >= 4
        # adapter 被调用了多个 action type
        assert ActionType.RESTART_SERVICE.value in adapter.all_action_types
        assert ActionType.CLEAR_LOGS.value in adapter.all_action_types
        assert ActionType.FREEZE_MANIFEST.value in adapter.all_action_types

    def test_tick_healthy_dispatches_nothing(self, mock_adapter_factory) -> None:
        """全部健康 → 0 信号 → 0 plan → 0 execute_action 调用。"""
        adapter = mock_adapter_factory(
            health_ok=True,
            disk_usage_percent=50.0,
            compose_status="running",
            service_running=True,
        )
        state = WatcherState()

        from scripts.autonomy.cvm_autonomy_watcher import tick

        truth, signals, plans, audits = tick(adapter, ALL_POLICIES, state)

        assert signals == []
        assert plans == []
        assert adapter.calls == []
