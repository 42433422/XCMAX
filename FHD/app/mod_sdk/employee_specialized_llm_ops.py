"""LLM ops."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

from app.mod_sdk.employee_specialized_runtime import (
    _FHD_ROOT,
    _err,
    _facade_attr,
    _ok,
)

_PROVIDER_PROFILES: list[dict[str, Any]] = [
    {
        "name": "b.ai",
        "env_keys": ["OPENAI_API_KEY"],
        "base_url_env": "OPENAI_BASE_URL",
        "base_url_default": "https://api.b.ai/v1",
        "model_env": "OPENAI_MODEL",
        "default_model": "MiniMax-M3",
        "ping_model": "MiniMax-M3",
        "billing_endpoints": [
            "/dashboard/billing/credit_grants",
            "/dashboard/billing/subscription",
        ],
        "detect": lambda env: "b.ai" in env.get("OPENAI_BASE_URL", ""),
    },
    {
        "name": "openai",
        "env_keys": ["OPENAI_API_KEY"],
        "base_url_env": "OPENAI_BASE_URL",
        "base_url_default": "https://api.openai.com/v1",
        "model_env": "OPENAI_MODEL",
        "default_model": "gpt-4o-mini",
        "ping_model": "gpt-4o-mini",
        "billing_endpoints": ["/dashboard/billing/credit_grants"],
        "detect": lambda env: env.get("OPENAI_BASE_URL", "") in ("", "https://api.openai.com/v1"),
    },
    {
        "name": "deepseek",
        "env_keys": ["DEEPSEEK_API_KEY"],
        "base_url_env": "DEEPSEEK_BASE_URL",
        "base_url_default": "https://api.deepseek.com/v1",
        "model_env": "DEEPSEEK_MODEL",
        "default_model": "deepseek-chat",
        "ping_model": "deepseek-chat",
        "billing_endpoints": ["/user/balance"],
    },
    {
        "name": "qwen",
        "env_keys": ["DASHSCOPE_API_KEY", "QWEN_API_KEY"],
        "base_url_env": "DASHSCOPE_BASE_URL",
        "base_url_default": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_env": "QWEN_MODEL",
        "default_model": "qwen-plus",
        "ping_model": "qwen-turbo",
        "billing_endpoints": [],
    },
    {
        "name": "zhipu",
        "env_keys": ["ZHIPU_API_KEY", "GLM_API_KEY"],
        "base_url_env": "ZHIPU_BASE_URL",
        "base_url_default": "https://open.bigmodel.cn/api/paas/v4",
        "model_env": "GLM_MODEL",
        "default_model": "glm-4-plus",
        "ping_model": "glm-4-flash",
        "billing_endpoints": [],
    },
    {
        "name": "moonshot",
        "env_keys": ["MOONSHOT_API_KEY", "KIMI_API_KEY"],
        "base_url_env": "MOONSHOT_BASE_URL",
        "base_url_default": "https://api.moonshot.cn/v1",
        "model_env": "MOONSHOT_MODEL",
        "default_model": "moonshot-v1-8k",
        "ping_model": "moonshot-v1-8k",
        "billing_endpoints": ["/users/me/balance"],
    },
    {
        "name": "siliconflow",
        "env_keys": ["SILICONFLOW_API_KEY"],
        "base_url_env": "SILICONFLOW_BASE_URL",
        "base_url_default": "https://api.siliconflow.cn/v1",
        "model_env": "SILICONFLOW_MODEL",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "ping_model": "Qwen/Qwen2.5-7B-Instruct",
        "billing_endpoints": ["/user/info"],
    },
    {
        "name": "openrouter",
        "env_keys": ["OPENROUTER_API_KEY"],
        "base_url_env": "OPENROUTER_BASE_URL",
        "base_url_default": "https://openrouter.ai/api/v1",
        "model_env": "OPENROUTER_MODEL",
        "default_model": "openai/gpt-4o-mini",
        "ping_model": "openai/gpt-4o-mini",
        "billing_endpoints": ["/credits"],
    },
    {
        "name": "volcengine",
        "env_keys": ["VOLC_API_KEY", "ARK_API_KEY"],
        "base_url_env": "VOLC_BASE_URL",
        "base_url_default": "https://ark.cn-beijing.volces.com/api/v3",
        "model_env": "VOLC_MODEL",
        "default_model": "doubao-pro-32k",
        "ping_model": "doubao-lite-4k",
        "billing_endpoints": [],
    },
    {
        "name": "ollama",
        "env_keys": [],
        "base_url_env": "OLLAMA_BASE_URL",
        "base_url_default": "http://localhost:11434/v1",
        "model_env": "OLLAMA_MODEL",
        "default_model": "llama3.2",
        "ping_model": "llama3.2",
        "billing_endpoints": ["/api/tags"],
        "no_auth": True,
    },
    {
        # 小米 MiMo (Token Plan, OpenAI 兼容)
        # Key 格式 tp-xxxxx (Token Plan) 与 sk-xxxxx (按量付费) 独立
        # 中国集群 endpoint: token-plan-cn.xiaomimimo.com/v1
        "name": "mimo",
        "env_keys": ["MIMO_API_KEY"],
        "base_url_env": "MIMO_BASE_URL",
        "base_url_default": "https://token-plan-cn.xiaomimimo.com/v1",
        "model_env": "MIMO_MODEL",
        "default_model": "mimo-v2.5-pro",
        "ping_model": "mimo-v2.5-pro",
        "billing_endpoints": [],  # Token Plan 无 billing 查询端点, 订阅期内无限调用
    },
]

# 从 profiles 派生环境变量清单
_LLM_ENV_KEYS: tuple[str, ...] = tuple(
    dict.fromkeys(
        [k for p in _PROVIDER_PROFILES for k in p["env_keys"]]
        + [p["base_url_env"] for p in _PROVIDER_PROFILES if p.get("base_url_env")]
        + [p["model_env"] for p in _PROVIDER_PROFILES if p.get("model_env")]
        + [
            "XCAGI_LLM_PROVIDER",
            "LLM_PROVIDER",
            "LLM_MODE",
            "FHD_LLM_MODE",
            "XCAUTO_API_KEY",
            "XCAUTO_PAT",
            "XIUCI_API_KEY",
            "XCAGI_EMPLOYEE_LLM_MODEL",
        ]
    )
)
# 需要脱敏的 key（含 secret / API_KEY / PAT）
_LLM_SECRET_KEYS: frozenset[str] = frozenset(
    k for k in _LLM_ENV_KEYS if "API_KEY" in k or "PAT" in k or "SECRET" in k
)


def _mask_secret(val: str) -> str:
    """脱敏：sk-abc123xyz → sk-***xyz（保留前 3 + 后 3）。"""
    if not val:
        return ""
    if len(val) <= 8:
        return "***"
    return f"{val[:3]}***{val[-3:]}"


def _read_env_file(env_path: Path) -> dict[str, str]:
    """解析 .env 文件为 dict（不污染 os.environ）。"""
    out: dict[str, str] = {}
    if not env_path.is_file():
        return out
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip("'\"")
            if k:
                out[k] = v
    except OSError:
        pass
    return out


def _provider_has_key(profile: dict[str, Any], env: dict[str, str]) -> str | None:
    """检查 provider 是否配了 key，返回第一个非空 key（不脱敏）。"""
    for k in profile["env_keys"]:
        v = env.get(k)
        if v:
            return v
    return None


def _provider_base_url(profile: dict[str, Any], env: dict[str, str]) -> str:
    """获取 provider 的 base_url（env 覆盖 default）。"""
    env_key = profile.get("base_url_env")
    if env_key:
        v = env.get(env_key)
        if v:
            return v
    return profile["base_url_default"]


def _provider_model(profile: dict[str, Any], env: dict[str, str]) -> str:
    """获取 provider 的模型（env 覆盖 default）。"""
    env_key = profile.get("model_env")
    if env_key:
        v = env.get(env_key)
        if v:
            return v
    return profile["default_model"]


def _detect_provider_name(profile: dict[str, Any], env: dict[str, str]) -> bool:
    """判断当前环境是否匹配该 provider（用于 OpenAI 兼容的 b.ai/openai 区分）。"""
    detect = profile.get("detect")
    if detect:
        return bool(detect(env))
    # 默认：有 key 就算匹配
    return _provider_has_key(profile, env) is not None


async def tool_read_llm_env_config(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """读取 .env 中 LLM 相关配置（API key 脱敏）。

    真实读取 FHD/.env 文件，提取所有 provider 的配置段，key 一律脱敏为 sk-***xxx。
    """
    env_path = _facade_attr("_FHD_ROOT", _FHD_ROOT) / ".env"
    env_map = _read_env_file(env_path)
    if not env_map:
        return _err(f".env 文件不存在或为空: {env_path}")
    llm_cfg: dict[str, str] = {}
    for k in _LLM_ENV_KEYS:
        if k in env_map:
            v = env_map[k]
            llm_cfg[k] = _mask_secret(v) if k in _LLM_SECRET_KEYS else v
    # 同时读 os.environ（运行时可能被覆盖）
    runtime_cfg: dict[str, str] = {}
    for k in _LLM_ENV_KEYS:
        v = os.environ.get(k)
        if v:
            runtime_cfg[k] = _mask_secret(v) if k in _LLM_SECRET_KEYS else v
    return _ok(
        f".env LLM 段读取完成（{len(llm_cfg)} 项），运行时环境变量 {len(runtime_cfg)} 项",
        env_file=str(env_path),
        env_config=llm_cfg,
        runtime_config=runtime_cfg,
        configured_provider=env_map.get("XCAGI_LLM_PROVIDER")
        or os.environ.get("XCAGI_LLM_PROVIDER")
        or "(未配置)",
        supported_providers=[p["name"] for p in _PROVIDER_PROFILES],
    )


async def tool_list_configured_providers(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """列出当前已配置的 LLM provider 及其状态（支持 10 家）。

    从 os.environ 实时读取，遍历所有 provider profile，标注 key 是否存在。
    """
    env = dict(os.environ)
    providers: list[dict[str, Any]] = []
    for profile in _PROVIDER_PROFILES:
        name = profile["name"]
        key = _provider_has_key(profile, env)
        no_auth = profile.get("no_auth", False)
        # ollama 不需要 key，只要 base_url 可达或默认就列出
        if not key and not no_auth:
            continue
        base_url = _provider_base_url(profile, env)
        model = _provider_model(profile, env)
        entry: dict[str, Any] = {
            "provider": name,
            "api_key": _mask_secret(key) if key else ("(无需)" if no_auth else ""),
            "has_key": bool(key) or no_auth,
            "base_url": base_url,
            "model": model,
            "ping_model": profile["ping_model"],
            "has_billing_api": bool(profile.get("billing_endpoints")),
        }
        providers.append(entry)
    active = os.environ.get("XCAGI_LLM_PROVIDER", "(未配置，走 default path)")
    return _ok(
        f"已配置 {len(providers)} 个 provider（共支持 {len(_PROVIDER_PROFILES)} 家），当前激活: {active}",
        providers=providers,
        active_provider=active,
        employee_llm_model=os.environ.get("XCAGI_EMPLOYEE_LLM_MODEL", "(未配置)"),
        supported_count=len(_PROVIDER_PROFILES),
    )


async def tool_test_llm_key_health(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """对已配置的 provider 发 ping 请求，测延迟和可用性（支持 10 家）。

    真实 HTTP 调用 /chat/completions（max_tokens=1），返回每个 provider 的健康状态。
    可用 params.provider 指定单个 provider，或留空测全部。
    """
    hx = _facade_attr("httpx", httpx)
    if hx is None:
        return _err("httpx 未安装，无法测试")
    target = str(params.get("provider") or "").strip().lower()
    env = dict(os.environ)
    results: list[dict[str, Any]] = []

    async def _ping(
        name: str, base_url: str, api_key: str, model: str, no_auth: bool = False
    ) -> dict[str, Any]:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if not no_auth and api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        t0 = asyncio.get_event_loop().time()
        try:
            async with hx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                elapsed = round((asyncio.get_event_loop().time() - t0) * 1000, 1)
                body: Any
                try:
                    body = resp.json()
                except Exception:  # noqa: BLE001
                    body = resp.text[:200]
                return {
                    "provider": name,
                    "ok": resp.is_success,
                    "status": resp.status_code,
                    "latency_ms": elapsed,
                    "model": model,
                    "error": "" if resp.is_success else str(body)[:300],
                }
        except Exception as exc:  # noqa: BLE001  健康检查边界：网络异常转结构化结果
            elapsed = round((asyncio.get_event_loop().time() - t0) * 1000, 1)
            return {
                "provider": name,
                "ok": False,
                "status": 0,
                "latency_ms": elapsed,
                "model": model,
                "error": repr(exc)[:300],
            }

    for profile in _PROVIDER_PROFILES:
        name = profile["name"]
        if target and target != "all" and target != name:
            continue
        key = _provider_has_key(profile, env)
        no_auth = profile.get("no_auth", False)
        if not key and not no_auth:
            continue
        base_url = _provider_base_url(profile, env)
        # ping 用 ping_model（便宜/免费），不是 default_model
        ping_model = profile["ping_model"]
        results.append(await _ping(name, base_url, key or "", ping_model, no_auth))

    if not results:
        return _err(f"未找到已配置 API key 的 provider（已检查 {len(_PROVIDER_PROFILES)} 家）")
    healthy = sum(1 for r in results if r["ok"])
    return _ok(
        f"测试 {len(results)} 个 provider，{healthy} 个健康",
        results=results,
        healthy_count=healthy,
        total_count=len(results),
    )


async def tool_query_provider_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 provider 账户余额与用量（通用化，支持多家 billing API）。

    真实探测 provider 的 billing endpoint，返回余额/用量。
    可用 params.provider 指定单个 provider，或留空查全部已配置的。
    """
    hx = _facade_attr("httpx", httpx)
    if hx is None:
        return _err("httpx 未安装")
    target = str(params.get("provider") or "").strip().lower()
    env = dict(os.environ)
    all_findings: list[dict[str, Any]] = []
    checked = 0
    supported = 0

    async with hx.AsyncClient(timeout=15) as client:
        for profile in _PROVIDER_PROFILES:
            name = profile["name"]
            if target and target != "all" and target != name:
                continue
            key = _provider_has_key(profile, env)
            no_auth = profile.get("no_auth", False)
            if not key and not no_auth:
                continue
            endpoints = profile.get("billing_endpoints") or []
            if not endpoints:
                all_findings.append(
                    {
                        "provider": name,
                        "endpoint": "(无)",
                        "status": 0,
                        "ok": False,
                        "error": f"{name} 无标准 billing API",
                    }
                )
                continue
            base_url = _provider_base_url(profile, env)
            headers = {}
            if not no_auth and key:
                headers["Authorization"] = f"Bearer {key}"
            checked += 1
            for ep in endpoints:
                url = f"{base_url.rstrip('/')}{ep}"
                try:
                    resp = await client.get(url, headers=headers)
                    body: Any
                    try:
                        body = resp.json()
                    except Exception:  # noqa: BLE001
                        body = resp.text[:300]
                    finding = {
                        "provider": name,
                        "endpoint": ep,
                        "status": resp.status_code,
                        "ok": resp.is_success,
                        "body": body if isinstance(body, (dict, list)) else str(body)[:300],
                    }
                    all_findings.append(finding)
                    if resp.is_success:
                        supported += 1
                except Exception as exc:  # noqa: BLE001
                    all_findings.append(
                        {
                            "provider": name,
                            "endpoint": ep,
                            "status": 0,
                            "ok": False,
                            "error": repr(exc)[:200],
                        }
                    )
    return _ok(
        f"探测 {checked} 个 provider 的 billing endpoint，{supported} 个可用",
        findings=all_findings,
        has_usage_api=supported > 0,
        checked_providers=checked,
        supported_count=supported,
    )


