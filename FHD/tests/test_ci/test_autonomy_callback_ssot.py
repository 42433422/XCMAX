"""autonomy_callback SSOT：ingest + github-approval 符号齐全、fail-open。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SSOT = (
    Path(__file__).resolve().parents[2] / "scripts" / "autonomy" / "autonomy_callback.py"
)


def _load_ssot():
    spec = importlib.util.spec_from_file_location("autonomy_callback_ssot_test", _SSOT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cb():
    return _load_ssot()


def test_ssot_exports(cb) -> None:
    for name in (
        "autonomy_callback",
        "report_callback",
        "deploy_callback",
        "report_executed",
        "report_execution_failed",
        "report_rejected",
        "report_approval_requested",
    ):
        assert callable(getattr(cb, name))


def test_report_executed_skips_without_env(cb, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FHD_API_BASE_URL", raising=False)
    monkeypatch.delenv("MODSTORE_OPS_BASE_URL", raising=False)
    monkeypatch.delenv("AUTONOMY_WEBHOOK_TOKEN", raising=False)
    monkeypatch.delenv("MODSTORE_OPS_INGEST_TOKEN", raising=False)
    assert cb.report_executed("act-1") is None


def test_report_executed_posts(cb, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_API_BASE_URL", "http://example.test")
    monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "tok")
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"ok": True, "state": "executed"}
    fake_httpx = MagicMock()
    fake_httpx.post.return_value = fake_resp
    with patch.object(cb, "httpx", fake_httpx):
        out = cb.report_executed("act-2", approver="tester")
    assert out == {"ok": True, "state": "executed"}
    fake_httpx.post.assert_called_once()
    args, kwargs = fake_httpx.post.call_args
    assert args[0].endswith("/api/ops/autonomy/github-approval")
    assert kwargs["json"]["decision"] == "executed"
