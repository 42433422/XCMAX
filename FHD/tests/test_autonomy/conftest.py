"""tests/test_autonomy/ 共享 fixtures。

提供：
  - tmp_deploy_root: 模拟 /opt/fhd-full 的临时目录（含 compose.yml / manifest / logs 等）
  - tmp_audit_dir: 模拟 autonomy/audit 目录
  - mock_subprocess_run: monkeypatch subprocess.run，按 cmd 关键字返回预设结果
  - adapter_for_test: 注入 mock 的 CvmAutonomyAdapter 实例
  - sample_truth: 预设 RuntimeTruthSnapshot（用于 impact_predictor 测试）
  - sample_signal: 预设 Signal 工厂

所有 fixture 基于 tmp_path + monkeypatch，不依赖真实 /opt/fhd-full。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

# 让 tests 能 import scripts.autonomy.*
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.autonomy.cvm_adapter import CvmAutonomyAdapter  # noqa: E402
from scripts.autonomy.types import (  # noqa: E402
    Action,
    ActionType,
    RiskLevel,
    RuntimeTruthSnapshot,
    Signal,
)

# --------------------------------------------------------------------------- #
# 临时目录 fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def tmp_deploy_root(tmp_path: Path) -> Path:
    """模拟 /opt/fhd-full 的临时部署根目录。

    默认创建：
      - compose.yml（空文件，标识 compose 存在）
      - logs/ 目录
      - releases/stable/server/fhd-manifest.json（空 JSON）
    """
    deploy_root = tmp_path / "fhd-full"
    deploy_root.mkdir()
    (deploy_root / "compose.yml").write_text("version: '3'\n", encoding="utf-8")
    (deploy_root / "logs").mkdir()
    manifest_dir = deploy_root / "releases" / "stable" / "server"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "fhd-manifest.json").write_text(
        json.dumps({"version": "10.0.0", "sha256": "abc"}), encoding="utf-8"
    )
    return deploy_root


@pytest.fixture
def tmp_audit_dir(tmp_path: Path) -> Path:
    """模拟 /opt/fhd-full/autonomy 的临时 audit 目录。"""
    audit_dir = tmp_path / "autonomy"
    audit_dir.mkdir()
    return audit_dir


@pytest.fixture
def tmp_manifest_path(tmp_deploy_root: Path) -> str:
    """manifest 完整路径。"""
    return str(tmp_deploy_root / "releases" / "stable" / "server" / "fhd-manifest.json")


# --------------------------------------------------------------------------- #
# subprocess mock fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def mock_subprocess_run(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """monkeypatch subprocess.run，返回 MagicMock。

    测试可配置 mock.return_value 或 mock.side_effect 来控制返回结果。
    """
    mock = MagicMock()
    # 默认返回成功（returncode=0, stdout='', stderr=''）
    default_result = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    mock.return_value = default_result
    # 同时 patch scripts.autonomy.cvm_adapter.subprocess.run
    from scripts.autonomy import cvm_adapter as adapter_mod

    monkeypatch.setattr(adapter_mod.subprocess, "run", mock)
    return mock


@pytest.fixture
def configurable_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[list[str], subprocess.CompletedProcess], None]:
    """返回一个工厂函数，测试可注册 (cmd_prefix → CompletedResult) 映射。

    用法：
        configurable_subprocess(
            ["docker", "compose"],
            subprocess.CompletedProcess(args=[], returncode=0, stdout="...", stderr="")
        )
    """
    responses: list[tuple[list[str], subprocess.CompletedProcess]] = []

    def _fake_run(cmd, *args, **kwargs):
        for prefix, result in responses:
            if cmd[: len(prefix)] == prefix:
                return result
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    from scripts.autonomy import cvm_adapter as adapter_mod

    monkeypatch.setattr(adapter_mod.subprocess, "run", _fake_run)

    def register(prefix: list[str], result: subprocess.CompletedProcess) -> None:
        responses.append((prefix, result))

    return register


# --------------------------------------------------------------------------- #
# Adapter fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def adapter_for_test(
    tmp_deploy_root: Path,
    tmp_audit_dir: Path,
    tmp_manifest_path: str,
) -> CvmAutonomyAdapter:
    """创建测试用 CvmAutonomyAdapter（通过 for_test 工厂方法）。

    默认 health_probe / compose_status_probe 都未设置（None），需要测试自行注入或 mock。
    """
    adapter = CvmAutonomyAdapter.for_test(
        deploy_root=str(tmp_deploy_root),
        audit_dir=str(tmp_audit_dir),
        manifest_path=tmp_manifest_path,
    )
    return adapter


@pytest.fixture
def healthy_adapter(
    adapter_for_test: CvmAutonomyAdapter,
) -> CvmAutonomyAdapter:
    """注入 mock：health_ok=True, compose_status='running', service_running=True。"""
    adapter_for_test._health_probe = lambda url: True
    adapter_for_test._compose_status_probe = lambda root: ("running", True)
    return adapter_for_test


# --------------------------------------------------------------------------- #
# Truth / Signal fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def sample_truth(tmp_deploy_root: Path, tmp_manifest_path: str) -> RuntimeTruthSnapshot:
    """预设 RuntimeTruthSnapshot：健康 + compose running + 磁盘 50%。"""
    return RuntimeTruthSnapshot(
        ts=1_000_000,
        deploy_root=str(tmp_deploy_root),
        manifest_path=tmp_manifest_path,
        compose_status="running",
        health_ok=True,
        service_running=True,
        pending_rollback_marker=False,
        disk_usage_percent=50.0,
        config_fingerprint_changed=False,
        last_backup_ts=999_000,
        app_version="10.0.0",
        build_sha="abc123",
        restart_count=0,
        manifest_exists=True,
        manifest_frozen=False,
    )


@pytest.fixture
def unhealthy_truth(tmp_deploy_root: Path, tmp_manifest_path: str) -> RuntimeTruthSnapshot:
    """预设 RuntimeTruthSnapshot：health_ok=False + compose_status='exited'。"""
    return RuntimeTruthSnapshot(
        ts=1_000_000,
        deploy_root=str(tmp_deploy_root),
        manifest_path=tmp_manifest_path,
        compose_status="exited",
        health_ok=False,
        service_running=False,
        pending_rollback_marker=False,
        disk_usage_percent=95.0,
        config_fingerprint_changed=False,
        last_backup_ts=999_000,
        app_version="10.0.0",
        build_sha="abc123",
        restart_count=0,
        manifest_exists=True,
        manifest_frozen=False,
    )


def make_signal(
    kind: str,
    ts: int = 1_000_000,
    detail: str = "test signal",
    severity: str = "warn",
    source: str = "runtime_truth",
) -> Signal:
    """Signal 工厂（测试辅助）。"""
    return Signal(
        source=source,
        kind=kind,
        severity=severity,  # type: ignore[arg-type]
        detail=detail,
        ts=ts,
    )


@pytest.fixture
def signal_factory() -> Callable[..., Signal]:
    """返回 make_signal 工厂。"""
    return make_signal


@pytest.fixture
def health_down_signal() -> Signal:
    """预设 health_down 信号。"""
    return make_signal("health_down", severity="crit", detail="health check failed")


@pytest.fixture
def disk_full_signal() -> Signal:
    """预设 disk_full 信号。"""
    return make_signal("disk_full", severity="crit", detail="disk 95%")
