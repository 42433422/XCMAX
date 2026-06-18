"""COVERAGE_RAMP Phase 6 round 5: backend low-coverage modules.

Targets:
- ``app/mod_sdk/mod_employee_llm.py`` (~12.8% line coverage, 75 lines uncovered)
- ``app/infrastructure/db/sync_engine.py`` (~52.6% line coverage, 73 lines uncovered)

Tests follow the phase-4 style: ``from __future__ import annotations``,
``unittest.mock`` + ``pytest``, mock only external boundaries (HTTP client,
LLM service, DB engine creation). Internal logic of the units under test is
exercised for real.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.infrastructure.db import sync_engine
from app.mod_sdk import mod_employee_llm

# ===========================================================================
# 1. mod_employee_llm — _resolve_provider_override
# ===========================================================================


class TestResolveProviderOverride:
    """``_resolve_provider_override`` 解析逻辑。"""

    def test_no_provider_returns_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_LLM_PROVIDER", raising=False)
        out = mod_employee_llm._resolve_provider_override()
        assert out == {"use_direct": False}

    def test_empty_provider_returns_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "   ")
        out = mod_employee_llm._resolve_provider_override()
        assert out == {"use_direct": False}

    def test_provider_without_api_key_returns_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "deepseek")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        out = mod_employee_llm._resolve_provider_override()
        assert out == {"use_direct": False}

    def test_provider_with_key_uses_default_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-abc")
        monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
        monkeypatch.delenv("XCAGI_EMPLOYEE_LLM_MODEL", raising=False)
        out = mod_employee_llm._resolve_provider_override()
        assert out["use_direct"] is True
        assert out["api_key"] == "sk-abc"
        assert "deepseek.com" in out["chat_url"]
        assert out["model"] == "deepseek-chat"
        assert out["provider"] == "deepseek"

    def test_openai_provider_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-xyz")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("OPENAI_MODEL", raising=False)
        monkeypatch.delenv("XCAGI_EMPLOYEE_LLM_MODEL", raising=False)
        out = mod_employee_llm._resolve_provider_override()
        assert out["use_direct"] is True
        assert out["model"] == "gpt-4o-mini"

    def test_custom_base_url_with_chat_completions_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "custom")
        monkeypatch.setenv("CUSTOM_API_KEY", "k1")
        monkeypatch.setenv("CUSTOM_BASE_URL", "https://llm.example.com/v1/chat/completions")
        monkeypatch.delenv("CUSTOM_MODEL", raising=False)
        monkeypatch.setenv("XCAGI_EMPLOYEE_LLM_MODEL", "my-model")
        out = mod_employee_llm._resolve_provider_override()
        assert out["use_direct"] is True
        assert out["chat_url"] == "https://llm.example.com/v1/chat/completions"
        assert out["model"] == "my-model"

    def test_custom_base_url_without_chat_path_appends_v1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "custom")
        monkeypatch.setenv("CUSTOM_API_KEY", "k1")
        monkeypatch.setenv("CUSTOM_BASE_URL", "https://llm.example.com/")
        monkeypatch.delenv("CUSTOM_MODEL", raising=False)
        monkeypatch.delenv("XCAGI_EMPLOYEE_LLM_MODEL", raising=False)
        out = mod_employee_llm._resolve_provider_override()
        assert out["use_direct"] is True
        assert out["chat_url"] == "https://llm.example.com/v1/chat/completions"

    def test_unknown_provider_without_base_url_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "unknownprov")
        monkeypatch.setenv("UNKNOWNPROV_API_KEY", "k1")
        monkeypatch.delenv("UNKNOWNPROV_BASE_URL", raising=False)
        out = mod_employee_llm._resolve_provider_override()
        assert out["use_direct"] is False
        assert "error" in out
        assert "UNKNOWNPROV_BASE_URL" in out["error"]

    def test_provider_model_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "k1")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-4-turbo")
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("XCAGI_EMPLOYEE_LLM_MODEL", raising=False)
        out = mod_employee_llm._resolve_provider_override()
        assert out["model"] == "gpt-4-turbo"


# ===========================================================================
# 2. mod_employee_llm — _parse_chat_completions_response
# ===========================================================================


class TestParseChatCompletionsResponse:
    """``_parse_chat_completions_response`` 解析逻辑。"""

    def test_happy_path_returns_content(self) -> None:
        raw = {
            "choices": [
                {"message": {"content": "hello world"}},
            ]
        }
        out = mod_employee_llm._parse_chat_completions_response(raw)
        assert out == {"success": True, "content": "hello world", "error": ""}

    def test_empty_choices_returns_error(self) -> None:
        out = mod_employee_llm._parse_chat_completions_response({"choices": []})
        assert out["success"] is False
        assert "choices" in out["error"]

    def test_missing_choices_returns_error(self) -> None:
        out = mod_employee_llm._parse_chat_completions_response({})
        assert out["success"] is False
        assert "choices" in out["error"]

    def test_missing_message_returns_error(self) -> None:
        out = mod_employee_llm._parse_chat_completions_response({"choices": [{}]})
        assert out["success"] is False
        assert "message.content" in out["error"]

    def test_none_content_returns_error(self) -> None:
        out = mod_employee_llm._parse_chat_completions_response(
            {"choices": [{"message": {"content": None}}]}
        )
        assert out["success"] is False
        assert "message.content" in out["error"]

    def test_non_dict_input_raises_typeerror_caught(self) -> None:
        # ``raw.get`` on a list raises AttributeError, which is NOT in
        # RECOVERABLE_ERRORS (programming bug) — verify behavior is to raise.
        with pytest.raises(AttributeError):
            mod_employee_llm._parse_chat_completions_response(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_content_is_stringified(self) -> None:
        out = mod_employee_llm._parse_chat_completions_response(
            {"choices": [{"message": {"content": 42}}]}
        )
        assert out["success"] is True
        assert out["content"] == "42"


# ===========================================================================
# 3. mod_employee_llm — _call_openai_compatible_chat
# ===========================================================================


class TestCallOpenAICompatibleChat:
    """``_call_openai_compatible_chat`` 直连 HTTP 路径。"""

    @pytest.mark.asyncio
    async def test_happy_path_returns_json(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            out = await mod_employee_llm._call_openai_compatible_chat(
                [{"role": "user", "content": "hi"}],
                api_key="k1",
                chat_url="https://x.example.com/v1/chat/completions",
                model="m1",
                max_tokens=128,
                temperature=0.1,
                response_format=None,
            )
        assert out == {"choices": [{"message": {"content": "ok"}}]}
        # 验证 payload 不含 response_format
        call_kwargs = mock_client.post.call_args.kwargs
        assert "response_format" not in call_kwargs["json"]

    @pytest.mark.asyncio
    async def test_response_format_propagated_to_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await mod_employee_llm._call_openai_compatible_chat(
                [{"role": "user", "content": "hi"}],
                api_key="k1",
                chat_url="https://x.example.com/v1/chat/completions",
                model="m1",
                max_tokens=128,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["json"]["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_recoverable_http_error_returns_none(self) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("network down"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            out = await mod_employee_llm._call_openai_compatible_chat(
                [{"role": "user", "content": "hi"}],
                api_key="k1",
                chat_url="https://x.example.com/v1/chat/completions",
                model="m1",
                max_tokens=128,
                temperature=0.1,
                response_format=None,
            )
        assert out is None

    @pytest.mark.asyncio
    async def test_timeout_error_returns_none(self) -> None:
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ReadTimeout("slow"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            out = await mod_employee_llm._call_openai_compatible_chat(
                [{"role": "user", "content": "hi"}],
                api_key="k1",
                chat_url="https://x.example.com/v1/chat/completions",
                model="m1",
                max_tokens=128,
                temperature=0.1,
                response_format=None,
            )
        assert out is None


# ===========================================================================
# 4. mod_employee_llm — mod_employee_complete (top-level)
# ===========================================================================


class TestModEmployeeComplete:
    """``mod_employee_complete`` 顶层入口。"""

    @pytest.mark.asyncio
    async def test_empty_messages_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_LLM_PROVIDER", raising=False)
        out = await mod_employee_llm.mod_employee_complete([])
        assert out["success"] is False
        assert "非空列表" in out["error"]

    @pytest.mark.asyncio
    async def test_non_list_messages_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_LLM_PROVIDER", raising=False)
        out = await mod_employee_llm.mod_employee_complete("not a list")  # type: ignore[arg-type]
        assert out["success"] is False
        assert "非空列表" in out["error"]

    @pytest.mark.asyncio
    async def test_override_error_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "unknownprov")
        monkeypatch.setenv("UNKNOWNPROV_API_KEY", "k1")
        monkeypatch.delenv("UNKNOWNPROV_BASE_URL", raising=False)
        out = await mod_employee_llm.mod_employee_complete([{"role": "user", "content": "hi"}])
        assert out["success"] is False
        assert "UNKNOWNPROV_BASE_URL" in out["error"]

    @pytest.mark.asyncio
    async def test_direct_path_returns_empty_when_llm_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-abc")
        monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
        monkeypatch.delenv("XCAGI_EMPLOYEE_LLM_MODEL", raising=False)

        with patch.object(
            mod_employee_llm, "_call_openai_compatible_chat", new=AsyncMock(return_value=None)
        ):
            out = await mod_employee_llm.mod_employee_complete([{"role": "user", "content": "hi"}])
        assert out["success"] is False
        assert "LLM 返回空" in out["error"]

    @pytest.mark.asyncio
    async def test_direct_path_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "deepseek")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-abc")
        monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
        monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
        monkeypatch.delenv("XCAGI_EMPLOYEE_LLM_MODEL", raising=False)

        raw = {"choices": [{"message": {"content": "answer"}}]}
        with patch.object(
            mod_employee_llm,
            "_call_openai_compatible_chat",
            new=AsyncMock(return_value=raw),
        ):
            out = await mod_employee_llm.mod_employee_complete(
                [{"role": "user", "content": "hi"}],
                response_format={"type": "json_object"},
            )
        assert out["success"] is True
        assert out["content"] == "answer"

    @pytest.mark.asyncio
    async def test_default_path_no_api_key_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XCAGI_LLM_PROVIDER", raising=False)

        mock_svc = MagicMock()
        mock_svc.api_key = None
        with patch(
            "app.services.ai_conversation_service.get_ai_conversation_service",
            return_value=mock_svc,
        ):
            out = await mod_employee_llm.mod_employee_complete([{"role": "user", "content": "hi"}])
        assert out["success"] is False
        assert "DEEPSEEK_API_KEY" in out["error"]

    @pytest.mark.asyncio
    async def test_default_path_call_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_LLM_PROVIDER", raising=False)

        mock_svc = MagicMock()
        mock_svc.api_key = "sk-host"
        mock_svc.call_deepseek_api = AsyncMock(return_value=None)
        with patch(
            "app.services.ai_conversation_service.get_ai_conversation_service",
            return_value=mock_svc,
        ):
            out = await mod_employee_llm.mod_employee_complete([{"role": "user", "content": "hi"}])
        assert out["success"] is False
        assert "LLM 返回空" in out["error"]

    @pytest.mark.asyncio
    async def test_default_path_recoverable_error_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XCAGI_LLM_PROVIDER", raising=False)

        mock_svc = MagicMock()
        mock_svc.api_key = "sk-host"
        mock_svc.call_deepseek_api = AsyncMock(side_effect=ConnectionError("db down"))
        with patch(
            "app.services.ai_conversation_service.get_ai_conversation_service",
            return_value=mock_svc,
        ):
            out = await mod_employee_llm.mod_employee_complete([{"role": "user", "content": "hi"}])
        assert out["success"] is False
        assert "db down" in out["error"]

    @pytest.mark.asyncio
    async def test_default_path_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_LLM_PROVIDER", raising=False)

        mock_svc = MagicMock()
        mock_svc.api_key = "sk-host"
        mock_svc.call_deepseek_api = AsyncMock(
            return_value={"choices": [{"message": {"content": "host-reply"}}]}
        )
        with patch(
            "app.services.ai_conversation_service.get_ai_conversation_service",
            return_value=mock_svc,
        ):
            out = await mod_employee_llm.mod_employee_complete(
                [{"role": "user", "content": "hi"}],
                response_format={"type": "json_object"},
            )
        assert out["success"] is True
        assert out["content"] == "host-reply"
        # 验证 response_format 透传到 kwargs
        call_kwargs = mock_svc.call_deepseek_api.call_args.kwargs
        assert call_kwargs["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_default_path_import_error_returns_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XCAGI_LLM_PROVIDER", raising=False)

        # 模拟 `from app.services.ai_conversation_service import get_ai_conversation_service`
        # 抛 ImportError：让模块缺少该属性，Python 会把 AttributeError 转为 ImportError。
        import sys
        import types

        fake_mod = types.ModuleType("app.services.ai_conversation_service")
        # 不设置 get_ai_conversation_service 属性
        monkeypatch.setitem(sys.modules, "app.services.ai_conversation_service", fake_mod)

        out = await mod_employee_llm.mod_employee_complete([{"role": "user", "content": "hi"}])
        assert out["success"] is False
        assert "not available" in out["error"]


# ===========================================================================
# 5. sync_engine — mode / path resolution
# ===========================================================================


class TestSyncEngineMode:
    """``set_mode`` / ``resolve_mode`` / 路径解析。"""

    def teardown_method(self) -> None:
        # 恢复 production 模式，避免污染其他测试
        sync_engine.set_mode("production")

    def test_set_mode_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="mode must be"):
            sync_engine.set_mode("staging")

    def test_set_mode_production_resets_engine(self) -> None:
        sync_engine.set_mode("production")
        assert sync_engine.resolve_mode() == "production"

    def test_set_mode_test_resets_engine(self) -> None:
        sync_engine.set_mode("test")
        assert sync_engine.resolve_mode() == "test"

    def test_sqlite_path_for_mode_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/xctest_ws")
        p = sync_engine._sqlite_path_for_mode("production")
        assert p.name == "products.db"

    def test_sqlite_path_for_mode_test(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/xctest_ws")
        p = sync_engine._sqlite_path_for_mode("test")
        assert p.name == "products_test.db"

    def test_resolve_customer_db_path_reflects_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/xctest_ws")
        sync_engine.set_mode("test")
        p = sync_engine.resolve_customer_db_path()
        assert p.name == "products_test.db"
        sync_engine.set_mode("production")
        p2 = sync_engine.resolve_customer_db_path()
        assert p2.name == "products.db"


# ===========================================================================
# 6. sync_engine — _database_url_for_mode / get_database_url
# ===========================================================================


class TestSyncEngineDatabaseUrl:
    """数据库 URL 解析。"""

    def test_database_url_for_mode_uses_env_url_when_not_pytest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # PYTEST_CURRENT_TEST 在 pytest 内会被设置，因此这里走 sqlite 分支
        # 但我们直接验证 env_url 优先级：通过显式 unset PYTEST_CURRENT_TEST
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
        url = sync_engine._database_url_for_mode("production")
        assert url == "postgresql+psycopg://u:p@h:5432/db"

    def test_database_url_for_mode_falls_back_to_sqlite(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        url = sync_engine._database_url_for_mode("production")
        assert url.startswith("sqlite:///")
        assert "products.db" in url

    def test_database_url_for_mode_test_uses_test_db_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        url = sync_engine._database_url_for_mode("test")
        assert "products_test.db" in url

    def test_get_database_url_raises_when_gate_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("FHD_DB_MOD_GATE", "mod-a,mod-b")
        monkeypatch.delenv("FHD_ENABLED_MOD_IDS", raising=False)
        with pytest.raises(RuntimeError, match="database_mod_gate_closed"):
            sync_engine.get_database_url()

    def test_get_database_url_returns_base_when_pytest(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # 在 pytest 中，gate 默认 open，返回 sqlite base url
        monkeypatch.delenv("FHD_DB_MOD_GATE", raising=False)
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        url = sync_engine.get_database_url()
        assert url.startswith("sqlite:///")


# ===========================================================================
# 7. sync_engine — get_read_database_url
# ===========================================================================


class TestSyncEngineReadUrl:
    """``get_read_database_url`` 读副本 URL 解析。"""

    def test_no_read_url_falls_back_to_primary(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("DATABASE_READ_URL", raising=False)
        monkeypatch.delenv("FHD_DB_MOD_GATE", raising=False)
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        primary = sync_engine.get_database_url()
        read = sync_engine.get_read_database_url()
        assert read == primary

    def test_sqlite_primary_ignores_read_url(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("DATABASE_READ_URL", "postgresql://r:r@h:5432/rdb")
        monkeypatch.delenv("FHD_DB_MOD_GATE", raising=False)
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        primary = sync_engine.get_database_url()
        assert primary.startswith("sqlite:")
        read = sync_engine.get_read_database_url()
        assert read == primary


# ===========================================================================
# 8. sync_engine — _urls_equivalent
# ===========================================================================


class TestUrlsEquivalent:
    """``_urls_equivalent`` URL 等价比较。"""

    def test_none_a_returns_false(self) -> None:
        assert sync_engine._urls_equivalent(None, "sqlite:///x") is False

    def test_same_url_returns_true(self) -> None:
        assert sync_engine._urls_equivalent("sqlite:///x", "sqlite:///x") is True

    def test_different_url_returns_false(self) -> None:
        assert sync_engine._urls_equivalent("sqlite:///a", "sqlite:///b") is False

    def test_password_hidden_comparison(self) -> None:
        # render_as_string(hide_password=True) 应让带密码的 URL 等价
        a = "postgresql://u:secret@h:5432/db"
        b = "postgresql://u:secret@h:5432/db"
        assert sync_engine._urls_equivalent(a, b) is True


# ===========================================================================
# 9. sync_engine — get_sync_engine / get_read_sync_engine / dispose
# ===========================================================================


class TestSyncEngineEngines:
    """``get_sync_engine`` / ``get_read_sync_engine`` / ``dispose_sync_engine``。"""

    def teardown_method(self) -> None:
        sync_engine.dispose_sync_engine()
        sync_engine.set_mode("production")

    def test_get_sync_engine_pytest_reuses_engine(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.delenv("FHD_DB_MOD_GATE", raising=False)
        e1 = sync_engine.get_sync_engine()
        e2 = sync_engine.get_sync_engine()
        assert e1 is e2

    def test_dispose_sync_engine_clears_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.delenv("FHD_DB_MOD_GATE", raising=False)
        e1 = sync_engine.get_sync_engine()
        sync_engine.dispose_sync_engine()
        assert sync_engine._engine is None
        assert sync_engine._bound_engine_url is None
        assert sync_engine._read_engine is None
        assert sync_engine._bound_read_engine_url is None

    def test_get_read_sync_engine_returns_engine(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.delenv("FHD_DB_MOD_GATE", raising=False)
        monkeypatch.delenv("DATABASE_READ_URL", raising=False)
        e = sync_engine.get_read_sync_engine()
        assert e is not None
        # sqlite 引擎应能 dispose
        sync_engine.dispose_sync_engine()


# ===========================================================================
# 10. sync_engine — get_read_session context manager
# ===========================================================================


class TestSyncEngineReadSession:
    """``get_read_session`` 上下文管理器。"""

    def test_get_read_session_yields_session(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        monkeypatch.delenv("FHD_DB_MOD_GATE", raising=False)
        monkeypatch.delenv("DATABASE_READ_URL", raising=False)
        sync_engine.dispose_sync_engine()
        with sync_engine.get_read_session() as session:
            assert session is not None
            # session 应能执行简单查询
            from sqlalchemy import text

            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1
        sync_engine.dispose_sync_engine()


# ===========================================================================
# 11. sync_engine — redact_database_url
# ===========================================================================


class TestRedactDatabaseUrl:
    """``redact_database_url`` 密码脱敏。"""

    def test_no_password_returns_unchanged(self) -> None:
        assert sync_engine.redact_database_url("sqlite:///x.db") == "sqlite:///x.db"

    def test_password_redacted(self) -> None:
        out = sync_engine.redact_database_url("postgresql://u:secret@h:5432/db")
        assert "secret" not in out
        assert "***" in out
        assert "u" in out
        assert "h" in out

    def test_password_with_port_redacted(self) -> None:
        out = sync_engine.redact_database_url("postgresql://u:p@h:6543/db")
        assert "p" not in out.replace("postgresql", "").replace("6543", "")
        assert "***" in out
        assert "6543" in out

    def test_empty_url_returns_unchanged(self) -> None:
        assert sync_engine.redact_database_url("") == ""

    def test_invalid_url_returns_unchanged(self) -> None:
        # 不是合法 URL，urlparse 仍能解析但无 password
        out = sync_engine.redact_database_url("not a url at all")
        assert out == "not a url at all"


# ===========================================================================
# 12. sync_engine — get_db_status
# ===========================================================================


class TestGetDbStatus:
    """``get_db_status`` 状态汇总。"""

    def test_gate_closed_returns_closed_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FHD_DB_MOD_GATE", "mod-x")
        monkeypatch.delenv("FHD_ENABLED_MOD_IDS", raising=False)
        status = sync_engine.get_db_status()
        assert status["database_mod_gate_closed"] is True
        assert status["database_url"] is None
        assert status["current_db"] is None
        assert "mod_database_gate" in status

    def test_gate_open_returns_full_status(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("FHD_DB_MOD_GATE", raising=False)
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        status = sync_engine.get_db_status()
        # gate_open 时无 database_mod_gate_closed 字段
        assert status.get("database_mod_gate_closed", False) is False
        assert "database_url" in status
        assert "current_db" in status
        assert "current_db_name" in status
        assert "production_db" in status
        assert "test_db" in status
        assert "postgresql_summary" in status
        assert "mod_database_gate" in status
        # sqlite 路径下 backend 应为 sqlite
        assert status["backend"] in ("sqlite", "postgresql")


# ===========================================================================
# 13. sync_engine — postgresql_connection_summary
# ===========================================================================


class TestPostgresqlConnectionSummary:
    """``postgresql_connection_summary`` PG 连接摘要。"""

    def test_postgres_url_summary(self) -> None:
        out = sync_engine.postgresql_connection_summary(
            "postgresql+psycopg://u:p@host.example:5432/mydb"
        )
        assert out["database_name"] == "mydb"
        assert "host.example" in out["host_port"]
        assert "5432" in out["host_port"]
        # 密码应被脱敏为 ***
        assert "***" in out["redacted_url"]
        assert ":p@" not in out["redacted_url"]

    def test_postgres_url_no_port(self) -> None:
        out = sync_engine.postgresql_connection_summary("postgresql://u:p@host.example/mydb2")
        assert out["database_name"] == "mydb2"
        assert "host.example" in out["host_port"]

    def test_postgres_url_empty_path(self) -> None:
        out = sync_engine.postgresql_connection_summary("postgresql://u:p@host.example:5432/")
        assert out["database_name"] == ""


# ===========================================================================
# 14. sync_engine — switch_to_production_mode / switch_to_test_mode
# ===========================================================================


class TestSwitchMode:
    """``switch_to_production_mode`` / ``switch_to_test_mode``。"""

    def teardown_method(self) -> None:
        sync_engine.set_mode("production")

    def test_switch_to_production(self) -> None:
        sync_engine.set_mode("test")
        out = sync_engine.switch_to_production_mode()
        assert out == {"success": True, "mode": "production"}
        assert sync_engine.resolve_mode() == "production"

    def test_switch_to_test(self) -> None:
        out = sync_engine.switch_to_test_mode()
        assert out == {"success": True, "mode": "test"}
        assert sync_engine.resolve_mode() == "test"


# ===========================================================================
# 15. sync_engine — reset_test_db
# ===========================================================================


class TestResetTestDb:
    """``reset_test_db`` 测试库重置。"""

    def test_reset_test_db_when_file_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        out = sync_engine.reset_test_db()
        assert out["success"] is True
        assert out["mode"] == "test"
        assert "products_test.db" in out["path"]

    def test_reset_test_db_removes_existing_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        # 先创建文件
        p = sync_engine._sqlite_path_for_mode("test")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("dummy")
        assert p.exists()
        out = sync_engine.reset_test_db()
        assert out["success"] is True
        assert not p.exists()

    def test_reset_test_db_os_error_returns_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
        p = sync_engine._sqlite_path_for_mode("test")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("dummy")

        # 让 unlink 抛 OSError
        original_unlink = Path.unlink

        def raising_unlink(self: Path, *args: object, **kwargs: object) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "unlink", raising_unlink)
        try:
            out = sync_engine.reset_test_db()
            assert out["success"] is False
            assert out["error"] is True
            assert "failed to remove" in out["message"]
        finally:
            monkeypatch.setattr(Path, "unlink", original_unlink)
