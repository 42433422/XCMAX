"""staging 自动部署默认开启。"""

from __future__ import annotations

from pathlib import Path

import modstore_server.maintenance_loop.config as _maintenance_config
import modstore_server.maintenance_loop.deployment as _maintenance_deployment


def test_auto_dispatch_defaults_to_staging(monkeypatch):
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY", raising=False)
    monkeypatch.delenv("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_ENVS", raising=False)
    assert _maintenance_config._auto_dispatch_deploy_enabled() is True
    assert _maintenance_deployment._auto_dispatch_deploy_envs() == ["staging"]


def test_auto_dispatch_explicit_off(monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY", "0")
    assert _maintenance_config._auto_dispatch_deploy_enabled() is False
    assert _maintenance_deployment._auto_dispatch_deploy_envs() == []


def test_production_requires_explicit_envs(monkeypatch):
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY", "1")
    monkeypatch.setenv("MODSTORE_SELF_MAINTENANCE_AUTO_DISPATCH_DEPLOY_ENVS", "staging,production")
    assert _maintenance_deployment._auto_dispatch_deploy_envs() == ["staging", "production"]


def test_force_remote_trigger_outlives_para_wait_budget():
    script = (
        Path(__file__).resolve().parents[3]
        / "FHD"
        / "scripts"
        / "deploy"
        / "force_self_maintenance_remote.sh"
    ).read_text(encoding="utf-8")
    assert "--max-time 2400 -o /tmp/loop-run.json" in script
