"""tests/test_autonomy/test_cvm_adapter.py — CvmAutonomyAdapter 单元测试。

覆盖：
  - 6 个 action 的成功路径（restart_service / rollback_to_last_tarball /
    freeze_manifest / clear_logs / escalate / noop）
  - 6 个 action 的失败路径（无 compose.yml / 无 .deploy-last.tarball / 无 manifest /
    无 logs 目录 / subprocess 超时 / 命令失败）
  - collect_truth 容错（docker 不可用 / df 失败 / manifest 不存在）
  - audit 写入与读取
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts.autonomy.cvm_adapter import (
    DEFAULT_DEPLOY_ROOT,
    DEFAULT_HEALTH_URL,
    DEFAULT_MANIFEST_PATH,
    CvmAutonomyAdapter,
    list_audit_entries,
)
from scripts.autonomy.types import Action, ActionType, AuditEntry, Diagnosis, RiskLevel

# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #


def _make_action(
    action_type: ActionType,
    risk: RiskLevel = RiskLevel.LOW,
    max_attempts: int = 1,
) -> Action:
    """构造测试用 Action。"""
    return Action(
        type=action_type,
        params={"reason": "test"},
        idempotency_key=f"test:{action_type.value}",
        max_attempts=max_attempts,
        risk=risk,
    )


def _make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    """构造 CompletedProcess。"""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


# --------------------------------------------------------------------------- #
# 6 个 action 成功路径
# --------------------------------------------------------------------------- #


class TestRestartServiceSuccess:
    def test_restart_service_compose_yml_exists(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """restart_service 成功：compose.yml 存在 + docker compose restart 返回 0。"""
        mock_subprocess_run.return_value = _make_completed(returncode=0, stdout="Restarting")
        action = _make_action(ActionType.RESTART_SERVICE, risk=RiskLevel.MEDIUM)

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "docker compose restart ok" in result.detail
        assert "compose.yml" in result.detail
        # 验证 subprocess.run 调用参数
        call_args = mock_subprocess_run.call_args
        assert call_args is not None
        cmd = call_args[0][0]
        assert cmd[:3] == ["docker", "compose", "-f"]
        assert "compose.yml" in cmd[3]

    def test_restart_service_uses_docker_compose_yml_when_no_compose_yml(
        self,
        tmp_deploy_root: Path,
        tmp_audit_dir: Path,
        tmp_manifest_path: str,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """compose.yml 不存在时回退到 docker-compose.yml。"""
        (tmp_deploy_root / "compose.yml").unlink()
        (tmp_deploy_root / "docker-compose.yml").write_text("version: '3'\n")
        adapter = CvmAutonomyAdapter.for_test(
            deploy_root=str(tmp_deploy_root),
            audit_dir=str(tmp_audit_dir),
            manifest_path=tmp_manifest_path,
        )
        mock_subprocess_run.return_value = _make_completed(returncode=0)
        action = _make_action(ActionType.RESTART_SERVICE, risk=RiskLevel.MEDIUM)

        result = adapter.execute_action(action)

        assert result.ok is True
        assert "docker-compose.yml" in result.detail


class TestRollbackSuccess:
    def test_rollback_to_last_tarball_success(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_deploy_root: Path,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """rollback 成功：.deploy-last.tar.gz + fhd-apply-release.sh 都存在 + 脚本返回 0。"""
        (tmp_deploy_root / ".deploy-last.tar.gz").write_bytes(b"fake tarball")
        scripts_dir = tmp_deploy_root / "scripts" / "deploy"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "fhd-apply-release.sh").write_text("#!/bin/bash\n")
        mock_subprocess_run.return_value = _make_completed(returncode=0, stdout="applied")
        action = _make_action(ActionType.ROLLBACK_TO_LAST_TARBALL, risk=RiskLevel.HIGH)

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "rollback applied" in result.detail
        # 验证 env 注入了 FHD_RELEASE_TARBALL
        call_kwargs = mock_subprocess_run.call_args.kwargs
        assert "FHD_RELEASE_TARBALL" in call_kwargs["env"]
        assert call_kwargs["env"]["FHD_RELEASE_TARBALL"].endswith(".deploy-last.tar.gz")


class TestFreezeManifestSuccess:
    def test_freeze_manifest_success(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """freeze_manifest 成功：manifest 存在 + .hold 不存在 → os.rename 成功。"""
        assert os.path.isfile(tmp_manifest_path)
        action = _make_action(ActionType.FREEZE_MANIFEST, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "manifest frozen" in result.detail
        # 验证 .hold 文件已生成
        assert os.path.isfile(f"{tmp_manifest_path}.hold")
        # 原 manifest 已重命名走
        assert not os.path.isfile(tmp_manifest_path)


class TestClearLogsSuccess:
    def test_clear_logs_success(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        mock_subprocess_run: MagicMock,
        tmp_deploy_root: Path,
    ) -> None:
        """clear_logs 成功：logs 目录存在 + find 返回 0。"""
        mock_subprocess_run.return_value = _make_completed(returncode=0)
        action = _make_action(ActionType.CLEAR_LOGS, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "logs older than 7d cleared" in result.detail
        # 验证 find 命令
        cmd = mock_subprocess_run.call_args[0][0]
        assert cmd[0] == "find"
        assert "-mtime" in cmd
        assert "+7" in cmd
        assert "-delete" in cmd


class TestEscalateNoopSuccess:
    def test_escalate_returns_ok(self, adapter_for_test: CvmAutonomyAdapter) -> None:
        """escalate 始终返回 ok=True。"""
        action = _make_action(ActionType.ESCALATE, risk=RiskLevel.HIGH)

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "escalate acknowledged" in result.detail

    def test_noop_returns_ok(self, adapter_for_test: CvmAutonomyAdapter) -> None:
        """noop 始终返回 ok=True。"""
        action = _make_action(ActionType.NOOP, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "noop acknowledged" in result.detail


# --------------------------------------------------------------------------- #
# 6 个 action 失败路径
# --------------------------------------------------------------------------- #


class TestActionFailures:
    def test_restart_service_no_compose_file(
        self,
        tmp_deploy_root: Path,
        tmp_audit_dir: Path,
        tmp_manifest_path: str,
    ) -> None:
        """restart_service 失败：compose.yml 与 docker-compose.yml 都不存在。"""
        (tmp_deploy_root / "compose.yml").unlink()
        adapter = CvmAutonomyAdapter.for_test(
            deploy_root=str(tmp_deploy_root),
            audit_dir=str(tmp_audit_dir),
            manifest_path=tmp_manifest_path,
        )
        action = _make_action(ActionType.RESTART_SERVICE, risk=RiskLevel.MEDIUM)

        result = adapter.execute_action(action)

        assert result.ok is False
        assert "no compose.yml" in result.detail

    def test_rollback_no_tarball(
        self,
        adapter_for_test: CvmAutonomyAdapter,
    ) -> None:
        """rollback 失败：.deploy-last.tar.gz 不存在。"""
        action = _make_action(ActionType.ROLLBACK_TO_LAST_TARBALL, risk=RiskLevel.HIGH)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "no .deploy-last.tarball" in result.detail

    def test_rollback_no_apply_script(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_deploy_root: Path,
    ) -> None:
        """rollback 失败：.deploy-last.tar.gz 存在但 fhd-apply-release.sh 不存在。"""
        (tmp_deploy_root / ".deploy-last.tar.gz").write_bytes(b"fake")
        action = _make_action(ActionType.ROLLBACK_TO_LAST_TARBALL, risk=RiskLevel.HIGH)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "no fhd-apply-release.sh" in result.detail

    def test_freeze_manifest_no_manifest(
        self,
        tmp_deploy_root: Path,
        tmp_audit_dir: Path,
    ) -> None:
        """freeze_manifest 失败：manifest 不存在。"""
        adapter = CvmAutonomyAdapter.for_test(
            deploy_root=str(tmp_deploy_root),
            audit_dir=str(tmp_audit_dir),
            manifest_path=str(tmp_deploy_root / "nonexistent.json"),
        )
        action = _make_action(ActionType.FREEZE_MANIFEST, risk=RiskLevel.LOW)

        result = adapter.execute_action(action)

        assert result.ok is False
        assert "manifest not found" in result.detail

    def test_freeze_manifest_already_frozen(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """freeze_manifest 失败：.hold 已存在。"""
        Path(f"{tmp_manifest_path}.hold").write_text("frozen")
        action = _make_action(ActionType.FREEZE_MANIFEST, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "already frozen" in result.detail

    def test_clear_logs_no_logs_dir(
        self,
        tmp_deploy_root: Path,
        tmp_audit_dir: Path,
        tmp_manifest_path: str,
    ) -> None:
        """clear_logs 失败：logs 目录不存在。"""
        import shutil

        shutil.rmtree(tmp_deploy_root / "logs")
        adapter = CvmAutonomyAdapter.for_test(
            deploy_root=str(tmp_deploy_root),
            audit_dir=str(tmp_audit_dir),
            manifest_path=tmp_manifest_path,
        )
        action = _make_action(ActionType.CLEAR_LOGS, risk=RiskLevel.LOW)

        result = adapter.execute_action(action)

        assert result.ok is False
        assert "no logs dir" in result.detail

    def test_restart_service_subprocess_failure(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """restart_service 失败：docker compose restart 返回非 0。"""
        mock_subprocess_run.return_value = _make_completed(
            returncode=1, stderr="docker error"
        )
        action = _make_action(ActionType.RESTART_SERVICE, risk=RiskLevel.MEDIUM)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "docker compose restart failed" in result.detail
        assert "docker error" in result.detail

    def test_clear_logs_subprocess_failure(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """clear_logs 失败：find 返回非 0。"""
        mock_subprocess_run.return_value = _make_completed(
            returncode=1, stderr="permission denied"
        )
        action = _make_action(ActionType.CLEAR_LOGS, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "find -mtime +7 -delete failed" in result.detail

    def test_rollback_subprocess_failure(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_deploy_root: Path,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """rollback 失败：fhd-apply-release.sh 返回非 0。"""
        (tmp_deploy_root / ".deploy-last.tar.gz").write_bytes(b"fake")
        scripts_dir = tmp_deploy_root / "scripts" / "deploy"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "fhd-apply-release.sh").write_text("#!/bin/bash\n")
        mock_subprocess_run.return_value = _make_completed(
            returncode=1, stderr="health check failed"
        )
        action = _make_action(ActionType.ROLLBACK_TO_LAST_TARBALL, risk=RiskLevel.HIGH)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "fhd-apply-release.sh failed" in result.detail
        assert "health check failed" in result.detail

    def test_subprocess_timeout_returns_failure(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        mock_subprocess_run: MagicMock,
    ) -> None:
        """subprocess 超时（subprocess.TimeoutExpired）→ ok=False。"""
        mock_subprocess_run.side_effect = subprocess.TimeoutExpired(cmd="docker", timeout=60)
        action = _make_action(ActionType.RESTART_SERVICE, risk=RiskLevel.MEDIUM)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "execute_threw" in result.detail


# --------------------------------------------------------------------------- #
# collect_truth 容错
# --------------------------------------------------------------------------- #


class TestCollectTruth:
    def test_collect_truth_healthy(
        self,
        healthy_adapter: CvmAutonomyAdapter,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """collect_truth: health_ok=True + compose running + manifest 存在。"""
        truth = healthy_adapter.collect_truth()

        assert truth.health_ok is True
        assert truth.compose_status == "running"
        assert truth.service_running is True
        assert truth.manifest_exists is True
        assert truth.manifest_frozen is False
        assert truth.deploy_root == str(tmp_deploy_root)
        assert truth.manifest_path == tmp_manifest_path

    def test_collect_truth_unhealthy(
        self,
        adapter_for_test: CvmAutonomyAdapter,
    ) -> None:
        """collect_truth: health_ok=False + compose exited。"""
        adapter_for_test._health_probe = lambda url: False
        adapter_for_test._compose_status_probe = lambda root: ("exited", False)

        truth = adapter_for_test.collect_truth()

        assert truth.health_ok is False
        assert truth.compose_status == "exited"
        assert truth.service_running is False

    def test_collect_truth_no_compose_file(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_deploy_root: Path,
    ) -> None:
        """collect_truth: compose.yml 不存在 → status='absent'。"""
        (tmp_deploy_root / "compose.yml").unlink()
        adapter_for_test._health_probe = lambda url: True
        # _compose_status_probe 为 None → 走真实路径，但 compose 文件不存在

        truth = adapter_for_test.collect_truth()

        assert truth.compose_status == "absent"
        assert truth.service_running is False

    def test_collect_truth_manifest_frozen(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """collect_truth: .hold 存在 → manifest_frozen=True。"""
        Path(f"{tmp_manifest_path}.hold").write_text("frozen")
        adapter_for_test._health_probe = lambda url: True
        adapter_for_test._compose_status_probe = lambda root: ("running", True)

        truth = adapter_for_test.collect_truth()

        assert truth.manifest_frozen is True

    def test_collect_truth_last_backup_ts(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_deploy_root: Path,
    ) -> None:
        """collect_truth: .deploy-last.tar.gz 存在 → last_backup_ts 非 None。"""
        (tmp_deploy_root / ".deploy-last.tar.gz").write_bytes(b"fake")
        adapter_for_test._health_probe = lambda url: True
        adapter_for_test._compose_status_probe = lambda root: ("running", True)

        truth = adapter_for_test.collect_truth()

        assert truth.last_backup_ts is not None
        assert truth.last_backup_ts > 0

    def test_collect_truth_no_backup_returns_none(
        self,
        adapter_for_test: CvmAutonomyAdapter,
    ) -> None:
        """collect_truth: .deploy-last.tar.gz 不存在 → last_backup_ts=None。"""
        adapter_for_test._health_probe = lambda url: True
        adapter_for_test._compose_status_probe = lambda root: ("running", True)

        truth = adapter_for_test.collect_truth()

        assert truth.last_backup_ts is None


# --------------------------------------------------------------------------- #
# audit 写入与读取
# --------------------------------------------------------------------------- #


class TestAudit:
    def test_audit_writes_jsonl(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_audit_dir: Path,
    ) -> None:
        """audit: 写入 audit.jsonl，每行一个 JSON。"""
        diagnosis = Diagnosis(
            root_cause="test_cause", confidence=0.8, detail="test detail", evidence=["e1"]
        )
        action = _make_action(ActionType.NOOP, risk=RiskLevel.LOW)
        entry = AuditEntry(
            ts="2026-07-18T00:00:00Z",
            source_signal=None,
            diagnosis=diagnosis,
            action=action,
            result=None,
            truth_snapshot=None,
        )

        adapter_for_test.audit(entry)

        audit_path = str(tmp_audit_dir / "audit.jsonl")
        entries = list_audit_entries(audit_path)
        assert len(entries) == 1
        assert entries[0]["ts"] == "2026-07-18T00:00:00Z"
        assert entries[0]["diagnosis"]["root_cause"] == "test_cause"
        assert entries[0]["action"]["type"] == "noop"

    def test_audit_failure_silent(
        self,
        tmp_deploy_root: Path,
        tmp_manifest_path: str,
    ) -> None:
        """audit: 写入失败（目录不可写）不抛错。"""
        # 使用不存在的 audit_dir，且无法创建（通过将 audit_dir 设为只读路径下）
        adapter = CvmAutonomyAdapter.for_test(
            deploy_root=str(tmp_deploy_root),
            audit_dir="/nonexistent/path/that/cannot/be/created/autonomy",
            manifest_path=tmp_manifest_path,
        )
        entry = AuditEntry(
            ts="2026-07-18T00:00:00Z",
            source_signal=None,
            diagnosis=None,
            action=None,
            result=None,
        )
        # 不应抛错
        adapter.audit(entry)

    def test_audit_skipped_action_serialized(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_audit_dir: Path,
    ) -> None:
        """audit: action 为 dict（skipped）时正确序列化。"""
        entry = AuditEntry(
            ts="2026-07-18T00:00:00Z",
            source_signal=None,
            diagnosis=None,
            action={"type": "skipped", "reasons": ["dry_run"]},
            result=None,
        )

        adapter_for_test.audit(entry)

        entries = list_audit_entries(str(tmp_audit_dir / "audit.jsonl"))
        assert len(entries) == 1
        assert entries[0]["action"]["type"] == "skipped"
        assert entries[0]["action"]["reasons"] == ["dry_run"]


# --------------------------------------------------------------------------- #
# 默认配置与构造
# --------------------------------------------------------------------------- #


class TestDefaults:
    def test_default_constants(self) -> None:
        """默认常量与文档一致。"""
        assert DEFAULT_DEPLOY_ROOT == "/opt/fhd-full"
        assert DEFAULT_MANIFEST_PATH == "/var/www/update/releases/stable/server/fhd-manifest.json"
        assert DEFAULT_HEALTH_URL == "https://xiu-ci.com/fhd-api/api/health"

    def test_constructor_creates_audit_dir(
        self,
        tmp_path: Path,
    ) -> None:
        """构造函数自动创建 audit_dir。"""
        audit_dir = tmp_path / "new_autonomy"
        assert not audit_dir.exists()
        CvmAutonomyAdapter(audit_dir=str(audit_dir))
        assert audit_dir.exists()
