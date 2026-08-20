# mypy: disable-error-code="import-not-found"
"""autonomy_callback / report_callback / deploy_callback 契约测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AUTONOMY_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "autonomy"
if str(AUTONOMY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(AUTONOMY_SCRIPTS))

import autonomy_callback as cb  # noqa: E402


@pytest.fixture
def env_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_API_BASE_URL", "https://xiu-ci.com")
    monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "tok-cb")


def test_callback_symbols_exported() -> None:
    assert callable(cb.autonomy_callback)
    assert callable(cb.report_callback)
    assert callable(cb.deploy_callback)
    assert "autonomy_callback" in cb.__all__
    assert "report_callback" in cb.__all__
    assert "deploy_callback" in cb.__all__


def test_deploy_callback_posts_deploy_phase(env_ok: None) -> None:
    mock_post = MagicMock(return_value={"ok": True, "action_id": "a1"})
    with patch.object(cb, "post_to_approval_ledger", mock_post):
        out = cb.deploy_callback(
            "freeze_manifest",
            {"environment": "staging", "ok": True},
            source="self_maintenance",
            action_id="freeze-1",
        )
    assert out == {"ok": True, "action_id": "a1"}
    mock_post.assert_called_once()
    kwargs = mock_post.call_args.kwargs
    assert kwargs["action"] == "deploy:freeze_manifest"
    assert kwargs["source"] == "self_maintenance"
    assert kwargs["action_id"] == "freeze-1"
    assert kwargs["payload"]["callback_event"] == "deploy:freeze_manifest"
    assert kwargs["payload"]["environment"] == "staging"


def test_report_callback_posts_report_kind(env_ok: None) -> None:
    mock_post = MagicMock(return_value={"ok": True})
    with patch.object(cb, "post_to_approval_ledger", mock_post):
        cb.report_callback("ledger_sync", {"files": 2}, source="runtime-sync")
    kwargs = mock_post.call_args.kwargs
    assert kwargs["action"] == "report:ledger_sync"
    assert kwargs["source"] == "runtime-sync"


def test_autonomy_callback_fail_open_when_client_missing(env_ok: None) -> None:
    with patch.object(cb, "post_to_approval_ledger", None):
        assert cb.autonomy_callback("x", {"a": 1}) is None
