"""MODSTORE_AUTOMATION_PRIMARY / ROLE 门禁。"""

from __future__ import annotations

import pytest

from modstore_server.automation_primary import (
    is_daily_automation_delegated,
    skip_daily_automation_result,
)


def test_no_primary_never_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODSTORE_AUTOMATION_PRIMARY", raising=False)
    monkeypatch.delenv("MODSTORE_AUTOMATION_ROLE", raising=False)
    assert is_daily_automation_delegated() is False
    assert skip_daily_automation_result(job="daily_digest_email") is None


def test_server_follower_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_AUTOMATION_PRIMARY", "local_mac")
    monkeypatch.setenv("MODSTORE_AUTOMATION_ROLE", "server")
    assert is_daily_automation_delegated() is True
    out = skip_daily_automation_result(job="daily_digest_email")
    assert out is not None
    assert out.get("skipped") is True
    assert out.get("primary") == "local_mac"


def test_mac_primary_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODSTORE_AUTOMATION_PRIMARY", "local_mac")
    monkeypatch.setenv("MODSTORE_AUTOMATION_ROLE", "local_mac")
    assert is_daily_automation_delegated() is False
