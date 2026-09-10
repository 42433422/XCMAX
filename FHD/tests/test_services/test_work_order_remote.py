# mypy: disable-error-code="no-any-return"
"""work_order_ssot 共享持久层（远端优先）测试。

覆盖：远端配置时的委托载荷、结果映射、不可达时回退本地 JSONL。
不访问网络：monkeypatch ``_remote_request`` / ``_remote_enabled``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services import work_order_ssot as wo


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("WORK_ORDER_SSOT_DIR", str(tmp_path))
    monkeypatch.setattr(wo, "_STORE_DIR", tmp_path)
    monkeypatch.setattr(wo, "_EVENTS_FILE", tmp_path / "work_orders.jsonl")
    return wo._EVENTS_FILE


@pytest.fixture
def remote_on(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append((method, path))
        return _FIXTURE_RESPONSE.get(path, {})

    monkeypatch.setattr(wo, "_remote_enabled", lambda: True)
    monkeypatch.setattr(wo, "_remote_request", fake_request)
    return calls


_FIXTURE_RESPONSE: dict[str, dict[str, Any]] = {
    "/api/work-orders/candidate": {
        "wo_id": "WO-abcdef123456",
        "created": True,
        "status": "candidate",
    },
    "/api/work-orders/transition": {
        "ok": True,
        "wo_id": "WO-abcdef123456",
        "from": "candidate",
        "to": "routed",
    },
    "/api/work-orders/acceptance": {
        "ok": True,
        "wo_id": "WO-abcdef123456",
        "from": "verifying",
        "to": "closed",
    },
    "/api/work-orders/by-issue/88": {
        "wo_id": "WO-abcdef123456",
        "status": "closed",
        "issue_number": 88,
    },
}


class TestRemoteDelegation:
    def test_upsert_candidate_delegates(self, isolated_store: Path, remote_on: list) -> None:
        result = wo.upsert_candidate(source="s", dedup_key="k-r1", reason="intent_unknown")
        assert result["remote"] is True
        assert result["wo_id"] == "WO-abcdef123456"
        assert result["created"] is True
        assert ("POST", "/api/work-orders/candidate") in remote_on
        # 本地事件流不写（远端为主）
        assert wo.list_work_orders() == []

    def test_transition_delegates_and_maps(self, isolated_store: Path, remote_on: list) -> None:
        result = wo.record_transition("WO-abcdef123456", "routed", ref={"issue_number": 1})
        assert result["remote"] is True
        assert result["to"] == "routed"
        assert result["ok"] is True
        assert remote_on[-1] == ("POST", "/api/work-orders/transition")

    def test_link_issue_delegates_with_track(self, isolated_store: Path, remote_on: list) -> None:
        result = wo.link_issue(
            "WO-abcdef123456", issue_number=88, issue_url="https://x/88", track="product_line"
        )
        assert result["remote"] is True
        assert result["to"] == "routed"

    def test_acceptance_delegates(self, isolated_store: Path, remote_on: list) -> None:
        result = wo.record_acceptance_verdict(
            issue_number=88,
            release_version="1.0.0.1",
            verdict="accepted",
            evidence={"per_platform": {}},
        )
        assert result["remote"] is True
        assert result["to"] == "closed"
        assert remote_on[-1] == ("POST", "/api/work-orders/acceptance")

    def test_find_by_issue_remotes(self, isolated_store: Path, remote_on: list) -> None:
        view = wo.find_by_issue(88)
        assert view is not None and view["status"] == "closed"
        assert ("GET", "/api/work-orders/by-issue/88") in remote_on


class TestRemoteFallback:
    def test_unavailable_falls_back_to_local(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WORK_ORDER_SSOT_DIR", str(tmp_path))
        monkeypatch.setattr(wo, "_STORE_DIR", tmp_path)
        monkeypatch.setattr(wo, "_EVENTS_FILE", tmp_path / "work_orders.jsonl")
        monkeypatch.setattr(wo, "_remote_enabled", lambda: True)

        def boom(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
            raise wo._RemoteUnavailable()

        monkeypatch.setattr(wo, "_remote_request", boom)
        result = wo.upsert_candidate(source="s", dedup_key="k-fb", reason="r")
        assert result["created"] is True
        assert "remote" not in result
        assert wo.list_work_orders() != []


class TestRemoteHttpRealPath:
    """经真实 _remote_request（urllib）验证成功/失败分支与远程开关读取。"""

    @staticmethod
    def _enable_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("WORK_ORDER_MARKET_BASE", "https://market.test")
        monkeypatch.setenv("WORK_ORDER_MARKET_TOKEN", "tok")
        monkeypatch.setenv("WORK_ORDER_SSOT_DIR", str(tmp_path))
        monkeypatch.setattr(wo, "_STORE_DIR", tmp_path)
        monkeypatch.setattr(wo, "_EVENTS_FILE", tmp_path / "work_orders.jsonl")

    def test_remote_enabled_detection(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._enable_env(monkeypatch, tmp_path)
        assert wo._remote_enabled() is True
        monkeypatch.delenv("WORK_ORDER_MARKET_TOKEN")
        monkeypatch.setenv("MARKET_ADMIN_TOKEN", "fallback")
        assert wo._remote_enabled() is True

    def test_success_response_returned(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._enable_env(monkeypatch, tmp_path)

        class _Resp:
            def __init__(self, payload: bytes) -> None:
                self._payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *_: Any) -> None:
                return None

            def read(self) -> bytes:
                return self._payload

        captured: dict[str, Any] = {}

        def fake_urlopen(req: Any, timeout: int = 15) -> _Resp:
            captured["url"] = req.full_url
            captured["token"] = req.get_header("Authorization")
            return _Resp(b'{"ok": true, "wo_id": "WO-x"}')

        monkeypatch.setattr(wo.urllib.request, "urlopen", fake_urlopen)
        result = wo._remote_request("POST", "/api/work-orders/transition", {"wo_id": "WO-x"})
        assert result == {"ok": True, "wo_id": "WO-x"}
        assert captured["url"] == "https://market.test/api/work-orders/transition"
        assert captured["token"] == "Bearer tok"

    def test_http_error_raises_remote_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._enable_env(monkeypatch, tmp_path)

        def fake_urlopen(req: Any, timeout: int = 15) -> Any:
            raise urllib.error.HTTPError(req.full_url, 403, "forbidden", {}, None)

        import urllib.error

        monkeypatch.setattr(wo.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(wo._RemoteUnavailable):
            wo._remote_request("GET", "/api/work-orders/WO-x")
