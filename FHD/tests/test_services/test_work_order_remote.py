# mypy: disable-error-code="no-any-return"
"""Shared/local Work Order persistence tests; all network calls are mocked."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.services import work_order_gate
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
        if path.startswith("/api/work-orders?"):
            return {"items": [{"wo_id": "WO-abcdef123456", "status": "routed"}]}
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
    "/api/work-orders/gate": {
        "ok": True,
    },
    "/api/work-orders/WO-abcdef123456": {
        "history": [
            {
                "event": "gate",
                "ref": {
                    "gate": "owner_instance",
                    "gate_status": "OWNER_INSTANCE_VERIFIED",
                    "evidence": {"sha256": "a" * 64},
                },
            }
        ],
    },
}


class TestRemoteDelegation:
    def test_upsert_candidate_delegates(self, isolated_store: Path, remote_on: list) -> None:
        result = wo.upsert_candidate(source="s", dedup_key="k-r1", reason="intent_unknown")
        assert result["remote"] is True
        assert result["wo_id"] == "WO-abcdef123456"
        assert result["created"] is True
        assert ("POST", "/api/work-orders/candidate") in remote_on
        assert wo.list_work_orders("routed", 999) == [
            {"wo_id": "WO-abcdef123456", "status": "routed"}
        ]
        assert remote_on[-1] == ("GET", "/api/work-orders?limit=500&status=routed")

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

    def test_gate_receipt_round_trips_through_shared_history(
        self, isolated_store: Path, remote_on: list
    ) -> None:
        result = work_order_gate.record_gate(
            "WO-abcdef123456",
            "owner_instance",
            "OWNER_INSTANCE_VERIFIED",
            evidence={"sha256": "a" * 64},
        )
        receipt = work_order_gate.gate_receipts("WO-abcdef123456")["owner_instance"]
        assert (
            result["ok"]
            and result["remote"]
            and receipt["gate_status"] == "OWNER_INSTANCE_VERIFIED"
        )
        assert receipt["evidence"] == {"sha256": "a" * 64}
        assert remote_on == [
            ("POST", "/api/work-orders/gate"),
            ("GET", "/api/work-orders/WO-abcdef123456"),
        ]

    def test_gate_receipt_fails_closed_when_shared_store_is_unavailable(
        self, isolated_store: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(wo, "_remote_enabled", lambda: True)

        def boom(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise wo._RemoteUnavailable()

        monkeypatch.setattr(wo, "_remote_request", boom)
        result = work_order_gate.record_gate("WO-abcdef123456", "repro", "RED")
        assert result["reason"] == "remote_unavailable" and wo.list_work_orders() == []


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
