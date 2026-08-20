# mypy: disable-error-code="import-not-found"
"""_approval_ledger_client.py 单元测试。

覆盖：
- 成功调用：URL / headers / body 正确，返回 response.json()
- FHD_API_BASE_URL 缺失 → fail-open 返回 None
- token 缺失 → fail-open 返回 None
- httpx 抛异常 → fail-open 返回 None，stderr 有日志
- response 非 2xx → fail-open 返回 None
- source 透传到 body
- action_id 非空时透传到 body
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 把 FHD/scripts/ci 加入 sys.path 以便直接 import _approval_ledger_client 模块
FHD_ROOT = Path(__file__).resolve().parents[2]
CI_SCRIPTS = FHD_ROOT / "scripts" / "ci"
if str(CI_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CI_SCRIPTS))

import _approval_ledger_client as client  # noqa: E402

# =====================================================================
# 测试 fixtures
# =====================================================================


@pytest.fixture
def env_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """注入正常的 env 配置。"""
    monkeypatch.setenv("FHD_API_BASE_URL", "https://xiu-ci.com")
    monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "tok-123")
    monkeypatch.delenv("MODSTORE_OPS_INGEST_TOKEN", raising=False)


def _make_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """构造 mock httpx.Response。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "" if status_code < 400 else "error body"
    resp.json.return_value = json_data if json_data is not None else {"ok": True}
    return resp


# =====================================================================
# 成功路径
# =====================================================================


class TestSuccess:
    def test_successful_post_returns_response_json(self, env_ok: None) -> None:
        expected = {"ok": True, "action_id": "abc", "state": "pending"}
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = _make_response(200, expected)

        with patch.object(client.httpx, "Client", return_value=mock_client) as ctor:
            result = client.post_to_approval_ledger(
                action="restart_service",
                payload={"service": "fhd-api"},
                source="cvm-watcher",
                action_id="evt-001",
            )

        assert result == expected
        # 验证 httpx.Client 调用 timeout=10.0
        ctor.assert_called_once_with(timeout=10.0)
        # 验证 URL
        call_args = mock_client.post.call_args
        assert call_args.args[0] == "https://xiu-ci.com/api/ops/autonomy/actions/ingest"
        # 验证 headers
        headers = call_args.kwargs["headers"]
        assert headers["X-Autonomy-Token"] == "tok-123"
        assert headers["Content-Type"] == "application/json"
        # 验证 body
        body = call_args.kwargs["json"]
        assert body["action"] == "restart_service"
        assert body["payload"] == {"service": "fhd-api"}
        assert body["source"] == "cvm-watcher"
        assert body["action_id"] == "evt-001"

    def test_source_default_is_runtime(self, env_ok: None) -> None:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = _make_response(200, {"ok": True})

        with patch.object(client.httpx, "Client", return_value=mock_client):
            client.post_to_approval_ledger(action="apply_release_to_cvm", payload={})

        body = mock_client.post.call_args.kwargs["json"]
        assert body["source"] == "runtime"
        # action_id 未传不应出现在 body 中
        assert "action_id" not in body

    def test_modstore_token_also_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHD_API_BASE_URL", "https://xiu-ci.com")
        monkeypatch.delenv("AUTONOMY_WEBHOOK_TOKEN", raising=False)
        monkeypatch.setenv("MODSTORE_OPS_INGEST_TOKEN", "ops-tok-456")

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = _make_response(200, {"ok": True})

        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result == {"ok": True}
        headers = mock_client.post.call_args.kwargs["headers"]
        assert headers["X-Autonomy-Token"] == "ops-tok-456"

    def test_base_url_trailing_slash_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHD_API_BASE_URL", "https://xiu-ci.com/")
        monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "tok-123")

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = _make_response(200, {"ok": True})

        with patch.object(client.httpx, "Client", return_value=mock_client):
            client.post_to_approval_ledger(action="restart_service", payload={})

        url = mock_client.post.call_args.args[0]
        assert url == "https://xiu-ci.com/api/ops/autonomy/actions/ingest"


# =====================================================================
# fail-open：env 缺失
# =====================================================================


class TestEnvMissing:
    def test_missing_base_url_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FHD_API_BASE_URL", raising=False)
        monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "tok-123")

        mock_client = MagicMock()
        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result is None
        mock_client.post.assert_not_called()

    def test_missing_token_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHD_API_BASE_URL", "https://xiu-ci.com")
        monkeypatch.delenv("AUTONOMY_WEBHOOK_TOKEN", raising=False)
        monkeypatch.delenv("MODSTORE_OPS_INGEST_TOKEN", raising=False)

        mock_client = MagicMock()
        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result is None
        mock_client.post.assert_not_called()

    def test_empty_token_treated_as_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHD_API_BASE_URL", "https://xiu-ci.com")
        monkeypatch.setenv("AUTONOMY_WEBHOOK_TOKEN", "   ")
        monkeypatch.delenv("MODSTORE_OPS_INGEST_TOKEN", raising=False)

        mock_client = MagicMock()
        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result is None
        mock_client.post.assert_not_called()


# =====================================================================
# fail-open：httpx 异常 & 非 2xx
# =====================================================================


class TestFailOpen:
    def test_httpx_raises_returns_none(
        self,
        env_ok: None,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.side_effect = httpx_err = RuntimeError("connection reset")

        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result is None
        captured = capsys.readouterr()
        assert "approval-ledger" in captured.err
        assert "connection reset" in captured.err

    def test_httpx_timeout_returns_none(
        self,
        env_ok: None,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import httpx as _httpx_mod

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.side_effect = _httpx_mod.TimeoutException("timed out")

        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result is None
        assert "approval-ledger" in capsys.readouterr().err

    def test_non_2xx_returns_none(
        self,
        env_ok: None,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = _make_response(500, {"err": "boom"})

        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result is None
        assert "non-2xx" in capsys.readouterr().err

    def test_401_returns_none(
        self,
        env_ok: None,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = _make_response(401, {"detail": "invalid token"})

        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result is None
        assert "non-2xx" in capsys.readouterr().err

    def test_2xx_boundary_199_returns_none(self, env_ok: None) -> None:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = _make_response(199, {"ok": True})

        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result is None

    def test_2xx_boundary_300_returns_none(self, env_ok: None) -> None:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = _make_response(300, {"ok": True})

        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result is None

    def test_201_returns_data(self, env_ok: None) -> None:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = False
        mock_client.post.return_value = _make_response(201, {"ok": True, "created": True})

        with patch.object(client.httpx, "Client", return_value=mock_client):
            result = client.post_to_approval_ledger(action="restart_service", payload={})

        assert result == {"ok": True, "created": True}
