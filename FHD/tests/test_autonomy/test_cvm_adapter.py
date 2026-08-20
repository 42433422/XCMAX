# mypy: disable-error-code="func-returns-value"
"""tests/test_autonomy/test_cvm_adapter.py — CvmAutonomyAdapter 单元测试。

覆盖：
  - 8 个 action 的成功路径（restart_service / rollback_to_last_tarball /
    freeze_manifest / unfreeze_manifest / clear_logs / escalate / noop /
    open_incident_issue）
  - 8 个 action 的失败路径（无 compose.yml / 无 .deploy-last.tarball / 无 manifest /
    无 logs 目录 / subprocess 超时 / 命令失败 / hold_ttl 未过期 / health 失败 /
    token 缺失 / GitHub API 错误 / 24h 去重命中 / 前置 action 成功跳过）
  - collect_truth 容错（docker 不可用 / df 失败 / manifest 不存在）
  - check_unfreeze_needed 守护逻辑
  - audit 写入与读取
"""

from __future__ import annotations

import json
import os
import subprocess
import time
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
from scripts.autonomy.types import (
    Action,
    ActionResult,
    ActionType,
    AuditEntry,
    Diagnosis,
    RiskLevel,
)

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


def _make_completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess:
    """构造 CompletedProcess。"""
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------- #
# 8 个 action 成功路径
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
        """freeze_manifest 成功：manifest 存在 + .frozen 不存在 → touch marker 文件。

        与 fhd-deploy.yml#L171 `touch ${MANIFEST}.frozen` 同源：marker 文件创建后
        manifest 原地保留（cron 检测 marker 跳过自动更新）。
        """
        assert os.path.isfile(tmp_manifest_path)
        action = _make_action(ActionType.FREEZE_MANIFEST, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "manifest frozen" in result.detail
        assert "manifest preserved" in result.detail
        # 验证 .frozen marker 文件已生成
        assert os.path.isfile(f"{tmp_manifest_path}.frozen")
        # manifest 原地保留（touch 语义，不 rename）
        assert os.path.isfile(tmp_manifest_path)


class TestUnfreezeManifestSuccess:
    """unfreeze_manifest action 成功路径：hold_ttl 过期 + health 通过 → rm .frozen。"""

    def test_unfreeze_manifest_success_when_expired_and_healthy(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """hold_ttl 过期 + health_ok=True → rm .frozen 成功，ok=True。"""
        frozen_path = f"{tmp_manifest_path}.frozen"
        Path(frozen_path).write_text("frozen")
        # 把 mtime 设为 1 小时前（远超默认 hold_ttl 30min）
        old_ts = time.time() - 3600
        os.utime(frozen_path, (old_ts, old_ts))
        adapter_for_test._health_probe = lambda url: True
        adapter_for_test.hold_ttl = 1800  # 显式 30min
        action = _make_action(ActionType.UNFREEZE_MANIFEST, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "manifest unfrozen" in result.detail
        assert "marker=" in result.detail
        assert "health=ok" in result.detail
        # .frozen marker 已被 rm
        assert not os.path.isfile(frozen_path)

    def test_unfreeze_manifest_no_frozen_marker(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """.frozen 不存在 → ok=False, "no .frozen marker to remove"。"""
        assert not os.path.isfile(f"{tmp_manifest_path}.frozen")
        action = _make_action(ActionType.UNFREEZE_MANIFEST, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "no .frozen marker" in result.detail

    def test_unfreeze_manifest_within_hold_ttl_keeps_frozen(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """mtime age < hold_ttl → ok=False, "still within hold_ttl"。"""
        frozen_path = f"{tmp_manifest_path}.frozen"
        # mtime 设为 5 分钟前（默认 hold_ttl 30min，未过期）
        recent_ts = time.time() - 300
        Path(frozen_path).write_text("frozen")
        os.utime(frozen_path, (recent_ts, recent_ts))
        adapter_for_test.hold_ttl = 1800
        action = _make_action(ActionType.UNFREEZE_MANIFEST, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "keep frozen" in result.detail
        assert "age 300s" in result.detail
        assert f"< hold_ttl {adapter_for_test.hold_ttl}s" in result.detail
        # marker 未删除
        assert os.path.isfile(frozen_path)

    def test_unfreeze_manifest_health_failed_keeps_frozen(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """hold_ttl 过期 BUT health_ok=False → ok=False, "health failed, keep frozen"。"""
        frozen_path = f"{tmp_manifest_path}.frozen"
        old_ts = time.time() - 3600  # 1 小时前，已过期
        Path(frozen_path).write_text("frozen")
        os.utime(frozen_path, (old_ts, old_ts))
        adapter_for_test._health_probe = lambda url: False
        adapter_for_test.hold_ttl = 1800
        action = _make_action(ActionType.UNFREEZE_MANIFEST, risk=RiskLevel.LOW)

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "health check failed" in result.detail
        assert "keep frozen" in result.detail
        # marker 未删除（health 失败保持冻结）
        assert os.path.isfile(frozen_path)

    def test_unfreeze_manifest_custom_hold_ttl_via_env(
        self,
        tmp_deploy_root: Path,
        tmp_audit_dir: Path,
        tmp_manifest_path: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """env FHD_MANIFEST_HOLD_TTL_SECONDS=60 → hold_ttl=60s, 5 分钟前 marker 视为过期。"""
        monkeypatch.setenv("FHD_MANIFEST_HOLD_TTL_SECONDS", "60")
        adapter = CvmAutonomyAdapter(
            deploy_root=str(tmp_deploy_root),
            manifest_path=tmp_manifest_path,
            audit_dir=str(tmp_audit_dir),
        )
        assert adapter.hold_ttl == 60

        frozen_path = f"{tmp_manifest_path}.frozen"
        old_ts = time.time() - 300  # 5 分钟前，> 60s ttl
        Path(frozen_path).write_text("frozen")
        os.utime(frozen_path, (old_ts, old_ts))
        adapter._health_probe = lambda url: True
        action = _make_action(ActionType.UNFREEZE_MANIFEST, risk=RiskLevel.LOW)

        result = adapter.execute_action(action)

        assert result.ok is True
        assert "ttl=60s" in result.detail
        assert not os.path.isfile(frozen_path)


class TestCheckUnfreezeNeeded:
    """adapter.check_unfreeze_needed() 守护逻辑测试。"""

    def test_no_frozen_marker_returns_false(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """.frozen 不存在 → (False, 0)。"""
        needed, age = adapter_for_test.check_unfreeze_needed()

        assert needed is False
        assert age == 0

    def test_within_hold_ttl_returns_false(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """mtime age < hold_ttl → (False, age)。"""
        frozen_path = f"{tmp_manifest_path}.frozen"
        recent_ts = time.time() - 60  # 1 分钟前
        Path(frozen_path).write_text("frozen")
        os.utime(frozen_path, (recent_ts, recent_ts))
        adapter_for_test.hold_ttl = 1800

        needed, age = adapter_for_test.check_unfreeze_needed()

        assert needed is False
        assert 50 <= age <= 70  # ~60s ± 容差

    def test_expired_returns_true(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_manifest_path: str,
    ) -> None:
        """mtime age >= hold_ttl → (True, age)。"""
        frozen_path = f"{tmp_manifest_path}.frozen"
        old_ts = time.time() - 3600  # 1 小时前
        Path(frozen_path).write_text("frozen")
        os.utime(frozen_path, (old_ts, old_ts))
        adapter_for_test.hold_ttl = 1800

        needed, age = adapter_for_test.check_unfreeze_needed()

        assert needed is True
        assert 3500 <= age <= 3700


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
# open_incident_issue 成功路径（GitHub REST API 创建 incident issue）
# --------------------------------------------------------------------------- #


def _make_incident_action(
    *,
    incident_type: str = "health_down",
    previous_action_key: str = "restart_service:health_down",
    source_kind: str = "health_down",
    reason: str = "health check failed after restart",
    diagnosis_root_cause: str = "service_unhealthy",
) -> Action:
    """构造测试用 open_incident_issue action。"""
    return Action(
        type=ActionType.OPEN_INCIDENT_ISSUE,
        params={
            "incident_type": incident_type,
            "previous_action_key": previous_action_key,
            "source_kind": source_kind,
            "reason": reason,
            "diagnosis_root_cause": diagnosis_root_cause,
            "evidence": {"compose_status": "exited"},
            "truth_snapshot": {"health_ok": False},
        },
        idempotency_key=f"open_incident_issue:{incident_type}",
        max_attempts=1,
        risk=RiskLevel.LOW,
    )


class TestOpenIncidentIssue:
    """open_incident_issue action：GitHub REST API 创建 incident issue。"""

    def test_token_missing_returns_failure(
        self,
        adapter_for_test: CvmAutonomyAdapter,
    ) -> None:
        """github_token 或 github_repo 未配置 → ok=False, 不阻断 watcher。"""
        # adapter_for_test 默认 github_token / github_repo 都是 None
        assert adapter_for_test.github_token is None
        assert adapter_for_test.github_repo is None
        action = _make_incident_action()

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "github_token/github_repo not configured" in result.detail

    def test_previous_action_succeeded_skips_issue_creation(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_audit_dir: Path,
    ) -> None:
        """前置 remediation action 在 audit 中成功 → ok=True, idempotent skip。"""
        adapter_for_test.github_token = "fake-token"
        adapter_for_test.github_repo = "owner/repo"
        # 写入一条 audit：restart_service:health_down 成功
        from scripts.autonomy.types import AuditEntry, Diagnosis

        prev_action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": "test"},
            idempotency_key="restart_service:health_down",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        prev_result = ActionResult(
            action=prev_action,
            ok=True,
            detail="docker compose restart ok",
            ts=1000,
        )
        entry = AuditEntry(
            ts="2026-07-18T00:00:00Z",
            source_signal=None,
            diagnosis=Diagnosis(
                root_cause="service_unhealthy",
                confidence=0.8,
                detail="test",
                evidence=[],
            ),
            action=prev_action,
            result=prev_result,
            truth_snapshot=None,
        )
        adapter_for_test.audit(entry)
        # 不应被调用的 GitHub API mock
        adapter_for_test._github_api_get = lambda url, token: (_ for _ in ()).throw(
            AssertionError("search should not be called when prev succeeded")
        )
        adapter_for_test._github_api_post = lambda url, token, body: (_ for _ in ()).throw(
            AssertionError("create should not be called when prev succeeded")
        )
        action = _make_incident_action()

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "previous action restart_service:health_down succeeded" in result.detail
        assert "skip incident issue" in result.detail

    def test_previous_action_failed_creates_issue(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_audit_dir: Path,
    ) -> None:
        """前置 action 失败 → 创建 issue（_github_api_post mock 返回 issue URL）。"""
        adapter_for_test.github_token = "fake-token"
        adapter_for_test.github_repo = "owner/repo"
        # 写入一条失败 audit
        from scripts.autonomy.types import AuditEntry, Diagnosis

        prev_action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": "test"},
            idempotency_key="restart_service:health_down",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        prev_result = ActionResult(
            action=prev_action,
            ok=False,
            detail="docker compose restart failed",
            ts=1000,
        )
        entry = AuditEntry(
            ts="2026-07-18T00:00:00Z",
            source_signal=None,
            diagnosis=Diagnosis(
                root_cause="service_unhealthy",
                confidence=0.8,
                detail="test",
                evidence=[],
            ),
            action=prev_action,
            result=prev_result,
            truth_snapshot=None,
        )
        adapter_for_test.audit(entry)
        # search 无命中
        adapter_for_test._github_api_get = lambda url, token: {"items": []}
        created = {
            "number": 42,
            "html_url": "https://github.com/owner/repo/issues/42",
        }
        post_calls: list[tuple[str, str, dict[str, Any]]] = []
        adapter_for_test._github_api_post = lambda url, token, body: (
            post_calls.append((url, token, body)) or created
        )
        action = _make_incident_action()

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "incident issue #42 created" in result.detail
        assert "https://github.com/owner/repo/issues/42" in result.detail
        # 验证 POST 调用
        assert len(post_calls) == 1
        url, token, body = post_calls[0]
        assert url == "https://api.github.com/repos/owner/repo/issues"
        assert token == "fake-token"
        assert body["title"].startswith("[incident:health_down]")
        assert "ai-implement" in body["labels"]
        assert "incident" in body["labels"]
        assert "auto-incident" in body["labels"]

    def test_24h_dedup_skips_when_existing_issue_found(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_audit_dir: Path,
    ) -> None:
        """GitHub Search 命中已有 open issue → ok=True, 24h dedup skip。"""
        adapter_for_test.github_token = "fake-token"
        adapter_for_test.github_repo = "owner/repo"
        # 写入失败 audit（前置 action 失败）
        from scripts.autonomy.types import AuditEntry, Diagnosis

        prev_action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": "test"},
            idempotency_key="restart_service:health_down",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        adapter_for_test.audit(
            AuditEntry(
                ts="2026-07-18T00:00:00Z",
                source_signal=None,
                diagnosis=Diagnosis(
                    root_cause="service_unhealthy",
                    confidence=0.8,
                    detail="test",
                    evidence=[],
                ),
                action=prev_action,
                result=ActionResult(action=prev_action, ok=False, detail="failed", ts=1000),
                truth_snapshot=None,
            )
        )
        # search 命中
        existing = {
            "number": 7,
            "html_url": "https://github.com/owner/repo/issues/7",
        }
        adapter_for_test._github_api_get = lambda url, token: {"items": [existing]}
        adapter_for_test._github_api_post = lambda url, token, body: (_ for _ in ()).throw(
            AssertionError("create should not be called when dedup hit")
        )
        action = _make_incident_action()

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "incident issue #7 already exists (24h dedup)" in result.detail
        assert "https://github.com/owner/repo/issues/7" in result.detail

    def test_github_api_error_returns_failure(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_audit_dir: Path,
    ) -> None:
        """_github_post 返回 _error → ok=False, detail 含错误码。"""
        adapter_for_test.github_token = "fake-token"
        adapter_for_test.github_repo = "owner/repo"
        # 前置失败 audit
        from scripts.autonomy.types import AuditEntry, Diagnosis

        prev_action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": "test"},
            idempotency_key="restart_service:health_down",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        adapter_for_test.audit(
            AuditEntry(
                ts="2026-07-18T00:00:00Z",
                source_signal=None,
                diagnosis=Diagnosis(
                    root_cause="service_unhealthy",
                    confidence=0.8,
                    detail="test",
                    evidence=[],
                ),
                action=prev_action,
                result=ActionResult(action=prev_action, ok=False, detail="failed", ts=1000),
                truth_snapshot=None,
            )
        )
        adapter_for_test._github_api_get = lambda url, token: {"items": []}
        adapter_for_test._github_api_post = lambda url, token, body: {
            "_error": 422,
            "_body": "validation failed",
        }
        action = _make_incident_action()

        result = adapter_for_test.execute_action(action)

        assert result.ok is False
        assert "github create issue failed 422" in result.detail
        assert "validation failed" in result.detail

    def test_no_previous_action_key_still_creates_issue(
        self,
        adapter_for_test: CvmAutonomyAdapter,
    ) -> None:
        """previous_action_key 为空 → 不查 audit，直接走 search + create。"""
        adapter_for_test.github_token = "fake-token"
        adapter_for_test.github_repo = "owner/repo"
        adapter_for_test._github_api_get = lambda url, token: {"items": []}
        created = {"number": 99, "html_url": "https://github.com/owner/repo/issues/99"}
        adapter_for_test._github_api_post = lambda url, token, body: created
        action = _make_incident_action(previous_action_key="")

        result = adapter_for_test.execute_action(action)

        assert result.ok is True
        assert "incident issue #99 created" in result.detail

    def test_skips_escalate_and_incident_audit_entries_when_checking_previous(
        self,
        adapter_for_test: CvmAutonomyAdapter,
        tmp_audit_dir: Path,
    ) -> None:
        """_check_previous_action_result 跳过 escalate / open_incident_issue 同 key 条目。

        构造 audit 中：
          - 一条 escalate（idempotency_key=同 key，但 type=escalate）→ 应跳过
          - 一条真实的 restart_service 失败 → 应被取到
        """
        adapter_for_test.github_token = "fake-token"
        adapter_for_test.github_repo = "owner/repo"
        from scripts.autonomy.types import AuditEntry, Diagnosis

        # 一条 restart_service 失败 audit
        restart_action = Action(
            type=ActionType.RESTART_SERVICE,
            params={"reason": "test"},
            idempotency_key="restart_service:health_down",
            max_attempts=1,
            risk=RiskLevel.MEDIUM,
        )
        # 一条 escalate audit（同 idempotency_key，但 type=escalate）→ 应被跳过
        escalate_action = Action(
            type=ActionType.ESCALATE,
            params={"reason": "test", "original_action": "restart_service"},
            idempotency_key="restart_service:health_down",
            max_attempts=1,
            risk=RiskLevel.HIGH,
        )
        for act, ok in [
            (restart_action, False),  # restart 失败
            (escalate_action, True),  # escalate 成功（但应被跳过）
        ]:
            adapter_for_test.audit(
                AuditEntry(
                    ts="2026-07-18T00:00:00Z",
                    source_signal=None,
                    diagnosis=Diagnosis(
                        root_cause="service_unhealthy",
                        confidence=0.8,
                        detail="test",
                        evidence=[],
                    ),
                    action=act,
                    result=ActionResult(action=act, ok=ok, detail="detail", ts=1000),
                    truth_snapshot=None,
                )
            )
        # search 无命中 → 走 create
        adapter_for_test._github_api_get = lambda url, token: {"items": []}
        adapter_for_test._github_api_post = lambda url, token, body: {
            "number": 1,
            "html_url": "https://github.com/owner/repo/issues/1",
        }
        action = _make_incident_action()

        result = adapter_for_test.execute_action(action)

        # 因 restart_service 失败 → 应创建 issue（escalate 同 key 被跳过）
        assert result.ok is True
        assert "incident issue #1 created" in result.detail

    def test_build_incident_title_truncates_long_reason(
        self,
        adapter_for_test: CvmAutonomyAdapter,
    ) -> None:
        """_build_incident_title：reason > 60 字符 → 截断 + '...'。"""
        adapter_for_test.github_token = "fake-token"
        adapter_for_test.github_repo = "owner/repo"
        long_reason = "x" * 100  # 100 字符
        title = adapter_for_test._build_incident_title("disk_full", {"reason": long_reason})
        assert title.startswith("[incident:disk_full] ")
        # 60 字符 + "..."
        assert title.endswith("...")
        assert len(title) < len(long_reason) + len("[incident:disk_full] ")

    def test_build_incident_body_contains_required_sections(
        self,
        adapter_for_test: CvmAutonomyAdapter,
    ) -> None:
        """_build_incident_body：含来源、根因、证据、truth 摘要、闭环说明各 section。"""
        adapter_for_test.github_token = "fake-token"
        adapter_for_test.github_repo = "owner/repo"
        action = _make_incident_action()
        body = adapter_for_test._build_incident_body(action, action.params)

        # 来源 / 类型 / 根因 section
        assert "## 来源：CVM 自治 watcher incident" in body
        assert "`health_down`" in body
        assert "`service_unhealthy`" in body
        # 证据 / truth 摘要 section
        assert "## 证据快照" in body
        assert "## RuntimeTruthSnapshot 摘要" in body
        assert '"compose_status": "exited"' in body
        assert '"health_ok": false' in body
        # 闭环说明
        assert "`cvm-autonomy-watcher.yml` workflow" in body
        assert "`ai-issue-implement.yml` workflow" in body
        assert "ai-implement" in body
        assert "incident" in body
        # 修复建议
        assert "## 修复建议" in body


# --------------------------------------------------------------------------- #
# 8 个 action 失败路径（含 open_incident_issue 专属失败路径）
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
        """freeze_manifest 失败：.frozen marker 已存在。"""
        Path(f"{tmp_manifest_path}.frozen").write_text("frozen")
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
        mock_subprocess_run.return_value = _make_completed(returncode=1, stderr="docker error")
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
        mock_subprocess_run.return_value = _make_completed(returncode=1, stderr="permission denied")
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
        """collect_truth: .frozen marker 存在 → manifest_frozen=True。"""
        Path(f"{tmp_manifest_path}.frozen").write_text("frozen")
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
