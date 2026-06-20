"""mod_sdk compat 门面（neuro_bus / approval / lan / planner）mock 单测。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.requests import Request

from app.mod_sdk import approval_compat, lan_compat, neuro_bus_compat, planner_compat


def _http_request() -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


class TestNeuroBusCompat:
    def test_list_facade_registry_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_NEURO_BUS_VIA_MOD", raising=False)
        monkeypatch.delenv("XCAGI_DISABLE_NEURO_BUS_MOD", raising=False)
        with patch.object(neuro_bus_compat, "is_neuro_bus_via_mod_enabled", return_value=False):
            reg = neuro_bus_compat.list_neuro_bus_facade_registry()
        assert reg["success"] is True
        assert reg["mod_id"] == neuro_bus_compat.NEURO_BUS_BRIDGE_MOD_ID
        assert reg["endpoint_count"] == len(reg["endpoints"])
        assert "GET /neurobus/health" in reg["endpoints"]

    def test_via_mod_enabled_env_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_NEURO_BUS_VIA_MOD", "1")
        assert neuro_bus_compat.is_neuro_bus_via_mod_enabled() is True

    def test_via_mod_disabled_env_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DISABLE_NEURO_BUS_MOD", "true")
        assert neuro_bus_compat.is_neuro_bus_via_mod_enabled() is False

    def test_is_mod_installed_from_manager(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mm = MagicMock()
        mm.list_all_mods.return_value = [{"id": neuro_bus_compat.NEURO_BUS_BRIDGE_MOD_ID}]
        with (
            patch("app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mm),
            patch("app.infrastructure.mods.mod_manager.is_mods_disabled", return_value=False),
        ):
            assert neuro_bus_compat.is_neuro_bus_mod_installed() is True


class TestApprovalCompat:
    def test_list_facade_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_APPROVAL_VIA_MOD", raising=False)
        with patch.object(approval_compat, "is_approval_via_mod_enabled", return_value=False):
            reg = approval_compat.list_approval_facade_registry()
        assert reg["facade_prefix"] == approval_compat.FACADE_PREFIX
        assert reg["execution_path"] == "host.api"
        assert "POST /requests" in reg["endpoints"]

    def test_approval_via_mod_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_APPROVAL_VIA_MOD", "yes")
        assert approval_compat.is_approval_via_mod_enabled() is True


class TestLanCompat:
    def test_list_lan_facade_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_LAN_VIA_MOD", raising=False)
        with patch.object(lan_compat, "is_lan_via_mod_enabled", return_value=False):
            reg = lan_compat.list_lan_facade_registry()
        assert reg["phase"] == "J"
        assert "GET /lan/status" in reg["endpoints"]

    def test_lan_mod_installed_disk_fallback(self, tmp_path: Path) -> None:
        mod_dir = tmp_path / lan_compat.LAN_BRIDGE_MOD_ID
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(
            '{"id":"xcagi-lan-license-bridge"}', encoding="utf-8"
        )
        with (
            patch(
                "app.infrastructure.mods.mod_manager.get_mod_manager",
                side_effect=RuntimeError("no mgr"),
            ),
            patch.object(lan_compat, "_resolve_mod_dir", return_value=mod_dir),
        ):
            assert lan_compat.is_lan_mod_installed() is True


class TestPlannerCompat:
    @pytest.mark.asyncio
    async def test_chat_delegates_execute(self) -> None:
        req = _http_request()
        with patch(
            "app.mod_sdk.planner_compat.execute_compat_chat",
            new_callable=AsyncMock,
            return_value={"success": True, "response": "ok"},
        ) as mock_exec:
            out = await planner_compat.chat(req, {"message": "你好"})
        mock_exec.assert_awaited_once()
        assert out["success"] is True

    def test_intent_test_empty_message(self) -> None:
        out = planner_compat.intent_test({"message": "  "})
        assert out.status_code == 400

    def test_intent_test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.application.ai_chat_helpers.recognize_intents",
            lambda msg: [{"intent": "greeting", "confidence": 0.9}],
        )
        out = planner_compat.intent_test({"message": "你好"})
        assert out["success"] is True
        assert out["data"][0]["intent"] == "greeting"

    def test_list_planner_tools_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "app.mod_sdk.planner_tools.list_planner_tools_registry_detail",
            lambda: {"tools": ["price_list"]},
        )
        reg = planner_compat.list_planner_tools_registry()
        assert reg["tools"] == ["price_list"]

    def test_resolve_ai_tier_for_request(self) -> None:
        req = _http_request()
        with patch("app.domain.ai.tier.resolve_ai_tier", return_value="p1"):
            assert planner_compat.resolve_ai_tier_for_request(req) == "p1"
