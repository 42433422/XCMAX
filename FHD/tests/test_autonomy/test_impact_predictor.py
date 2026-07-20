"""tests/test_autonomy/test_impact_predictor.py — ImpactPredictor 单元测试。

覆盖 7 个 action 的预检边界（allow / deny）：
  - restart_service: compose 不存在 / service_running=False → deny
  - rollback_to_last_tarball: 无 tarball / 有 pending marker → deny
  - freeze_manifest: 已 frozen / 不存在 → deny
  - clear_logs: 磁盘不足 / 无 logs 目录 → deny
  - escalate: 始终 allow
  - noop: 始终 allow
  - open_incident_issue: 始终 allow（token / 去重 / 前置 action 失败判定由 adapter 内守护）
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.autonomy.impact_predictor import (
    DISK_CLEAN_THRESHOLD,
    batch_predict,
    predict,
    should_skip,
)
from scripts.autonomy.types import Action, ActionType, Prediction, RiskLevel, RuntimeTruthSnapshot

# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #


def _make_action(action_type: ActionType) -> Action:
    return Action(
        type=action_type,
        params={"reason": "test"},
        idempotency_key=f"test:{action_type.value}",
        max_attempts=1,
        risk=RiskLevel.LOW,
    )


def _make_truth(
    tmp_deploy_root: Path,
    tmp_manifest_path: str,
    *,
    compose_status: str = "running",
    health_ok: bool = True,
    service_running: bool = True,
    pending_rollback_marker: bool = False,
    disk_usage_percent: float = 50.0,
    last_backup_ts: int | None = 999_000,
    manifest_exists: bool = True,
    manifest_frozen: bool = False,
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
        build_sha="abc",
        restart_count=0,
        manifest_exists=manifest_exists,
        manifest_frozen=manifest_frozen,
    )


# --------------------------------------------------------------------------- #
# restart_service 预检
# --------------------------------------------------------------------------- #


class TestPredictRestartService:
    def test_allow_when_compose_and_service_running(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """restart_service: compose 存在 + service_running=True → allow。"""
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, service_running=True)
        action = _make_action(ActionType.RESTART_SERVICE)

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []

    def test_deny_when_no_compose_file(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """restart_service: compose.yml 不存在 → deny。"""
        (tmp_deploy_root / "compose.yml").unlink()
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path)
        action = _make_action(ActionType.RESTART_SERVICE)

        prediction = predict(action, truth)

        assert prediction.allow is False
        assert any("compose.yml 不存在" in r for r in prediction.reasons)

    def test_deny_when_service_not_running(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """restart_service: service_running=False → deny。"""
        truth = _make_truth(
            tmp_deploy_root, tmp_manifest_path, service_running=False, compose_status="exited"
        )
        action = _make_action(ActionType.RESTART_SERVICE)

        prediction = predict(action, truth)

        assert prediction.allow is False
        assert any("service_running=False" in r for r in prediction.reasons)


# --------------------------------------------------------------------------- #
# rollback_to_last_tarball 预检
# --------------------------------------------------------------------------- #


class TestPredictRollback:
    def test_allow_when_tarball_exists_and_no_marker(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """rollback: .deploy-last.tar.gz 存在 + 无 marker → allow。"""
        (tmp_deploy_root / ".deploy-last.tar.gz").write_bytes(b"fake")
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, pending_rollback_marker=False)
        action = _make_action(ActionType.ROLLBACK_TO_LAST_TARBALL)

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []

    def test_deny_when_no_tarball(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """rollback: .deploy-last.tar.gz 不存在 → deny。"""
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path)
        action = _make_action(ActionType.ROLLBACK_TO_LAST_TARBALL)

        prediction = predict(action, truth)

        assert prediction.allow is False
        assert any("无 .deploy-last.tar.gz" in r for r in prediction.reasons)

    def test_deny_when_pending_marker(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """rollback: pending_rollback_marker=True → deny（嵌套回滚）。"""
        (tmp_deploy_root / ".deploy-last.tar.gz").write_bytes(b"fake")
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, pending_rollback_marker=True)
        action = _make_action(ActionType.ROLLBACK_TO_LAST_TARBALL)

        prediction = predict(action, truth)

        assert prediction.allow is False
        assert any("pending rollback marker" in r for r in prediction.reasons)

    def test_deny_when_backup_too_old(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """rollback: last_backup_ts 超过 7 天 → deny。"""
        (tmp_deploy_root / ".deploy-last.tar.gz").write_bytes(b"fake")
        # ts=1_000_000, 7 天前 = 1_000_000 - 7*24*3600*1000 = 395_200_000
        truth = _make_truth(
            tmp_deploy_root, tmp_manifest_path, last_backup_ts=1_000_000 - 8 * 24 * 3600 * 1000
        )
        action = _make_action(ActionType.ROLLBACK_TO_LAST_TARBALL)

        prediction = predict(action, truth)

        assert prediction.allow is False
        assert any("备份超过 7 天" in r for r in prediction.reasons)


# --------------------------------------------------------------------------- #
# freeze_manifest 预检
# --------------------------------------------------------------------------- #


class TestPredictFreezeManifest:
    def test_allow_when_manifest_exists_and_not_frozen(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """freeze_manifest: manifest 存在 + 未 frozen → allow。"""
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, manifest_frozen=False)
        action = _make_action(ActionType.FREEZE_MANIFEST)

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []

    def test_deny_when_manifest_frozen(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """freeze_manifest: manifest_frozen=True → deny。"""
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, manifest_frozen=True)
        action = _make_action(ActionType.FREEZE_MANIFEST)

        prediction = predict(action, truth)

        assert prediction.allow is False
        assert any("已 frozen" in r for r in prediction.reasons)

    def test_deny_when_manifest_not_exists(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """freeze_manifest: manifest_exists=False → deny。"""
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, manifest_exists=False)
        action = _make_action(ActionType.FREEZE_MANIFEST)

        prediction = predict(action, truth)

        assert prediction.allow is False
        assert any("manifest 不存在" in r for r in prediction.reasons)


# --------------------------------------------------------------------------- #
# clear_logs 预检
# --------------------------------------------------------------------------- #


class TestPredictClearLogs:
    def test_allow_when_disk_high_and_logs_exists(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """clear_logs: disk > 70 + logs 目录存在 → allow。"""
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, disk_usage_percent=85.0)
        action = _make_action(ActionType.CLEAR_LOGS)

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []

    def test_deny_when_disk_below_threshold(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """clear_logs: disk <= 70 → deny（与桌面端 <= 边界一致）。"""
        truth = _make_truth(
            tmp_deploy_root, tmp_manifest_path, disk_usage_percent=float(DISK_CLEAN_THRESHOLD)
        )
        action = _make_action(ActionType.CLEAR_LOGS)

        prediction = predict(action, truth)

        assert prediction.allow is False
        assert any("<= 阈值" in r for r in prediction.reasons)

    def test_deny_when_no_logs_dir(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """clear_logs: logs 目录不存在 → deny。"""
        import shutil

        shutil.rmtree(tmp_deploy_root / "logs")
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, disk_usage_percent=95.0)
        action = _make_action(ActionType.CLEAR_LOGS)

        prediction = predict(action, truth)

        assert prediction.allow is False
        assert any("logs 目录不存在" in r for r in prediction.reasons)


# --------------------------------------------------------------------------- #
# escalate / noop / open_incident_issue 预检
# --------------------------------------------------------------------------- #


class TestPredictEscalateNoopIncident:
    def test_escalate_always_allow(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """escalate 始终 allow（即使所有 truth 状态都坏）。"""
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
        action = _make_action(ActionType.ESCALATE)

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []

    def test_noop_always_allow(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """noop 始终 allow。"""
        truth = _make_truth(
            tmp_deploy_root,
            tmp_manifest_path,
            health_ok=False,
            service_running=False,
        )
        action = _make_action(ActionType.NOOP)

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []

    def test_open_incident_issue_always_allow(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """open_incident_issue 始终 allow（即使所有 truth 状态都坏）。

        设计：token / 24h 去重 / 前置 action 失败判定由 adapter._action_open_incident_issue
        内守护，避免 predict 与 action 双重 GitHub API 调用。
        """
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
        action = _make_action(ActionType.OPEN_INCIDENT_ISSUE)

        prediction = predict(action, truth)

        assert prediction.allow is True
        assert prediction.reasons == []


# --------------------------------------------------------------------------- #
# 辅助函数
# --------------------------------------------------------------------------- #


class TestHelpers:
    def test_batch_predict_returns_list(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """batch_predict: 返回与 actions 等长的 Prediction 列表。"""
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path)
        actions = [
            _make_action(ActionType.NOOP),
            _make_action(ActionType.ESCALATE),
            _make_action(ActionType.CLEAR_LOGS),
        ]

        predictions = batch_predict(actions, truth)

        assert len(predictions) == 3
        assert all(isinstance(p, Prediction) for p in predictions)

    def test_should_skip_returns_tuple(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """should_skip: 返回 (skip, reasons) 元组。"""
        truth = _make_truth(tmp_deploy_root, tmp_manifest_path, disk_usage_percent=50.0)
        action = _make_action(ActionType.CLEAR_LOGS)

        skip, reasons = should_skip(action, truth)

        assert skip is True
        assert len(reasons) > 0