# 内置模型价格表（2026 市场参考价，每 1M tokens，美元）— 覆盖 10 家 provider
_MODEL_PRICES: list[dict[str, Any]] = [
    # DeepSeek
    {
        "model": "DeepSeek-V3",
        "provider": "DeepSeek",
        "input_per_1m": 0.27,
        "output_per_1m": 1.10,
        "context": "64K",
        "note": "国产最便宜之一",
    },
    {
        "model": "DeepSeek-R1",
        "provider": "DeepSeek",
        "input_per_1m": 0.55,
        "output_per_1m": 2.19,
        "context": "64K",
        "note": "推理模型",
    },
    # MiniMax（b.ai）
    {
        "model": "MiniMax-M3",
        "provider": "b.ai",
        "input_per_1m": 0.40,
        "output_per_1m": 1.50,
        "context": "1M",
        "note": "当前在用",
    },
    {
        "model": "MiniMax-Text-01",
        "provider": "MiniMax",
        "input_per_1m": 0.20,
        "output_per_1m": 0.80,
        "context": "1M",
        "note": "便宜",
    },
    # OpenAI
    {
        "model": "gpt-4o",
        "provider": "OpenAI",
        "input_per_1m": 2.50,
        "output_per_1m": 10.00,
        "context": "128K",
        "note": "贵",
    },
    {
        "model": "gpt-4o-mini",
        "provider": "OpenAI",
        "input_per_1m": 0.15,
        "output_per_1m": 0.60,
        "context": "128K",
        "note": "性价比高",
    },
    # Anthropic
    {
        "model": "claude-3.5-sonnet",
        "provider": "Anthropic",
        "input_per_1m": 3.00,
        "output_per_1m": 15.00,
        "context": "200K",
        "note": "最贵",
    },
    # 通义千问
    {
        "model": "qwen-max",
        "provider": "qwen",
        "input_per_1m": 1.40,
        "output_per_1m": 5.60,
        "context": "32K",
        "note": "",
    },
    {
        "model": "qwen-plus",
        "provider": "qwen",
        "input_per_1m": 0.14,
        "output_per_1m": 0.56,
        "context": "128K",
        "note": "便宜",
    },
    {
        "model": "qwen-turbo",
        "provider": "qwen",
        "input_per_1m": 0.05,
        "output_per_1m": 0.20,
        "context": "1M",
        "note": "最便宜之一",
    },
    # 智谱
    {
        "model": "glm-4-plus",
        "provider": "zhipu",
        "input_per_1m": 0.70,
        "output_per_1m": 0.70,
        "context": "128K",
        "note": "",
    },
    {
        "model": "glm-4-flash",
        "provider": "zhipu",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "128K",
        "note": "免费！",
    },
    # Kimi
    {
        "model": "moonshot-v1-8k",
        "provider": "moonshot",
        "input_per_1m": 1.68,
        "output_per_1m": 1.68,
        "context": "8K",
        "note": "",
    },
    {
        "model": "moonshot-v1-32k",
        "provider": "moonshot",
        "input_per_1m": 3.36,
        "output_per_1m": 3.36,
        "context": "32K",
        "note": "",
    },
    # 硅基流动（聚合，价格按 DeepSeek-V3 估算）
    {
        "model": "deepseek-ai/DeepSeek-V3",
        "provider": "siliconflow",
        "input_per_1m": 0.27,
        "output_per_1m": 1.10,
        "context": "64K",
        "note": "聚合代理",
    },
    {
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "provider": "siliconflow",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "32K",
        "note": "免费！",
    },
    # OpenRouter（聚合，价格按 OpenAI 估算）
    {
        "model": "openai/gpt-4o-mini",
        "provider": "openrouter",
        "input_per_1m": 0.15,
        "output_per_1m": 0.60,
        "context": "128K",
        "note": "聚合代理",
    },
    # 火山引擎（豆包）
    {
        "model": "doubao-pro-32k",
        "provider": "volcengine",
        "input_per_1m": 0.11,
        "output_per_1m": 0.28,
        "context": "32K",
        "note": "便宜",
    },
    {
        "model": "doubao-lite-4k",
        "provider": "volcengine",
        "input_per_1m": 0.003,
        "output_per_1m": 0.007,
        "context": "4K",
        "note": "极便宜",
    },
    # Ollama（本地，免费）
    {
        "model": "llama3.2",
        "provider": "ollama",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "128K",
        "note": "本地免费！",
    },
    {
        "model": "qwen2.5:7b",
        "provider": "ollama",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "32K",
        "note": "本地免费！",
    },
    # 小米 MiMo (Token Plan 订阅制, 订阅期内无限调用, 此处价格按订阅摊销估算)
    {
        "model": "mimo-v2.5-pro",
        "provider": "mimo",
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "context": "128K",
        "note": "Token Plan 订阅期内免费",
    },
]


