"""管理员审计日志 API。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.infrastructure.auth.dependencies import get_logged_in_user


@pytest.fixture(autouse=True)
def _disable_lan_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAN_GUARD_ENABLED", "0")
    from app.security.lan_config import reset_lan_config_cache
    from app.security.lan_settings_store import LanSettingsOverride

    monkeypatch.setattr(
        "app.security.lan_settings_store.load_overrides",
        lambda: LanSettingsOverride(enabled=False),
    )
    reset_lan_config_cache()


def test_admin_audit_logs_requires_auth(client: TestClient) -> None:
    resp = client.get("/api/admin/audit-logs")
    assert resp.status_code == 401


def test_admin_audit_logs_returns_items(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    log_file = tmp_path / "audit.jsonl"
    log_file.write_text(
        json.dumps({"action": "auth_login", "success": True}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUDIT_LOG_PATH", str(log_file))

    def _fake_admin(_request=None):
        return SimpleNamespace(id=1, username="admin", role="admin")

    client.app.dependency_overrides[get_logged_in_user] = _fake_admin
    try:
        resp = client.get("/api/admin/audit-logs?limit=10")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("success") is True
        assert body["data"]["total"] >= 1
    finally:
        client.app.dependency_overrides.pop(get_logged_in_user, None)
