"""tests/test_autonomy/test_cvm_watcher.py — cvm-autonomy-watcher 主程序测试。

覆盖：
  - 主流程（truth → signal → policy → action）
  - dry-run（只决策不执行）
  - truth 采集容错（adapter 抛错 → watcher 抛错 + 写 audit）
  - cooldown 窗口内跳过
  - max_attempts 耗尽 → escalate
  - escalate 写 audit
  - noop 写 audit
  - CLI 参数解析
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts.autonomy.cvm_adapter import CvmAutonomyAdapter, list_audit_entries
from scripts.autonomy.cvm_autonomy_watcher import (
    WatcherState,
    derive_signals,
    execute_plan,
    main,
    parse_args,
    run_policies,
    tick,
)
from scripts.autonomy.policies import ALL_POLICIES
from scripts.autonomy.types import (
    Action,
    ActionType,
    AuditEntry,
    Diagnosis,
    Plan,
    RiskLevel,
    RuntimeTruthSnapshot,
    Signal,
)


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #


def _make_signal(kind: str, ts: int = 1_000_000) -> Signal:
    return Signal(
        source="runtime_truth",
        kind=kind,
        severity="crit",
        detail=f"test {kind}",
        ts=ts,
    )


def _make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------- #
# derive_signals 测试
# --------------------------------------------------------------------------- #


class TestDeriveSignals:
    def test_derive_health_down_when_unhealthy(
        self,
        unhealthy_truth: RuntimeTruthSnapshot,
    ) -> None:
        """truth.health_ok=False → 派生 health_down 信号。"""
        signals = derive_signals(unhealthy_truth)

        kinds = [s.kind for s in signals]
        assert "health_down" in kinds

    def test_derive_disk_full_when_high(
        self,
        unhealthy_truth: RuntimeTruthSnapshot,
    ) -> None:
        """truth.disk_usage_percent >= 90 → 派生 disk_full 信号。"""
        signals = derive_signals(unhealthy_truth)

        kinds = [s.kind for s in signals]
        assert "disk_full" in kinds

    def test_derive_compose_unhealthy_when_not_running(
        self,
        unhealthy_truth: RuntimeTruthSnapshot,
    ) -> None:
        """truth.compose_status != 'running' → 派生 compose_unhealthy 信号。"""
        signals = derive_signals(unhealthy_truth)

        kinds = [s.kind for s in signals]
        assert "compose_unhealthy" in kinds

    def test_derive_no_signals_when_healthy(
        self,
        sample_truth: RuntimeTruthSnapshot,
    ) -> None:
        """truth 健康 → 不派生信号。"""
        signals = derive_signals(sample_truth)

        assert signals == []

    def test_derive_manifest_drift_when_extra_flag(
        self,
        sample_truth: RuntimeTruthSnapshot,
    ) -> None:
        """truth.extra.manifest_drift_detected=True → 派生 manifest_drift 信号。"""
        sample_truth.extra = {"manifest_drift_detected": True}
        signals = derive_signals(sample_truth)

        kinds = [s.kind for s in signals]
        assert "manifest_drift" in kinds

    def test_derive_uses_truth_ts_as_signal_ts(
        self,
        unhealthy_truth: RuntimeTruthSnapshot,
    ) -> None:
        """派生信号的 ts = truth.ts（纯函数，禁止 time.time()）。"""
        signals = derive_signals(unhealthy_truth)

        for s in signals:
            assert s.ts == unhealthy_truth.ts


# --------------------------------------------------------------------------- #
# run_policies 测试
# --------------------------------------------------------------------------- #


class TestRunPolicies:
    def test_empty_signals_returns_empty(self) -> None:
        """空 signals → run_policies 返回空。"""
        assert run_policies([], ALL_POLICIES) == []

    def test_matching_signal_produces_plan(self) -> None:
        """health_down 信号 → 匹配 health_down_policy 产出 plan。"""
        sig = _make_signal("health_down")
        results = run_policies([sig], ALL_POLICIES)

        assert len(results) == 1
        policy, plan = results[0]
        assert policy.id == "health-down"
        assert len(plan.actions) == 1
        assert plan.actions[0].type == ActionType.RESTART_SERVICE

    def test_unmatched_signal_returns_empty(self) -> None:
        """未匹配的 kind → 不产出 plan。"""
        sig = _make_signal("unknown_kind")
        assert run_policies([sig], ALL_POLICIES) == []

    def test_multiple_signals_match_multiple_policies(self) -> None:
        """多信号匹配多 policy → 产出多个 plan。"""
        signals = [
            _make_signal("health_down", ts=1_000_000),
            _make_signal("disk_full", ts=1_000_000),
        ]
        results = run_policies(signals, ALL_POLICIES)

        assert len(results) == 2
        policy_ids = {p.id for p, _ in results}
        assert policy_ids == {"health-down", "disk-full"}


# --------------------------------------------------------------------------- #
# execute_plan 测试
# --------------------------------------------------------------------------- #


class TestExecutePlan:
    def test_dry_run_skips_execution(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        sample_truth: RuntimeTruthSnapshot,
        tmp_audit_dir: Path,
    ) -> None:
        """dry_run=True → 不执行 action，写 audit skipped。"""
        action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": "test"},
            idempotency_key="test:restart",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        plan = Plan(
            diagnosis=Diagnosis(root_cause="test", confidence=0.8, detail="test", evidence=[]),
            actions=[action],
        )
        state = WatcherState()

        audits = execute_plan(
            adapter_for_test, plan, sample_truth, None, state, dry_run=True
        )

        assert len(audits) == 1
        # audit 中 action 应为 skipped
        audit_action = audits[0].action
        assert isinstance(audit_action, dict)
        assert audit_action["type"] == "skipped"
        assert "dry_run" in audit_action["reasons"][0]
        # audit 文件已写入
        entries = list_audit_entries(str(tmp_audit_dir / "audit.jsonl"))
        assert len(entries) == 1
        assert entries[0]["action"]["type"] == "skipped"

    def test_predict_deny_skips_execution(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        sample_truth: RuntimeTruthSnapshot,
        tmp_audit_dir: Path,
    ) -> None:
        """ImpactPredictor deny → 不执行 action，写 audit skipped。

        构造 clear_logs action 但 disk=50%（< 阈值 70），predict 应 deny。
        """
        action = Action(
            type=ActionType.CLEAR_LOGS,
            params={"reason": "test"},
            idempotency_key="test:clear",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )
        plan = Plan(
            diagnosis=Diagnosis(root_cause="test", confidence=0.8, detail="test", evidence=[]),
            actions=[action],
        )
        state = WatcherState()

        audits = execute_plan(
            adapter_for_test, plan, sample_truth, None, state, dry_run=False
        )

        assert len(audits) == 1
        # audit action 应为 skipped（predict deny）
        audit_action = audits[0].action
        assert isinstance(audit_action, dict)
        assert audit_action["type"] == "skipped"

    def test_max_attempts_exhausted_escalates(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        sample_truth: RuntimeTruthSnapshot,
        mock_subprocess_run: MagicMock,
        tmp_audit_dir: Path,
    ) -> None:
        """max_attempts 耗尽 → 转 escalate。

        构造 action max_attempts=1，第 1 次执行失败 → 立即 escalate。
        与桌面端 controller.ts 行为一致：失败 + 耗尽 attempts → escalate(reason=result.detail)
        """
        # 模拟 restart_service 失败
        mock_subprocess_run.return_value = _make_completed(returncode=1, stderr="fail")
        action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": "test"},
            idempotency_key="test:escalate",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        plan = Plan(
            diagnosis=Diagnosis(root_cause="test", confidence=0.8, detail="test", evidence=[]),
            actions=[action],
        )
        state = WatcherState()

        # 第 1 次执行：失败 + 耗尽 → 立即 escalate
        audits = execute_plan(
            adapter_for_test, plan, sample_truth, None, state, dry_run=False
        )

        # 应有 escalate audit（原始 action audit 已通过 adapter.audit 写入）
        escalate_audits = [
            a for a in audits
            if a.action is not None
            and not isinstance(a.action, dict)
            and a.action.type == ActionType.ESCALATE
        ]
        assert len(escalate_audits) >= 1
        # audit 文件应包含 escalate entry
        entries = list_audit_entries(str(tmp_audit_dir / "audit.jsonl"))
        escalate_entries = [e for e in entries if e.get("action", {}).get("type") == "escalate"]
        assert len(escalate_entries) >= 1
        # escalate reason 应包含原始 action 失败 detail（与桌面端 controller.ts 一致）
        reason = escalate_entries[0]["action"]["params"]["reason"]
        assert "docker compose restart failed" in reason or "fail" in reason
        # escalate params 应记录原始 action type
        assert escalate_entries[0]["action"]["params"]["original_action"] == "restart_service"

    def test_noop_action_writes_audit(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        sample_truth: RuntimeTruthSnapshot,
        tmp_audit_dir: Path,
    ) -> None:
        """noop action → 写 audit + result.ok=True。"""
        action = Action(
            type=ActionType.NOOP,
            params={"reason": "test"},
            idempotency_key="test:noop",
            max_attempts=1,
            risk=RiskLevel.LOW,
        )
        plan = Plan(
            diagnosis=Diagnosis(root_cause="test", confidence=0.8, detail="test", evidence=[]),
            actions=[action],
        )
        state = WatcherState()

        audits = execute_plan(
            adapter_for_test, plan, sample_truth, None, state, dry_run=False
        )

        assert len(audits) == 1
        assert audits[0].result is not None
        assert audits[0].result.ok is True
        # audit 文件已写入
        entries = list_audit_entries(str(tmp_audit_dir / "audit.jsonl"))
        assert len(entries) == 1
        assert entries[0]["action"]["type"] == "noop"

    def test_escalate_action_writes_audit(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        sample_truth: RuntimeTruthSnapshot,
        tmp_audit_dir: Path,
    ) -> None:
        """escalate action → 写 audit + result.ok=True。"""
        action = Action(
            type=ActionType.ESCALATE,
            params={"reason": "manual"},
            idempotency_key="test:escalate_direct",
            max_attempts=1,
            risk=RiskLevel.HIGH,
        )
        plan = Plan(
            diagnosis=Diagnosis(root_cause="test", confidence=0.8, detail="test", evidence=[]),
            actions=[action],
        )
        state = WatcherState()

        audits = execute_plan(
            adapter_for_test, plan, sample_truth, None, state, dry_run=False
        )

        assert len(audits) == 1
        assert audits[0].result is not None
        assert audits[0].result.ok is True
        entries = list_audit_entries(str(tmp_audit_dir / "audit.jsonl"))
        assert len(entries) == 1
        assert entries[0]["action"]["type"] == "escalate"


# --------------------------------------------------------------------------- #
# tick 主流程测试
# --------------------------------------------------------------------------- #


class TestTick:
    def test_tick_healthy_no_signals(
        self,
        healthy_adapter: CvmAutonomyAdapter,
    ) -> None:
        """健康 truth → 不派生信号 → 不产出 plan → 不执行 action。"""
        state = WatcherState()

        truth, signals, plans, audits = tick(healthy_adapter, ALL_POLICIES, state)

        assert truth.health_ok is True
        assert signals == []
        assert plans == []
        assert audits == []

    def test_tick_unhealthy_triggers_restart(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        mock_subprocess_run: MagicMock,
        tmp_deploy_root: Path,
    ) -> None:
        """不健康 truth → health_down + compose_unhealthy 信号 → restart_service 执行。"""
        adapter_for_test._health_probe = lambda url: False
        adapter_for_test._compose_status_probe = lambda root: ("exited", False)
        # service_running=False 时 predict 会 deny restart_service；
        # 改为 compose exited 但 service_running=True 模拟"服务在但 compose 报 exited"
        # 实际上 compose_status_probe 返回的 service_running 决定 truth.service_running
        # 我们让 probe 返回 service_running=True 但 compose_status='exited' 来触发 policy
        adapter_for_test._compose_status_probe = lambda root: ("exited", True)
        # restart_service 的 predict 要求 service_running=True，故这里设 True
        mock_subprocess_run.return_value = _make_completed(returncode=0, stdout="ok")
        state = WatcherState()

        truth, signals, plans, audits = tick(adapter_for_test, ALL_POLICIES, state)

        # 派生 health_down + compose_unhealthy 两个信号
        kinds = {s.kind for s in signals}
        assert "health_down" in kinds
        assert "compose_unhealthy" in kinds
        # 匹配 2 个 policy（health_down + compose_unhealthy），各产出 1 个 action
        assert len(plans) == 2
        # 至少 2 个 audit（每 plan 1 个 action）
        assert len(audits) >= 2

    def test_tick_truth_collect_failure_raises(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_audit_dir: Path,
    ) -> None:
        """truth 采集失败 → tick 抛错 + 写 audit。"""
        def _fail_collect() -> RuntimeTruthSnapshot:
            raise RuntimeError("docker unavailable")

        adapter_for_test.collect_truth = _fail_collect  # type: ignore[method-assign]
        state = WatcherState()

        with pytest.raises(RuntimeError, match="docker unavailable"):
            tick(adapter_for_test, ALL_POLICIES, state)

        # audit 应记录 truth_collect_failed
        entries = list_audit_entries(str(tmp_audit_dir / "audit.jsonl"))
        assert len(entries) == 1
        assert entries[0]["diagnosis"]["root_cause"] == "truth_collect_failed"

    def test_tick_dry_run_no_execution(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """dry_run=True → 即使不健康也不执行 action（仅写 audit skipped）。"""
        adapter_for_test._health_probe = lambda url: False
        adapter_for_test._compose_status_probe = lambda root: ("exited", True)
        state = WatcherState()

        truth, signals, plans, audits = tick(
            adapter_for_test, ALL_POLICIES, state, dry_run=True
        )

        # 派生信号 + 匹配 policy
        assert len(signals) > 0
        assert len(plans) > 0
        # 所有 audit 都是 skipped
        for audit in audits:
            assert isinstance(audit.action, dict)
            assert audit.action["type"] == "skipped"
        # dry_run 时不调用 docker compose restart / find 等动作命令
        # （df 在 truth 采集阶段会被调用，属正常；此处只验证无 action 命令）
        for call in mock_subprocess_run.call_args_list:
            cmd = call[0][0] if call[0] else []
            # 不应有 docker compose restart / find -mtime / bash fhd-apply-release.sh
            cmd_str = " ".join(cmd)
            assert "docker compose restart" not in cmd_str
            assert "fhd-apply-release.sh" not in cmd_str
            assert "-mtime" not in cmd_str


# --------------------------------------------------------------------------- #
# WatcherState cooldown 测试
# --------------------------------------------------------------------------- #


class TestWatcherStateCooldown:
    def test_get_tracker_creates_new(
        self,
    ) -> None:
        """get_tracker: 首次调用创建新 tracker。"""
        state = WatcherState()

        tracker = state.get_tracker("test:key")

        assert tracker.idempotency_key == "test:key"
        assert tracker.attempts == 0
        assert tracker.escalated is False

    def test_get_tracker_returns_existing(
        self,
    ) -> None:
        """get_tracker: 第二次调用返回同一 tracker。"""
        state = WatcherState()

        t1 = state.get_tracker("test:key")
        t1.attempts = 5
        t2 = state.get_tracker("test:key")

        assert t1 is t2
        assert t2.attempts == 5

    def test_default_cooldown_ms(self) -> None:
        """默认 cooldown = 5 分钟。"""
        state = WatcherState()
        assert state.default_cooldown_ms == 5 * 60 * 1000


# --------------------------------------------------------------------------- #
# CLI 参数解析测试
# --------------------------------------------------------------------------- #


class TestCli:
    def test_parse_args_defaults(self) -> None:
        """无参数 → 默认值。"""
        args = parse_args([])

        assert args.dry_run is False
        assert args.deploy_root == "/opt/fhd-full"
        assert args.manifest_path == "/var/www/update/releases/stable/server/fhd-manifest.json"

    def test_parse_args_dry_run(self) -> None:
        """--dry-run → dry_run=True。"""
        args = parse_args(["--dry-run"])

        assert args.dry_run is True

    def test_parse_args_custom_paths(self) -> None:
        """--deploy-root / --manifest-path / --audit-dir 自定义。"""
        args = parse_args([
            "--deploy-root", "/custom/deploy",
            "--manifest-path", "/custom/manifest.json",
            "--audit-dir", "/custom/audit",
        ])

        assert args.deploy_root == "/custom/deploy"
        assert args.manifest_path == "/custom/manifest.json"
        assert args.audit_dir == "/custom/audit"

    def test_main_returns_0_on_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """main(): 健康 truth → 退出码 0。"""
        # 构造临时 deploy root
        deploy_root = tmp_path / "deploy"
        deploy_root.mkdir()
        (deploy_root / "compose.yml").write_text("version: '3'\n")
        audit_dir = tmp_path / "audit"
        manifest_dir = deploy_root / "releases" / "stable" / "server"
        manifest_dir.mkdir(parents=True)
        manifest_path = manifest_dir / "fhd-manifest.json"
        manifest_path.write_text("{}")

        # mock adapter 的 health/compose probe
        from scripts.autonomy import cvm_autonomy_watcher as watcher_mod

        original_init = watcher_mod.CvmAutonomyAdapter.__init__

        def _patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self._health_probe = lambda url: True
            self._compose_status_probe = lambda root: ("running", True)

        monkeypatch.setattr(watcher_mod.CvmAutonomyAdapter, "__init__", _patched_init)

        exit_code = main([
            "--deploy-root", str(deploy_root),
            "--manifest-path", str(manifest_path),
            "--audit-dir", str(audit_dir),
        ])

        assert exit_code == 0

    def test_main_returns_1_on_truth_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """main(): truth 采集抛错 → 退出码 1。"""
        from scripts.autonomy import cvm_autonomy_watcher as watcher_mod

        def _fail_collect(self):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(watcher_mod.CvmAutonomyAdapter, "collect_truth", _fail_collect)

        exit_code = main([
            "--deploy-root", str(tmp_path),
            "--manifest-path", str(tmp_path / "manifest.json"),
            "--audit-dir", str(tmp_path / "audit"),
        ])

        assert exit_code == 1