async def tool_compare_model_prices(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """对比各 LLM 模型价格（内置价格表，覆盖 10 家 provider）。

    支持按 provider 过滤，按价格排序。标注免费模型。
    """
    provider_filter = str(params.get("provider") or "").strip().lower()
    sort_by = str(params.get("sort_by") or "output").strip().lower()
    prices = [dict(p) for p in _MODEL_PRICES]
    if provider_filter:
        prices = [p for p in prices if provider_filter in str(p["provider"]).lower()]
    sort_key = "input_per_1m" if sort_by == "input" else "output_per_1m"
    prices.sort(key=lambda x: float(x.get(sort_key, 999)))
    free_models = [
        p["model"]
        for p in prices
        if float(p.get("input_per_1m", 0)) == 0 and float(p.get("output_per_1m", 0)) == 0
    ]
    cheapest = prices[0] if prices else None
    return _ok(
        f"对比 {len(prices)} 个模型（按 {sort_key} 升序），{len(free_models)} 个免费",
        prices=prices,
        free_models=free_models,
        cheapest=cheapest,
        sort_by=sort_key,
        total_models=len(_MODEL_PRICES),
        providers_covered=sorted({p["provider"] for p in _MODEL_PRICES}),
    )


async def tool_query_local_token_usage(
    params: dict[str, Any], ctx: dict[str, Any]
) -> dict[str, Any]:
    """查询本地 token 用量账本（真实数据，非 LLM 编造）。

    读取 FHD 的 model_usage_ledger.json，返回 token 用量统计。
    b.ai/mimo 等平台不开放 usage 查询 API，但 FHD 在 agent_orchestrator
    路径下会记录每次 LLM 调用的 prompt/completion/total tokens 到本地账本。

    可用 params:
    - user_id: 按用户筛选
    - run_id: 按会话/run 筛选
    - limit: 返回最近 N 条明细（默认 20，0 = 只返回汇总不返回明细）
    - group_by: "model" | "provider" | "none"（默认 model）
    """
    try:
        from app.infrastructure.billing.model_usage import (
            list_model_usage_entries,
            model_usage_ledger_path,
        )
    except ImportError as exc:
        return _err(f"无法导入 billing 模块: {exc}")

    user_id = str(params.get("user_id") or "").strip()
    run_id = str(params.get("run_id") or "").strip()
    limit = int(params.get("limit") if params.get("limit") is not None else 20)
    group_by = str(params.get("group_by") or "model").strip().lower()

    ledger_path = model_usage_ledger_path()
    entries = list_model_usage_entries(
        limit=max(limit, 500) if limit > 0 else 500, run_id=run_id, user_id=user_id
    )

    # 只统计 model_call 类型（tool_call 的 token 是 0）
    model_entries = [e for e in entries if str(e.get("entry_type") or "model_call") == "model_call"]

    # 汇总
    total_prompt = sum(int(e.get("prompt_tokens") or 0) for e in model_entries)
    total_completion = sum(int(e.get("completion_tokens") or 0) for e in model_entries)
    total_tokens = sum(int(e.get("total_tokens") or 0) for e in model_entries)
    total_cost = sum(int(e.get("cost_units") or 0) for e in model_entries)

    # 分组统计
    groups: dict[str, dict[str, Any]] = {}
    group_key = "model" if group_by == "model" else ("provider" if group_by == "provider" else "")
    for e in model_entries:
        if not group_key:
            continue
        key = str(e.get(group_key) or "unknown")
        g = groups.setdefault(
            key,
            {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_units": 0,
                "calls": 0,
            },
        )
        g["prompt_tokens"] += int(e.get("prompt_tokens") or 0)
        g["completion_tokens"] += int(e.get("completion_tokens") or 0)
        g["total_tokens"] += int(e.get("total_tokens") or 0)
        g["cost_units"] += int(e.get("cost_units") or 0)
        g["calls"] += 1

    # 明细（限制条数）
    details = []
    if limit > 0:
        for e in model_entries[:limit]:
            details.append(
                {
                    "created_at": e.get("created_at", ""),
                    "provider": e.get("provider", ""),
                    "model": e.get("model", ""),
                    "prompt_tokens": int(e.get("prompt_tokens") or 0),
                    "completion_tokens": int(e.get("completion_tokens") or 0),
                    "total_tokens": int(e.get("total_tokens") or 0),
                    "cost_units": int(e.get("cost_units") or 0),
                    "run_id": e.get("run_id", ""),
                    "user_id": e.get("user_id", ""),
                }
            )

    # 账本是否存在
    ledger_exists = ledger_path.is_file()

    return _ok(
        f"本地账本 {len(model_entries)} 条 model_call 记录，总 token={total_tokens:,}",
        ledger_path=str(ledger_path),
        ledger_exists=ledger_exists,
        usage_summary={
            "total_calls": len(model_entries),
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "cost_units": total_cost,
        },
        groups=groups if group_key else {},
        group_by=group_by,
        details=details,
        detail_count=len(details),
        note="仅 agent_orchestrator 路径记录；conversation 服务主路径未持久化。b.ai/mimo 平台不开放 usage API，需去各自控制台查看。",
    )


async def tool_query_cursor_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 Cursor 编辑器的使用统计（自动采集，含精确 token 用量）。

    数据源（按精确度从高到低）：
    1. cursor-usage CLI → 调 Cursor Dashboard 内部 API，返回精确的
       inputTokens/outputTokens/cacheReadTokens/totalCents（按 model 分组）
    2. macOS Keychain cursor-access-token → api2.cursor.sh/auth/usage
       获取免费配额（gpt-4）的请求次数
    3. 本地 ~/.cursor/ai-tracking/ai-code-tracking.db（SQLite）
       获取 AI 代码生成次数和 commit 代码比例

    可用 params:
    - days: 统计最近 N 天的数据（默认 30，0 = 当前账单月）
    - detail_limit: 返回最近 N 条明细事件（默认 10，0 = 不返回明细）
    """
    import csv
    import io
    import sqlite3
    from datetime import UTC, datetime, timedelta

    import app.mod_sdk.employee_specialized_tools as est

    shutil = est.shutil
    subprocess = est.subprocess

    days = int(params.get("days") if params.get("days") is not None else 30)
    detail_limit = int(params.get("detail_limit") if params.get("detail_limit") is not None else 10)
    result_data: dict[str, Any] = {
        "sources": [],
        "cli_usage": None,
        "api_usage": None,
        "local_db": None,
        "cursor_summary": {},
    }

    # --- 数据源 1：cursor-usage CLI（精确 token + 费用）---
    cli_bin = shutil.which("cursor-usage") or str(
        Path.home() / "Library" / "Python" / "3.9" / "bin" / "cursor-usage"
    )
    if Path(cli_bin).is_file():
        result_data["sources"].append("cursor-usage-cli")
        try:
            # 获取汇总 JSON
            cmd = [cli_bin, "--json"]
            if days > 0:
                cmd.extend(["--days", str(days)])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                raw = json.loads(proc.stdout)
                aggregations = raw.get("aggregations", [])
                # 汇总
                total_input = 0
                total_output = 0
                total_cache_read = 0
                total_cache_write = 0
                total_cents = 0.0
                by_model = []
                for agg in aggregations:
                    inp = int(agg.get("inputTokens") or 0)
                    out = int(agg.get("outputTokens") or 0)
                    cr = int(agg.get("cacheReadTokens") or 0)
                    cw = int(agg.get("cacheWriteTokens") or 0)
                    cents = float(agg.get("totalCents") or 0)
                    total_input += inp
                    total_output += out
                    total_cache_read += cr
                    total_cache_write += cw
                    total_cents += cents
                    by_model.append(
                        {
                            "model": agg.get("modelIntent", "unknown"),
                            "input_tokens": inp,
                            "output_tokens": out,
                            "cache_read_tokens": cr,
                            "cache_write_tokens": cw,
                            "total_tokens": inp + out + cr + cw,
                            "cost_cents": round(cents, 2),
                            "cost_usd": round(cents / 100, 4),
                            "tier": agg.get("tier"),
                        }
                    )
                by_model.sort(key=lambda x: x["cost_cents"], reverse=True)
                result_data["cli_usage"] = {
                    "total_input_tokens": total_input,
                    "total_output_tokens": total_output,
                    "total_cache_read_tokens": total_cache_read,
                    "total_cache_write_tokens": total_cache_write,
                    "total_tokens": total_input
                    + total_output
                    + total_cache_read
                    + total_cache_write,
                    "total_cost_cents": round(total_cents, 2),
                    "total_cost_usd": round(total_cents / 100, 2),
                    "by_model": by_model,
                    "model_count": len(by_model),
                    "days_filter": days if days > 0 else "current_billing_month",
                }

                # 可选：获取明细 CSV
                if detail_limit > 0:
                    csv_cmd = [cli_bin]
                    if days > 0:
                        csv_cmd.extend(["--days", str(days)])
                    else:
                        csv_cmd.extend(["--month", datetime.now(UTC).strftime("%Y-%m")])
                    csv_cmd.extend(["--csv", "-"])
                    csv_proc = subprocess.run(csv_cmd, capture_output=True, text=True, timeout=60)
                    if csv_proc.returncode == 0 and csv_proc.stdout:
                        reader = csv.DictReader(io.StringIO(csv_proc.stdout))
                        events = list(reader)
                        # 取最近 detail_limit 条
                        events = events[-detail_limit:] if len(events) > detail_limit else events
                        result_data["cli_usage"]["recent_events"] = [
                            {
                                "datetime": e.get("datetime_local", ""),
                                "model": e.get("model", ""),
                                "input_tokens": int(e.get("input_tokens") or 0),
                                "output_tokens": int(e.get("output_tokens") or 0),
                                "cache_read_tokens": int(e.get("cache_read_tokens") or 0),
                                "value_cents": float(e.get("value_cents") or 0),
                                "kind": e.get("kind", ""),
                            }
                            for e in events
                        ]
                        result_data["cli_usage"]["total_events"] = len(
                            list(csv.DictReader(io.StringIO(csv_proc.stdout)))
                        )
        except Exception as exc:  # noqa: BLE001
            result_data["cli_usage"] = {"error": str(exc)}

    # --- 数据源 2：Cursor API（/auth/usage，免费配额）---
    api_token = ""
    try:
        proc = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                "cursor-access-token",
                "-a",
                "cursor-user",
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            api_token = proc.stdout.strip()
    except Exception:  # noqa: BLE001
        pass

    if api_token:
        result_data["sources"].append("cursor-api:auth/usage")
        try:
            import httpx as _httpx

            resp = _httpx.get(
                "https://api2.cursor.sh/auth/usage",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "User-Agent": "cursor/0.50.0",
                    "x-cursor-client-version": "0.50.0",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                api_data = resp.json()
                result_data["api_usage"] = {
                    "free_quota": api_data,
                    "start_of_month": api_data.get("startOfMonth", ""),
                    "note": "仅返回免费配额(gpt-4)；Pro 版用量由 cursor-usage CLI 提供",
                }
        except Exception as exc:  # noqa: BLE001
            result_data["api_usage"] = {"error": str(exc)}

    # --- 数据源 3：本地 ai-code-tracking.db（AI 代码生成次数 + commit 比例）---
    db_path = Path.home() / ".cursor" / "ai-tracking" / "ai-code-tracking.db"
    if db_path.is_file():
        result_data["sources"].append(f"local-db:{db_path.name}")
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            since_ts = 0
            if days > 0:
                since_dt = datetime.now(UTC) - timedelta(days=days)
                since_ts = int(since_dt.timestamp() * 1000)

            if since_ts > 0:
                cur.execute(
                    "SELECT model, COUNT(*) as count FROM ai_code_hashes WHERE timestamp >= ? GROUP BY model ORDER BY count DESC",
                    (since_ts,),
                )
            else:
                cur.execute(
                    "SELECT model, COUNT(*) as count FROM ai_code_hashes GROUP BY model ORDER BY count DESC",
                )
            model_counts = [
                {"model": r["model"] or "(unknown)", "count": r["count"]} for r in cur.fetchall()
            ]

            cur.execute("SELECT COUNT(*) FROM ai_code_hashes")
            total_hashes = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) as commits, SUM(linesAdded) as total_add, SUM(tabLinesAdded) as tab_add, SUM(composerLinesAdded) as comp_add, SUM(humanLinesAdded) as human_add FROM scored_commits"
            )
            row = cur.fetchone()
            commits_data = {
                "total_commits": row["commits"],
                "total_lines_added": row["total_add"] or 0,
                "tab_lines_added": row["tab_add"] or 0,
                "composer_lines_added": row["comp_add"] or 0,
                "human_lines_added": row["human_add"] or 0,
            }
            ai_lines = commits_data["tab_lines_added"] + commits_data["composer_lines_added"]
            total_lines = commits_data["total_lines_added"] or 1
            commits_data["ai_percentage"] = round(ai_lines / total_lines * 100, 1)

            conn.close()

            result_data["local_db"] = {
                "db_path": str(db_path),
                "total_ai_generations": total_hashes,
                "by_model": model_counts,
                "commits": commits_data,
                "days_filter": days if days > 0 else "all",
            }
        except Exception as exc:  # noqa: BLE001
            result_data["local_db"] = {"error": str(exc)}

    # --- 汇总 ---
    cli = result_data.get("cli_usage") or {}
    total_tokens = cli.get("total_tokens", 0)
    total_cost = cli.get("total_cost_usd", 0)
    total_gen = 0
    if result_data.get("local_db") and "error" not in result_data["local_db"]:
        total_gen = result_data["local_db"].get("total_ai_generations", 0)
    result_data["cursor_summary"] = {
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost,
        "total_ai_generations": total_gen,
        "has_cli": bool(cli and "error" not in cli),
        "has_api_token": bool(api_token),
        "has_local_db": bool(
            result_data.get("local_db") and "error" not in result_data.get("local_db", {})
        ),
        "note": "cursor-usage CLI 提供精确 token 和费用（来自 Dashboard API）。本地 DB 提供 AI 生成次数和代码比例。",
    }

    return _ok(
        f"Cursor 使用统计：{total_tokens:,} tokens，${total_cost}，{total_gen} 次 AI 生成，{len(result_data['sources'])} 个数据源",
        **result_data,
    )


async def tool_query_codex_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 OpenAI Codex CLI 的使用统计（自动从本地数据采集）。

    数据源：
    1. ~/.codex/archived_sessions/*.jsonl — 逐会话的精确 token 用量
       （input/cached/output/reasoning/total tokens + rate_limits）
    2. ~/.codex/goals_1.sqlite 的 thread_goals 表 — 按会话的 tokens_used 和状态
    3. ~/.codex/config.toml — 当前 model 配置

    可用 params:
    - days: 统计最近 N 天的数据（默认 30，0 = 全部）
    """
    import glob
    import sqlite3
    from datetime import UTC, datetime, timedelta

    days = int(params.get("days") if params.get("days") is not None else 30)
    codex_dir = Path.home() / ".codex"
    result_data: dict[str, Any] = {
        "sources": [],
        "sessions": None,
        "goals_db": None,
        "config": None,
        "codex_summary": {},
    }

    # --- 数据源 1：archived_sessions/*.jsonl ---
    sessions_dir = codex_dir / "archived_sessions"
    jsonl_files = sorted(glob.glob(str(sessions_dir / "*.jsonl"))) if sessions_dir.is_dir() else []
    if jsonl_files:
        result_data["sources"].append(f"archived-sessions:{len(jsonl_files)}-files")
        try:
            since_dt = None
            if days > 0:
                since_dt = datetime.now(UTC) - timedelta(days=days)

            sessions_list = []
            total_input = 0
            total_cached = 0
            total_output = 0
            total_reasoning = 0
            total_tokens = 0

            for fpath in jsonl_files:
                session_model = "unknown"
                session_cwd = ""
                session_ts = ""
                last_usage = None
                rate_limit_used = None

                with open(fpath, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        evt_type = evt.get("type", "")
                        payload = evt.get("payload", {})

                        if evt_type == "session_meta":
                            session_model = payload.get("model", session_model)
                            session_cwd = payload.get("cwd", "")
                            session_ts = payload.get("timestamp", "")

                        if evt_type == "event_msg" and payload.get("type") == "token_count":
                            info = payload.get("info", {})
                            last_usage = info.get("total_token_usage", {})
                            rl = payload.get("rate_limits", {})
                            primary = rl.get("primary", {})
                            rate_limit_used = primary.get("used_percent")

                if last_usage:
                    inp = int(last_usage.get("input_tokens") or 0)
                    cached = int(last_usage.get("cached_input_tokens") or 0)
                    out = int(last_usage.get("output_tokens") or 0)
                    reasoning = int(last_usage.get("reasoning_output_tokens") or 0)
                    tot = int(last_usage.get("total_tokens") or 0)

                    # 日期过滤
                    if since_dt and session_ts:
                        try:
                            evt_dt = datetime.fromisoformat(session_ts.replace("Z", "+00:00"))
                            if evt_dt < since_dt:
                                continue
                        except (ValueError, TypeError):
                            pass

                    total_input += inp
                    total_cached += cached
                    total_output += out
                    total_reasoning += reasoning
                    total_tokens += tot

                    sessions_list.append(
                        {
                            "file": Path(fpath).name,
                            "model": session_model,
                            "cwd": session_cwd,
                            "timestamp": session_ts,
                            "input_tokens": inp,
                            "cached_input_tokens": cached,
                            "output_tokens": out,
                            "reasoning_output_tokens": reasoning,
                            "total_tokens": tot,
                            "rate_limit_used_percent": rate_limit_used,
                        }
                    )

            sessions_list.sort(key=lambda x: x["timestamp"], reverse=True)
            result_data["sessions"] = {
                "total_sessions": len(sessions_list),
                "total_input_tokens": total_input,
                "total_cached_input_tokens": total_cached,
                "total_output_tokens": total_output,
                "total_reasoning_output_tokens": total_reasoning,
                "total_tokens": total_tokens,
                "by_session": sessions_list[:20],
                "days_filter": days if days > 0 else "all",
            }
        except Exception as exc:  # noqa: BLE001
            result_data["sessions"] = {"error": str(exc)}

    # --- 数据源 2：goals_1.sqlite ---
    goals_db = codex_dir / "goals_1.sqlite"
    if goals_db.is_file():
        result_data["sources"].append("goals-sqlite")
        try:
            conn = sqlite3.connect(str(goals_db))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(
                "SELECT thread_id, objective, status, token_budget, tokens_used, time_used_seconds, created_at_ms FROM thread_goals ORDER BY created_at_ms DESC"
            )
            goals_list = []
            total_goal_tokens = 0
            total_goal_time = 0
            for r in cur.fetchall():
                tokens = r["tokens_used"] or 0
                total_goal_tokens += tokens
                total_goal_time += r["time_used_seconds"] or 0
                goals_list.append(
                    {
                        "thread_id": r["thread_id"],
                        "objective": (r["objective"] or "")[:80],
                        "status": r["status"],
                        "token_budget": r["token_budget"],
                        "tokens_used": tokens,
                        "time_used_seconds": r["time_used_seconds"] or 0,
                        "created_at": datetime.fromtimestamp(
                            (r["created_at_ms"] or 0) / 1000
                        ).strftime("%Y-%m-%d %H:%M"),
                    }
                )
            conn.close()
            result_data["goals_db"] = {
                "total_threads": len(goals_list),
                "total_tokens_used": total_goal_tokens,
                "total_time_seconds": total_goal_time,
                "by_status": {
                    s: sum(1 for g in goals_list if g["status"] == s)
                    for s in {g["status"] for g in goals_list}
                },
                "threads": goals_list,
            }
        except Exception as exc:  # noqa: BLE001
            result_data["goals_db"] = {"error": str(exc)}

    # --- 数据源 3：config.toml ---
    config_file = codex_dir / "config.toml"
    if config_file.is_file():
        result_data["sources"].append("config-toml")
        try:
            config_text = config_file.read_text(encoding="utf-8")
            model = ""
            reasoning_effort = ""
            for line in config_text.splitlines():
                line = line.strip()
                if line.startswith("model") and "=" in line:
                    model = line.split("=", 1)[1].strip().strip('"')
                if line.startswith("model_reasoning_effort") and "=" in line:
                    reasoning_effort = line.split("=", 1)[1].strip().strip('"')
            result_data["config"] = {
                "model": model,
                "reasoning_effort": reasoning_effort,
            }
        except Exception as exc:  # noqa: BLE001
            result_data["config"] = {"error": str(exc)}

    # --- 汇总 ---
    sess = result_data.get("sessions") or {}
    goals = result_data.get("goals_db") or {}
    total_tok = sess.get("total_tokens", 0) or goals.get("total_tokens_used", 0)
    result_data["codex_summary"] = {
        "total_tokens": total_tok,
        "total_sessions": sess.get("total_sessions", 0),
        "total_threads": goals.get("total_threads", 0),
        "total_time_seconds": goals.get("total_time_seconds", 0),
        "model": (result_data.get("config") or {}).get("model", "unknown"),
        "note": "Codex CLI 本地数据。archived_sessions 含精确 token（input/cached/output/reasoning），goals_db 含按会话的 token 和状态。",
    }

    return _ok(
        f"Codex 使用统计：{total_tok:,} tokens，{sess.get('total_sessions', 0)} 个会话，{len(result_data['sources'])} 个数据源",
        **result_data,
    )


async def tool_query_trae_usage(params: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """查询 Trae IDE 的使用统计（自动从本地数据采集）。

    数据源：
    1. ~/.trae-cn/trae-jwt-token → 尝试调 Trae API 获取 token 用量
    2. Trae CN/User/globalStorage/state.vscdb — 聊天轮次、模型列表、用户 ID
    3. ~/.trae-cn/ 目录 — 配置文件

    注意：Trae 的 token 用量 API 被 403 拦截（需要网页 cookie），
    本工具能提取聊天轮次、模型列表、当前模型等本地数据。
    """
    import sqlite3

    trae_cn = Path.home() / ".trae-cn"
    trae_app = Path.home() / "Library" / "Application Support" / "Trae CN"
    result_data: dict[str, Any] = {
        "sources": [],
        "api_usage": None,
        "local_state": None,
        "config": None,
        "trae_summary": {},
    }

    # --- 数据源 1：尝试调 Trae API ---
    jwt_path = trae_cn / "trae-jwt-token"
    if jwt_path.is_file():
        result_data["sources"].append("trae-jwt-token")
        jwt_token = jwt_path.read_text(encoding="utf-8").strip()
        try:
            import httpx as _httpx

            resp = _httpx.get(
                "https://trae.cn/api/v1/user/usage",
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "User-Agent": "Trae/1.10.0",
                    "Content-Type": "application/json",
                },
                timeout=8,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                result_data["api_usage"] = resp.json()
            else:
                result_data["api_usage"] = {
                    "status_code": resp.status_code,
                    "note": f"Trae API 返回 {resp.status_code}，token 用量需去 Trae 网页设置页查看",
                }
        except Exception as exc:  # noqa: BLE001
            result_data["api_usage"] = {"error": str(exc)}

    # --- 数据源 2：state.vscdb ---
    state_db = trae_app / "User" / "globalStorage" / "state.vscdb"
    if state_db.is_file():
        result_data["sources"].append("state.vscdb")
        try:
            conn = sqlite3.connect(str(state_db))
            cur = conn.cursor()

            # 聊天轮次统计
            cur.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'ai.chat.feedback%'")
            feedback = {}
            for k, v in cur.fetchall():
                feedback[k] = v
            accumulated_turns = 0
            for k, v in feedback.items():
                if "accumulatedTurns" in k:
                    try:
                        accumulated_turns = int(v)
                    except (ValueError, TypeError):
                        pass

            # 当前选择的模型
            cur.execute(
                "SELECT key, value FROM ItemTable WHERE key LIKE '%sessionRelation:globalModelMap%'"
            )
            current_models = {}
            for _k, v in cur.fetchall():
                try:
                    current_models = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    pass

            # 可用模型列表
            cur.execute("SELECT value FROM ItemTable WHERE key LIKE '%model_list_map%' LIMIT 1")
            row = cur.fetchone()
            available_models = {}
            if row:
                try:
                    available_models = json.loads(row[0])
                except (json.JSONDecodeError, TypeError):
                    pass

            # 用户 ID
            cur.execute(
                "SELECT key FROM ItemTable WHERE key LIKE '%_ai-chat:sessionRelation%' LIMIT 1"
            )
            user_id = ""
            row = cur.fetchone()
            if row and "_" in row[0]:
                user_id = row[0].split("_")[0]

            conn.close()

            result_data["local_state"] = {
                "user_id": user_id,
                "accumulated_chat_turns": accumulated_turns,
                "current_models": current_models,
                "available_models_by_mode": {
                    mode: [m.get("name", "") for m in models if isinstance(m, dict)]
                    for mode, models in available_models.items()
                },
                "feedback_keys": list(feedback.keys()),
            }
        except Exception as exc:  # noqa: BLE001
            result_data["local_state"] = {"error": str(exc)}

    # --- 数据源 3：配置文件 ---
    argv_file = trae_cn / "argv.json"
    if argv_file.is_file():
        result_data["sources"].append("argv.json")
        try:
            result_data["config"] = {"argv": json.loads(argv_file.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            pass

    # --- 汇总 ---
    local = result_data.get("local_state") or {}
    result_data["trae_summary"] = {
        "chat_turns": local.get("accumulated_chat_turns", 0),
        "current_models": local.get("current_models", {}),
        "user_id": local.get("user_id", ""),
        "api_accessible": bool(
            result_data.get("api_usage")
            and isinstance(result_data.get("api_usage"), dict)
            and "status_code" not in result_data.get("api_usage", {})
        ),
        "note": "Trae token 用量 API 被 403 拦截。本地能提取聊天轮次和模型列表，精确 token 用量需去 Trae 设置页查看。",
    }

    return _ok(
        f"Trae 使用统计：{local.get('accumulated_chat_turns', 0)} 轮聊天，{len(result_data['sources'])} 个数据源",
        **result_data,
    )

