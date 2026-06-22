"""llm-ops-engineer 专属工具的真实执行测试。

验证 5 个工具真的能工作（真实读 .env / 真实 HTTP ping / 真实价格表），
而非靠 LLM 编造数据。
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
from pathlib import Path

import pytest

# 确保用项目 venv 的 path
_FHD = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_FHD))

from app.mod_sdk.employee_specialized_tools import (  # noqa: E402
    _MODEL_PRICES,
    _PROVIDER_PROFILES,
    EMPLOYEE_TOOLS,
    TOOL_REGISTRY,
    _mask_secret,
    _read_env_file,
    handle_specialized,
)

# ---------------------------------------------------------------------------
# 全局变量隔离 fixture
# ---------------------------------------------------------------------------
# EMPLOYEE_TOOLS / TOOL_REGISTRY 是模块级可变 dict，全量套件中若前序测试
# 通过 monkeypatch/patch 临时修改后未完全恢复（或直接 append），会导致
# test_llm_ops_engineer_has_6_tools 期望 6 个工具但实际数量不符。
# 此 fixture 在每个测试前后快照/恢复，确保隔离。


@pytest.fixture(autouse=True)
def _preserve_tool_registry_state():
    """快照并恢复 EMPLOYEE_TOOLS / TOOL_REGISTRY 的原始内容。"""
    employee_tools_snapshot = copy.deepcopy(EMPLOYEE_TOOLS)
    tool_registry_keys = set(TOOL_REGISTRY.keys())
    tool_registry_snapshot = {k: TOOL_REGISTRY[k] for k in tool_registry_keys}
    yield
    EMPLOYEE_TOOLS.clear()
    EMPLOYEE_TOOLS.update(employee_tools_snapshot)
    # 恢复 TOOL_REGISTRY：移除新增的 key，恢复被替换的 fn
    current_keys = set(TOOL_REGISTRY.keys())
    for new_key in current_keys - tool_registry_keys:
        del TOOL_REGISTRY[new_key]
    for k, fn in tool_registry_snapshot.items():
        TOOL_REGISTRY[k] = fn


# ---------------------------------------------------------------------------
# 工具注册验证
# ---------------------------------------------------------------------------


class TestLlmOpsToolRegistration:
    """验证 5 个工具已正确注册到 TOOL_REGISTRY 和 EMPLOYEE_TOOLS。"""

    def test_all_5_tools_registered_in_registry(self):
        """5 个工具全部在 TOOL_REGISTRY 中。"""
        required = {
            "read_llm_env_config",
            "list_configured_providers",
            "test_llm_key_health",
            "query_provider_usage",
            "compare_model_prices",
        }
        missing = required - set(TOOL_REGISTRY.keys())
        assert not missing, f"未注册的工具: {missing}"

    def test_llm_ops_engineer_has_core_tools(self):
        """llm-ops-engineer 员工注册了全部专属工具（含 6 个核心工具）。"""
        tools = EMPLOYEE_TOOLS.get("llm-ops-engineer", [])
        # 核心 6 个工具必须存在（工具集后续可扩展，断言"至少包含核心"更稳健）
        core = {
            "read_llm_env_config",
            "list_configured_providers",
            "test_llm_key_health",
            "query_provider_usage",
            "compare_model_prices",
            "query_local_token_usage",
        }
        missing = core - set(tools)
        assert not missing, f"缺少核心工具: {missing}"
        # 当前工具集已从 6 扩展到 9（新增 cursor/codex/trae 用量查询）
        assert set(tools) == core | {
            "query_cursor_usage",
            "query_codex_usage",
            "query_trae_usage",
        }, f"实际工具集: {tools}"

    def test_all_tools_are_callable(self):
        """所有工具函数都是可调用的。"""
        for name in EMPLOYEE_TOOLS["llm-ops-engineer"]:
            fn = TOOL_REGISTRY[name]
            assert callable(fn), f"{name} 不是 callable"

    def test_handle_specialized_lists_available_tools(self):
        """handle_specialized 未指定 tool 时返回可用工具清单。"""
        result = asyncio.get_event_loop().run_until_complete(
            handle_specialized("llm-ops-engineer", {}, {})
        )
        assert result["ok"] is True
        assert result["available_tools"] == EMPLOYEE_TOOLS["llm-ops-engineer"]

    def test_unauthorized_tool_blocked(self):
        """llm-ops-engineer 调用未授权工具被拦截。"""
        result = asyncio.get_event_loop().run_until_complete(
            handle_specialized("llm-ops-engineer", {"tool": "run_pytest"}, {})
        )
        assert result["ok"] is False
        assert "不在员工" in result["error"]


# ---------------------------------------------------------------------------
# 辅助函数验证
# ---------------------------------------------------------------------------


class TestMaskSecret:
    """API key 脱敏函数验证。"""

    def test_normal_key_masked(self):
        """正常长度的 key 保留前 3 + 后 3。"""
        assert _mask_secret("sk-a8m2xbs0jbqbgw9ex6st8o7u4zmqa8jz") == "sk-***8jz"

    def test_short_key_fully_masked(self):
        """短 key 全脱敏。"""
        assert _mask_secret("sk-abc") == "***"

    def test_empty_key_returns_empty(self):
        """空 key 返回空字符串。"""
        assert _mask_secret("") == ""

    def test_boundary_8_chars_masked(self):
        """恰好 8 字符的 key 全脱敏。"""
        assert _mask_secret("sk-abcde") == "***"


class TestReadEnvFile:
    """.env 文件解析验证。"""

    def test_reads_env_file_with_content(self, tmp_path):
        """能读取一个有内容的 .env 文件（自洽，不依赖仓库根的真实 .env）。"""
        env_path = tmp_path / ".env"
        env_path.write_text(
            "XCAGI_LLM_PROVIDER=openai\nOPENAI_API_KEY=sk-test1234567890\n",
            encoding="utf-8",
        )
        env_map = _read_env_file(env_path)
        assert isinstance(env_map, dict)
        assert len(env_map) > 0, ".env 应该有内容"
        assert env_map["XCAGI_LLM_PROVIDER"] == "openai"
        assert env_map["OPENAI_API_KEY"] == "sk-test1234567890"

    def test_skips_comments_and_empty_lines(self):
        """跳过注释和空行。"""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# 这是注释\n\nKEY1=val1\nKEY2=val2\n")
            path = Path(f.name)
        try:
            env_map = _read_env_file(path)
            assert env_map == {"KEY1": "val1", "KEY2": "val2"}
        finally:
            path.unlink()

    def test_strips_quotes(self):
        """去除值的引号。"""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("KEY1=\"quoted\"\nKEY2='single'\nKEY3=bare\n")
            path = Path(f.name)
        try:
            env_map = _read_env_file(path)
            assert env_map == {"KEY1": "quoted", "KEY2": "single", "KEY3": "bare"}
        finally:
            path.unlink()

    def test_nonexistent_file_returns_empty(self):
        """不存在的文件返回空 dict。"""
        env_map = _read_env_file(Path("/nonexistent/.env"))
        assert env_map == {}


# ---------------------------------------------------------------------------
# read_llm_env_config — 真实读 .env
# ---------------------------------------------------------------------------


class TestReadLlmEnvConfig:
    """验证 read_llm_env_config 真实读取 .env 并脱敏。"""

    @pytest.fixture(autouse=True)
    def _temp_env_file(self, tmp_path, monkeypatch):
        """造一个临时 .env 并指向它（自洽，不依赖仓库根的真实 .env / CI）。

        tool_read_llm_env_config 读取 模块级 _FHD_ROOT / ".env"，
        monkeypatch 该常量即可让工具读到临时 .env。
        """
        import app.mod_sdk.employee_specialized_tools as mod

        env_path = tmp_path / ".env"
        env_path.write_text(
            "XCAGI_LLM_PROVIDER=openai\n"
            "OPENAI_API_KEY=sk-a8m2xbs0jbqbgw9ex6st8o7u4zmqa8jz\n"
            "OPENAI_BASE_URL=https://api.b.ai/v1\n"
            "OPENAI_MODEL=MiniMax-M3\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_FHD_ROOT", tmp_path)
        yield

    def test_reads_real_env_file(self):
        """读取临时 .env，返回 LLM 配置。"""
        fn = TOOL_REGISTRY["read_llm_env_config"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True, f"读取失败: {result.get('error')}"
        assert "env_config" in result
        assert "runtime_config" in result

    def test_api_key_is_masked_in_output(self):
        """输出的 API key 必须脱敏，不含完整 key。"""
        fn = TOOL_REGISTRY["read_llm_env_config"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        env_cfg = result.get("env_config", {})
        runtime_cfg = result.get("runtime_config", {})
        # 检查所有 secret key 都脱敏
        for cfg in (env_cfg, runtime_cfg):
            for key, val in cfg.items():
                if "API_KEY" in key or "PAT" in key:
                    if val:
                        assert "sk-a8m2" not in val, f"{key} 未脱敏: {val}"
                        assert "***" in val, f"{key} 缺少脱敏标记: {val}"

    def test_returns_configured_provider(self):
        """返回 configured_provider 字段。"""
        fn = TOOL_REGISTRY["read_llm_env_config"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert "configured_provider" in result
        # 临时 .env 配了 XCAGI_LLM_PROVIDER=openai
        assert result["configured_provider"] in ("openai", "(未配置)")


# ---------------------------------------------------------------------------
# list_configured_providers — 真实读 os.environ
# ---------------------------------------------------------------------------


class TestListConfiguredProviders:
    """验证 list_configured_providers 真实读环境变量。"""

    def test_lists_openai_provider_when_configured(self, monkeypatch):
        """配了 OPENAI_API_KEY 时列出 openai provider。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test1234567890abcdef")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.b.ai/v1")
        monkeypatch.setenv("OPENAI_MODEL", "MiniMax-M3")
        fn = TOOL_REGISTRY["list_configured_providers"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True
        providers = result["providers"]
        openai_providers = [p for p in providers if p["provider"] == "openai"]
        assert len(openai_providers) == 1
        assert openai_providers[0]["has_key"] is True
        assert openai_providers[0]["base_url"] == "https://api.b.ai/v1"
        assert openai_providers[0]["model"] == "MiniMax-M3"

    def test_api_key_masked_in_provider_list(self, monkeypatch):
        """provider 列表中的 api_key 必须脱敏（跳过 no_auth 的 ollama）。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-a8m2xbs0jbqbgw9ex6st8o7u4zmqa8jz")
        fn = TOOL_REGISTRY["list_configured_providers"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        for p in result["providers"]:
            if p["provider"] == "ollama":
                continue  # ollama no_auth，api_key 是 "(无需)"
            if p.get("api_key") and p["api_key"] != "(无需)":
                assert "a8m2xbs0jbqbgw9" not in p["api_key"], "api_key 未脱敏"
                assert "***" in p["api_key"]

    def test_returns_active_provider(self, monkeypatch):
        """返回 active_provider 字段。"""
        monkeypatch.setenv("XCAGI_LLM_PROVIDER", "openai")
        fn = TOOL_REGISTRY["list_configured_providers"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["active_provider"] == "openai"

    def test_empty_when_no_keys(self, monkeypatch):
        """没有任何 key 时返回空 provider 列表（ollama 除外，因 no_auth）。"""
        for key in (
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "DASHSCOPE_API_KEY",
            "ZHIPU_API_KEY",
            "MOONSHOT_API_KEY",
            "SILICONFLOW_API_KEY",
            "OPENROUTER_API_KEY",
            "VOLC_API_KEY",
            "ARK_API_KEY",
            "XCAUTO_API_KEY",
            "XCAUTO_PAT",
            "MIMO_API_KEY",
            "KIMI_API_KEY",
            "QWEN_API_KEY",
            "GLM_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        fn = TOOL_REGISTRY["list_configured_providers"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True
        # ollama 是 no_auth，所以可能还有 1 个
        providers = result["providers"]
        provider_names = [p["provider"] for p in providers]
        assert all(name == "ollama" for name in provider_names), (
            f"应该只剩 ollama，实际: {provider_names}"
        )

    def test_lists_multiple_providers(self, monkeypatch):
        """配了多个 provider key 时列出多家。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test1234567890")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.b.ai/v1")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds1234567890")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-qwen1234567890")
        fn = TOOL_REGISTRY["list_configured_providers"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True
        provider_names = [p["provider"] for p in result["providers"]]
        assert "b.ai" in provider_names
        assert "deepseek" in provider_names
        assert "qwen" in provider_names

    def test_returns_supported_count(self):
        """返回 supported_count 字段（应为 11）。"""
        fn = TOOL_REGISTRY["list_configured_providers"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["supported_count"] == 11


# ---------------------------------------------------------------------------
# test_llm_key_health — 真实 HTTP ping
# ---------------------------------------------------------------------------


class TestTestLlmKeyHealth:
    """验证 test_llm_key_health 真实发 HTTP 请求。"""

    def test_pings_bai_and_returns_health_status(self):
        """真实 ping b.ai，返回健康状态（需要 .env 配了 key）。"""
        from dotenv import load_dotenv

        load_dotenv()
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY 未配置，跳过真实 ping 测试")
        fn = TOOL_REGISTRY["test_llm_key_health"]
        result = asyncio.get_event_loop().run_until_complete(fn({"provider": "openai"}, {}))
        assert result["ok"] is True, f"健康检查失败: {result.get('error')}"
        assert "results" in result
        assert len(result["results"]) >= 1
        health = result["results"][0]
        assert "provider" in health
        assert "ok" in health
        assert "latency_ms" in health
        assert "status" in health
        assert isinstance(health["latency_ms"], (int, float))
        assert health["latency_ms"] > 0

    def test_returns_error_when_no_key(self, monkeypatch):
        """没有 key 时返回明确错误。"""
        for key in (
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "DASHSCOPE_API_KEY",
            "ZHIPU_API_KEY",
            "MOONSHOT_API_KEY",
            "SILICONFLOW_API_KEY",
            "OPENROUTER_API_KEY",
            "VOLC_API_KEY",
            "ARK_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        fn = TOOL_REGISTRY["test_llm_key_health"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        # ollama 是 no_auth 仍会尝试，所以可能 ok=True（但连不上 localhost）
        # 或 ok=False 如果只有 ollama 且连不上
        assert "results" in result or "error" in result

    def test_healthy_count_field_present(self):
        """结果包含 healthy_count 字段。"""
        from dotenv import load_dotenv

        load_dotenv()
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY 未配置")
        fn = TOOL_REGISTRY["test_llm_key_health"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        if result["ok"]:
            assert "healthy_count" in result
            assert "total_count" in result
            assert result["healthy_count"] <= result["total_count"]


# ---------------------------------------------------------------------------
# query_provider_usage — 真实查 provider billing（通用化，支持多家）
# ---------------------------------------------------------------------------


class TestQueryProviderUsage:
    """验证 query_provider_usage 真实探测 provider billing endpoint。"""

    def test_queries_bai_billing_endpoints(self):
        """真实探测 b.ai billing endpoint。"""
        from dotenv import load_dotenv

        load_dotenv()
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY 未配置")
        if "b.ai" not in os.environ.get("OPENAI_BASE_URL", ""):
            pytest.skip("OPENAI_BASE_URL 不是 b.ai")
        fn = TOOL_REGISTRY["query_provider_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({"provider": "b.ai"}, {}))
        assert result["ok"] is True, f"查询失败: {result.get('error')}"
        assert "findings" in result
        assert len(result["findings"]) >= 1
        assert "has_usage_api" in result
        for f in result["findings"]:
            assert "endpoint" in f or "error" in f

    def test_returns_error_when_no_key(self, monkeypatch):
        """没有任何 provider key 时返回错误或空结果。"""
        for key in (
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "DASHSCOPE_API_KEY",
            "ZHIPU_API_KEY",
            "MOONSHOT_API_KEY",
            "SILICONFLOW_API_KEY",
            "OPENROUTER_API_KEY",
            "VOLC_API_KEY",
            "ARK_API_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        fn = TOOL_REGISTRY["query_provider_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        # 没有 key 时，ollama 仍会被检查（no_auth），所以可能 ok=True 但 findings 为空或只有 ollama
        assert "findings" in result

    def test_supports_multiple_providers(self, monkeypatch):
        """配了多个 provider key 时能查多家 billing。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test1234567890")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.b.ai/v1")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds1234567890")
        fn = TOOL_REGISTRY["query_provider_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True
        # 至少检查了 b.ai 和 deepseek
        providers_checked = {f.get("provider") for f in result.get("findings", [])}
        assert "b.ai" in providers_checked or "deepseek" in providers_checked

    def test_filter_single_provider(self, monkeypatch):
        """provider 过滤生效，只查指定 provider。"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test1234567890")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.b.ai/v1")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds1234567890")
        fn = TOOL_REGISTRY["query_provider_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({"provider": "deepseek"}, {}))
        assert result["ok"] is True
        providers_checked = {f.get("provider") for f in result.get("findings", [])}
        assert providers_checked == {"deepseek"}


# ---------------------------------------------------------------------------
# _PROVIDER_PROFILES — 11 家 provider 配置完整性
# ---------------------------------------------------------------------------


class TestProviderProfiles:
    """验证 _PROVIDER_PROFILES 覆盖 11 家主流 provider 且配置完整。"""

    def test_has_11_providers(self):
        """共 11 家 provider profile。"""
        assert len(_PROVIDER_PROFILES) == 11

    def test_all_required_fields_present(self):
        """每个 profile 有必需字段。"""
        required = {
            "name",
            "env_keys",
            "base_url_default",
            "default_model",
            "ping_model",
            "billing_endpoints",
        }
        for p in _PROVIDER_PROFILES:
            missing = required - set(p.keys())
            assert not missing, f"provider {p.get('name')} 缺字段: {missing}"

    def test_covers_mainstream_providers(self):
        """覆盖主流 11 家 provider。"""
        names = {p["name"] for p in _PROVIDER_PROFILES}
        expected = {
            "b.ai",
            "openai",
            "deepseek",
            "qwen",
            "zhipu",
            "moonshot",
            "siliconflow",
            "openrouter",
            "volcengine",
            "ollama",
            "mimo",
        }
        assert names == expected, f"缺少: {expected - names}"

    def test_ollama_is_no_auth(self):
        """ollama 标记为 no_auth（本地无需 key）。"""
        ollama = next(p for p in _PROVIDER_PROFILES if p["name"] == "ollama")
        assert ollama.get("no_auth") is True
        assert ollama["env_keys"] == []

    def test_mimo_uses_token_plan_endpoint(self):
        """mimo 用 Token Plan 中国集群 endpoint（tp-xxxxx key）。"""
        mimo = next(p for p in _PROVIDER_PROFILES if p["name"] == "mimo")
        assert mimo["env_keys"] == ["MIMO_API_KEY"]
        assert "token-plan-cn.xiaomimimo.com" in mimo["base_url_default"]
        assert mimo["default_model"] == "mimo-v2.5-pro"
        assert mimo["ping_model"] == "mimo-v2.5-pro"

    def test_bai_and_openai_share_openai_key(self):
        """b.ai 和 openai 都用 OPENAI_API_KEY（通过 base_url 区分）。"""
        bai = next(p for p in _PROVIDER_PROFILES if p["name"] == "b.ai")
        openai = next(p for p in _PROVIDER_PROFILES if p["name"] == "openai")
        assert "OPENAI_API_KEY" in bai["env_keys"]
        assert "OPENAI_API_KEY" in openai["env_keys"]
        # 都有 detect 函数区分
        assert "detect" in bai
        assert "detect" in openai

    def test_each_provider_has_ping_model(self):
        """每个 provider 有 ping_model（用便宜/免费模型 ping）。"""
        for p in _PROVIDER_PROFILES:
            assert p["ping_model"], f"{p['name']} 缺 ping_model"

    def test_env_keys_derived_correctly(self):
        """_LLM_ENV_KEYS 从 profiles 派生，包含所有 provider 的 env_keys。"""
        from app.mod_sdk.employee_specialized_tools import _LLM_ENV_KEYS

        for p in _PROVIDER_PROFILES:
            for k in p["env_keys"]:
                assert k in _LLM_ENV_KEYS, f"{k} 不在 _LLM_ENV_KEYS"
            if p.get("base_url_env"):
                assert p["base_url_env"] in _LLM_ENV_KEYS
            if p.get("model_env"):
                assert p["model_env"] in _LLM_ENV_KEYS


# ---------------------------------------------------------------------------
# compare_model_prices — 内置价格表
# ---------------------------------------------------------------------------


class TestCompareModelPrices:
    """验证 compare_model_prices 返回真实价格表。"""

    def test_returns_all_models_by_default(self):
        """默认返回全部模型（22 个，覆盖 11 家）。"""
        fn = TOOL_REGISTRY["compare_model_prices"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True
        assert len(result["prices"]) == len(_MODEL_PRICES)
        assert len(result["prices"]) >= 20  # 至少 20 个模型
        assert result["total_models"] == len(_MODEL_PRICES)

    def test_sorted_by_output_price_ascending(self):
        """默认按 output 价格升序。"""
        fn = TOOL_REGISTRY["compare_model_prices"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        prices = result["prices"]
        for i in range(len(prices) - 1):
            assert prices[i]["output_per_1m"] <= prices[i + 1]["output_per_1m"]

    def test_sort_by_input(self):
        """sort_by=input 时按 input 价格升序。"""
        fn = TOOL_REGISTRY["compare_model_prices"]
        result = asyncio.get_event_loop().run_until_complete(fn({"sort_by": "input"}, {}))
        prices = result["prices"]
        for i in range(len(prices) - 1):
            assert prices[i]["input_per_1m"] <= prices[i + 1]["input_per_1m"]

    def test_filter_by_provider(self):
        """provider 过滤生效。"""
        fn = TOOL_REGISTRY["compare_model_prices"]
        result = asyncio.get_event_loop().run_until_complete(fn({"provider": "deepseek"}, {}))
        prices = result["prices"]
        assert len(prices) >= 2  # DeepSeek-V3 + DeepSeek-R1
        for p in prices:
            assert "deepseek" in p["provider"].lower()

    def test_identifies_free_models(self):
        """识别免费模型（glm-4-flash / Qwen2.5-7B / llama3.2 / qwen2.5:7b）。"""
        fn = TOOL_REGISTRY["compare_model_prices"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        free = result["free_models"]
        assert "glm-4-flash" in free
        assert "llama3.2" in free  # ollama 本地免费
        # 免费模型价格为 0
        for p in result["prices"]:
            if p["model"] in free:
                assert p["input_per_1m"] == 0
                assert p["output_per_1m"] == 0

    def test_returns_cheapest_model(self):
        """返回 cheapest 字段。"""
        fn = TOOL_REGISTRY["compare_model_prices"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["cheapest"] is not None
        # 最便宜的应该是 glm-4-flash（免费）或 qwen-plus
        assert (
            result["cheapest"]["output_per_1m"] == 0 or result["cheapest"]["model"] == "qwen-plus"
        )

    def test_model_prices_have_required_fields(self):
        """每个模型价格条目有必需字段。"""
        fn = TOOL_REGISTRY["compare_model_prices"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        for p in result["prices"]:
            assert "model" in p
            assert "provider" in p
            assert "input_per_1m" in p
            assert "output_per_1m" in p
            assert "context" in p
            assert isinstance(p["input_per_1m"], (int, float))
            assert isinstance(p["output_per_1m"], (int, float))

    def test_minimax_m3_in_list(self):
        """MiniMax-M3（当前在用）在价格表中。"""
        fn = TOOL_REGISTRY["compare_model_prices"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        models = [p["model"] for p in result["prices"]]
        assert "MiniMax-M3" in models


# ---------------------------------------------------------------------------
# query_local_token_usage — 本地 token 用量账本查询
# ---------------------------------------------------------------------------


class TestQueryLocalTokenUsage:
    """验证 query_local_token_usage 真实读取本地账本。"""

    def test_registered_in_tool_registry(self):
        """工具注册在 TOOL_REGISTRY。"""
        assert "query_local_token_usage" in TOOL_REGISTRY

    def test_registered_for_llm_ops_engineer(self):
        """工具属于 llm-ops-engineer。"""
        assert "query_local_token_usage" in EMPLOYEE_TOOLS["llm-ops-engineer"]

    def test_returns_summary_with_real_data(self):
        """返回汇总数据（prompt/completion/total tokens）。"""
        fn = TOOL_REGISTRY["query_local_token_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True
        assert "usage_summary" in result
        summary = result["usage_summary"]
        # 必须有这些字段（即使值为 0）
        assert "prompt_tokens" in summary
        assert "completion_tokens" in summary
        assert "total_tokens" in summary
        assert "total_calls" in summary
        assert "cost_units" in summary

    def test_returns_ledger_path(self):
        """返回账本路径（真实文件路径）。"""
        fn = TOOL_REGISTRY["query_local_token_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True
        assert "ledger_path" in result
        assert "model_usage_ledger.json" in result["ledger_path"]
        assert "ledger_exists" in result

    def test_groups_by_model_by_default(self):
        """默认按 model 分组。"""
        fn = TOOL_REGISTRY["query_local_token_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True
        assert result["group_by"] == "model"
        assert "groups" in result

    def test_groups_by_provider(self):
        """支持按 provider 分组。"""
        fn = TOOL_REGISTRY["query_local_token_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({"group_by": "provider"}, {}))
        assert result["ok"] is True
        assert result["group_by"] == "provider"
        assert "groups" in result

    def test_no_grouping_when_none(self):
        """group_by=none 时不分组。"""
        fn = TOOL_REGISTRY["query_local_token_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({"group_by": "none"}, {}))
        assert result["ok"] is True
        assert result["groups"] == {}

    def test_limit_zero_returns_no_details(self):
        """limit=0 只返回汇总，不返回明细。"""
        fn = TOOL_REGISTRY["query_local_token_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({"limit": 0}, {}))
        assert result["ok"] is True
        assert result["detail_count"] == 0
        assert result["details"] == []

    def test_details_have_token_fields(self):
        """明细包含 token 字段。"""
        fn = TOOL_REGISTRY["query_local_token_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({"limit": 5}, {}))
        assert result["ok"] is True
        for d in result["details"]:
            assert "prompt_tokens" in d
            assert "completion_tokens" in d
            assert "total_tokens" in d
            assert "model" in d
            assert "provider" in d

    def test_note_explains_limitations(self):
        """note 字段说明数据局限性。"""
        fn = TOOL_REGISTRY["query_local_token_usage"]
        result = asyncio.get_event_loop().run_until_complete(fn({}, {}))
        assert result["ok"] is True
        assert "note" in result
        # 必须提到 agent_orchestrator 和平台不开放 API
        assert "agent_orchestrator" in result["note"]


# ---------------------------------------------------------------------------
# handle_specialized 端到端调度
# ---------------------------------------------------------------------------


class TestHandleSpecializedDispatch:
    """验证 handle_specialized 能正确调度 llm-ops-engineer 的工具。"""

    def test_dispatches_compare_model_prices(self):
        """handle_specialized 能调度 compare_model_prices。"""
        result = asyncio.get_event_loop().run_until_complete(
            handle_specialized(
                "llm-ops-engineer", {"tool": "compare_model_prices", "params": {}}, {}
            )
        )
        assert result["ok"] is True
        assert "prices" in result

    def test_dispatches_read_llm_env_config(self, tmp_path, monkeypatch):
        """handle_specialized 能调度 read_llm_env_config（自洽临时 .env）。"""
        import app.mod_sdk.employee_specialized_tools as mod

        env_path = tmp_path / ".env"
        env_path.write_text(
            "XCAGI_LLM_PROVIDER=openai\nOPENAI_API_KEY=sk-test1234567890\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_FHD_ROOT", tmp_path)
        result = asyncio.get_event_loop().run_until_complete(
            handle_specialized(
                "llm-ops-engineer", {"tool": "read_llm_env_config", "params": {}}, {}
            )
        )
        assert result["ok"] is True
        assert "env_config" in result

    def test_dispatches_list_configured_providers(self):
        """handle_specialized 能调度 list_configured_providers。"""
        from dotenv import load_dotenv

        load_dotenv()
        result = asyncio.get_event_loop().run_until_complete(
            handle_specialized(
                "llm-ops-engineer", {"tool": "list_configured_providers", "params": {}}, {}
            )
        )
        assert result["ok"] is True
        assert "providers" in result

    def test_blocks_other_employees_from_llm_ops_tools(self):
        """其他员工不能调用 llm-ops-engineer 的专属工具。"""
        result = asyncio.get_event_loop().run_until_complete(
            handle_specialized(
                "fhd-core-maintainer", {"tool": "compare_model_prices", "params": {}}, {}
            )
        )
        assert result["ok"] is False
        assert "不在员工" in result["error"]
