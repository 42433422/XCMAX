"""tests/test_autonomy/test_impact_predictor_escalate.py — T-D08 escalate 路径测试。

验证「高影响必须 escalate，不得静默执行」语义：

  1.escalate / noop / open_incident_issue：predict 始终 allow（不被 predict 误杀）
  2. HIGH risk remediation 失败 + max_attempts 耗尽 → 必转 escalate，audit 有 escalate entry
  3. predict deny 的 remediation action → 写 audit skipped，不执行；但兜底 open_incident_issue
     必须仍然执行（不被静默吞掉）
  4. escalate 自身失败 → 写 audit error，不再递归 escalate（避免无限循环）
  5. _escalate() 构造的 escalate_action 字段结构：original_action / reason / diagnosis_root_cause

参考：FHD/scripts/autonomy/impact_predictor.py + cvm_autonomy_watcher._escalate()。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts.autonomy.cvm_autonomy_watcher import (
    WatcherState,
    execute_plan,
)
from scripts.autonomy.impact_predictor import predict
from scripts.autonomy.policies import (
    disk_full_policy,
    health_down_policy,
)
from scripts.autonomy.types import (
    Action,
    ActionType,
    AuditEntry,
    Diagnosis,
    RiskLevel,
    RuntimeTruthSnapshot,
    Signal,
)

# --------------------------------------------------------------------------- #
# 复用 MockAutonomyAdapter（与 test_policies_detect_act.py 同实现，独立定义避免循环依赖）
# --------------------------------------------------------------------------- #


@dataclass
class _RecordedCall:
    action: Action
    return_ok: bool
    return_detail: str


class MockAutonomyAdapter:
    """轻量 AutonomyAdapter，记录所有 execute_action 调用。"""

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
        self.calls: list[_RecordedCall] = []
        self.calls_by_type: dict[str, list[_RecordedCall]] = {}
        self.returns_by_type: dict[str, tuple[bool, str]] = {}

    def collect_truth(self) -> RuntimeTruthSnapshot:
        return self._truth

    def subscribe_signals(self, emit: Any) -> None:
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
        def _serialize(obj: Any) -> Any:
            if isinstance(obj, ActionType):
                return obj.value
            if isinstance(obj, RiskLevel):
                return obj.value
            if isinstance(obj, (Action, Signal, Diagnosis, RuntimeTruthSnapshot, AuditEntry)):
                return {k: _serialize(v) for k, v in asdict(obj).items()}
            if isinstance(obj, dict):
                return {k: _serialize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_serialize(x) for x in obj]
            return obj

        line = json.dumps(_serialize(entry), ensure_ascii=False, default=str)
        with self._audit_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def calls_of(self, action_type: ActionType) -> list[_RecordedCall]:
        return self.calls_by_type.get(action_type.value, [])

    def call_count(self, action_type: ActionType) -> int:
        return len(self.calls_of(action_type))

    @property
    def all_action_types(self) -> set[str]:
        return set(self.calls_by_type.keys())


# --------------------------------------------------------------------------- #
# 共享工具
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
    pending_rollback_marker: bool = False,
    last_backup_ts: int | None = 999_000,
    extra: dict[str, Any] | None = None,
) -> RuntimeTruthSnapshot:
    return RuntimeTruthSnapshot(
        ts=1_000_000,
        deploy_root=str(tmp_deploy_root),
        manifest_path=tmp_manifest_path,
        compose_status=compose_status,
        health_ok=health_ok,
        service_running=service_running,
        pending_rollback_marker=pending_rollback_marker,
        disk_usage_percent=disk_usage_percent,
        config_fingerprint_changed=False,
        last_backup_ts=last_backup_ts,
        app_version="10.0.0",
        build_sha="abc123",
        restart_count=0,
        manifest_exists=manifest_exists,
        manifest_frozen=manifest_frozen,
        extra=extra,
    )


def _read_audit(tmp_audit_dir: Path) -> list[dict]:
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


def _make_signal(kind: str = "health_down", severity: str = "crit") -> Signal:
    return Signal(
        source="runtime_truth",
        kind=kind,
        severity=severity,  # type: ignore[arg-type]
        detail="test signal",
        ts=1_000_000,
    )


# --------------------------------------------------------------------------- #
# T-D08 · escalate 路径测试
# --------------------------------------------------------------------------- #


class TestEscalatePredictAlwaysAllow:
    """escalate / noop / open_incident_issue：predict 始终 allow（不被 predict 误杀）。

    这三个 action 是守护链的兜底通道，必须始终 allow，否则守护链会死锁
    （remediation 失败 → 转 escalate → escalate 也被 predict deny → 静默吞错）。
    """

    def test_escalate_always_allow_even_all_truth_bad(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """所有 truth 状态都坏 → escalate 仍 allow。"""
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            health_ok=False,
            service_running=False,
            compose_status="exited",
            manifest_exists=False,
            manifest_frozen=True,
            pending_rollback_marker=True,
            disk_usage_percent=99.0,
        )
        action = Action(
            type=ActionType.ESCALATE,
            params={"original_action": "rollback_to_last_tarball", "reason": "test"},
            idempotency_key="escalate:test",
            max_attempts=1,
            risk=RiskLevel.HIGH,
        )

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []

    def test_open_incident_issue_always_allow(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """open_incident_issue 始终 allow（避免兜底通道被 predict 误杀）。"""
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            health_ok=False,
            service_running=False,
            manifest_frozen=True,
            pending_rollback_marker=True,
            disk_usage_percent=99.0,
        )
        action = Action(
            type=ActionType.OPEN_INCIDENT_ISSUE,
            params={"incident_type": "test"},
            idempotency_key="open_incident_issue:test",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []

    def test_noop_always_allow(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """noop 始终 allow。"""
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path)
        action = Action(
            type=ActionType.NOOP,
            params={},
            idempotency_key="noop:test",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []


class TestRemediationFailureTriggersEscalate:
    """remediation 失败 + max_attempts 耗尽 → 必转 escalate（不静默吞错）。"""

    def test_health_down_restart_failure_triggers_escalate(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
        tmp_audit_dir: Path,
    ) -> None:
        """health_down policy: restart_service 失败 → 转 escalate。"""
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            health_ok=False,
            service_running=True,
        )
        adapter = MockAutonomyAdapter(truth=truth, audit_path=tmp_audit_dir / "audit.jsonl")
        # restart_service 失败
        adapter.returns_by_type[ActionType.RESTART_SERVICE.value] = (
            False,
            "docker compose restart failed",
        )

        signal = _make_signal("health_down")
        plan = health_down_policy.plan([signal])
        state = WatcherState()

        execute_plan(adapter, plan, truth, signal, state)

        # escalate 必须被调用至少 1 次
        assert adapter.call_count(ActionType.ESCALATE) >= 1
        escalate_action = adapter.calls_of(ActionType.ESCALATE)[0].action
        # escalate action 字段结构验证
        assert escalate_action.type == ActionType.ESCALATE
        assert escalate_action.risk == RiskLevel.HIGH
        assert escalate_action.params["original_action"] == "restart_service"
        assert "docker compose restart failed" in escalate_action.params["reason"]

    def test_disk_full_clear_logs_exhausts_max_attempts(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
        tmp_audit_dir: Path,
    ) -> None:
        """disk_full policy: clear_logs max_attempts=2，同一 watcher state 内连续 2 次失败 → 转 escalate。

        守护链（cvm_autonomy_watcher._try_execute_single）：
          - 第 1 次 execute_plan: tracker.attempts=0 → 1，失败但 < max_attempts=2，不 escalate
          - 第 2 次 execute_plan（同 state）: tracker.attempts=1 → 2，失败且 >= max_attempts=2 → escalate
        """
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            disk_usage_percent=95.0,
        )
        adapter = MockAutonomyAdapter(truth=truth, audit_path=tmp_audit_dir / "audit.jsonl")
        # clear_logs 失败
        adapter.returns_by_type[ActionType.CLEAR_LOGS.value] = (False, "rm logs failed")

        signal = _make_signal("disk_full")
        plan = disk_full_policy.plan([signal])
        # 同一 state 跨 2 次 execute_plan（模拟 watcher 多次 tick）
        state = WatcherState()

        # 第 1 次：attempts 0→1，失败但不耗尽
        execute_plan(adapter, plan, truth, signal, state)
        assert adapter.call_count(ActionType.CLEAR_LOGS) == 1
        # 此时不应有 clear_logs 的 escalate（attempts=1 < 2）
        # （open_incident_issue 兜底可能也调用了，但 risk=LOW + max_attempts=1 失败时也会 escalate）

        # 第 2 次：attempts 1→2，失败且耗尽 → 转 escalate
        execute_plan(adapter, plan, truth, signal, state)

        # 验证 clear_logs 被调用 2 次
        assert adapter.call_count(ActionType.CLEAR_LOGS) == 2
        # 至少 1 次 escalate 来自 clear_logs 耗尽
        escalate_calls = adapter.calls_of(ActionType.ESCALATE)
        clear_logs_escalates = [
            c for c in escalate_calls
            if c.action.params.get("original_action") == "clear_logs"
        ]
        assert len(clear_logs_escalates) >= 1


class TestEscalateActionStructure:
    """_escalate() 构造的 escalate action 字段结构验证。"""

    def test_escalate_action_carries_original_action_and_reason(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
        tmp_audit_dir: Path,
    ) -> None:
        """escalate action 必须带 original_action / reason / diagnosis_root_cause 字段。"""
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            health_ok=False,
            service_running=True,
        )
        adapter = MockAutonomyAdapter(truth=truth, audit_path=tmp_audit_dir / "audit.jsonl")
        adapter.returns_by_type[ActionType.RESTART_SERVICE.value] = (False, "exec failed")

        signal = _make_signal("health_down")
        plan = health_down_policy.plan([signal])
        state = WatcherState()

        execute_plan(adapter, plan, truth, signal, state)

        escalate_action = adapter.calls_of(ActionType.ESCALATE)[0].action
        assert escalate_action.type == ActionType.ESCALATE
        assert escalate_action.risk == RiskLevel.HIGH
        assert escalate_action.max_attempts == 1
        # 字段完整性
        assert "original_action" in escalate_action.params
        assert "reason" in escalate_action.params
        assert "diagnosis_root_cause" in escalate_action.params
        # idempotency_key 必须基于 original_action 的 key（避免不同 remediation 的 escalate 冲突）
        assert escalate_action.idempotency_key.startswith("escalate:")

    def test_escalate_audit_recorded(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
        tmp_audit_dir: Path,
    ) -> None:
        """escalate 必须写 audit entry（不静默吞错）。"""
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            health_ok=False,
            service_running=True,
        )
        adapter = MockAutonomyAdapter(truth=truth, audit_path=tmp_audit_dir / "audit.jsonl")
        adapter.returns_by_type[ActionType.RESTART_SERVICE.value] = (False, "fail")

        signal = _make_signal("health_down")
        plan = health_down_policy.plan([signal])
        state = WatcherState()

        execute_plan(adapter, plan, truth, signal, state)

        entries = _read_audit(tmp_audit_dir)
        # 至少有 1 条 escalate 类的 audit entry
        escalate_entries = [e for e in entries if e.get("action", {}).get("type") == "escalate"]
        assert len(escalate_entries) >= 1
        # escalate audit 必须带 result（不静默）
        assert escalate_entries[0]["result"] is not None
        # escalate audit 必须带 source_signal（追溯到触发信号）
        assert escalate_entries[0]["source_signal"] is not None
        assert escalate_entries[0]["source_signal"]["kind"] == "health_down"


class TestPredictDenyDoesNotSilentlySwallow:
    """predict deny 的 remediation → 写 audit skipped，不执行；但兜底 open_incident_issue 必须执行。"""

    def test_predict_deny_writes_skipped_audit(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
        tmp_audit_dir: Path,
    ) -> None:
        """predict deny 的 action 必须写 audit skipped（不能静默跳过）。"""
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            disk_usage_percent=50.0,  # <= 70，predict 会 deny clear_logs
        )
        adapter = MockAutonomyAdapter(truth=truth, audit_path=tmp_audit_dir / "audit.jsonl")

        # 手动注入 disk_full signal 绕过 derive_signals
        signal = _make_signal("disk_full")
        plan = disk_full_policy.plan([signal])
        state = WatcherState()

        execute_plan(adapter, plan, truth, signal, state)

        entries = _read_audit(tmp_audit_dir)
        # 至少有 1 条 skipped audit（clear_logs 被 predict deny）
        skipped_entries = [
            e for e in entries
            if isinstance(e.get("action"), dict) and e["action"].get("type") == "skipped"
        ]
        assert len(skipped_entries) >= 1
        # skipped audit 必须带 reasons（解释为什么跳过）
        assert len(skipped_entries[0]["action"].get("reasons", [])) > 0

    def test_predict_deny_does_not_swallow_fallback_action(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
        tmp_audit_dir: Path,
    ) -> None:
        """predict deny remediation 时，兜底 open_incident_issue 必须仍执行。

        设计意图：clear_logs 被 predict deny → 写 audit skipped；
        但 plan 中的 open_incident_issue 必须仍执行（不被 predict 误杀），
        保证「问题被记录到 GitHub issue」，不静默丢失。
        """
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            disk_usage_percent=50.0,  # clear_logs 被 predict deny
        )
        adapter = MockAutonomyAdapter(truth=truth, audit_path=tmp_audit_dir / "audit.jsonl")

        signal = _make_signal("disk_full")
        plan = disk_full_policy.plan([signal])
        state = WatcherState()

        execute_plan(adapter, plan, truth, signal, state)

        # clear_logs 应被 predict deny（不执行）
        assert adapter.call_count(ActionType.CLEAR_LOGS) == 0
        # 但 open_incident_issue 必须执行（不被静默吞）
        assert adapter.call_count(ActionType.OPEN_INCIDENT_ISSUE) >= 1


class TestEscalateFailureNoRecursiveEscalate:
    """escalate 自身失败 → 写 audit error，不再递归 escalate（避免无限循环）。"""

    def test_escalate_failure_writes_audit_and_stops(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
        tmp_audit_dir: Path,
    ) -> None:
        """escalate 失败 → 写 audit，不再递归 escalate。"""
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            health_ok=False,
            service_running=True,
        )
        adapter = MockAutonomyAdapter(truth=truth, audit_path=tmp_audit_dir / "audit.jsonl")
        # restart_service 失败 → 触发 escalate
        adapter.returns_by_type[ActionType.RESTART_SERVICE.value] = (False, "restart fail")
        # escalate 自身也失败
        adapter.returns_by_type[ActionType.ESCALATE.value] = (False, "gh issue create fail")

        signal = _make_signal("health_down")
        plan = health_down_policy.plan([signal])
        state = WatcherState()

        execute_plan(adapter, plan, truth, signal, state)

        # escalate 只被调用 1 次（不递归）
        assert adapter.call_count(ActionType.ESCALATE) == 1
        # escalate 失败 → 不再触发新 escalate（无 escalate-of-escalate）
        # 注：_escalate 内部 try/except，失败时构造 error_result 但不再递归调用 _escalate
        # 验证：audit 中只有 1 条 escalate entry
        entries = _read_audit(tmp_audit_dir)
        escalate_entries = [e for e in entries if e.get("action", {}).get("type") == "escalate"]
        assert len(escalate_entries) == 1
        # 该 escalate entry 的 result.ok 应为 False
        assert escalate_entries[0]["result"]["ok"] is False
        assert "gh issue create fail" in escalate_entries[0]["result"]["detail"]
