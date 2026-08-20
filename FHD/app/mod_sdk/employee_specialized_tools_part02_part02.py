# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.mod_sdk.employee_specialized_tools")


def _provider_model(profile: dict[str, _facade().Any], env: dict[str, str]) -> str:
    """获取 provider 的模型（env 覆盖 default）。"""
    env_key = profile.get("model_env")
    if env_key:
        v = env.get(env_key)
        if v:
            return v
    return _facade().cast("str", profile["default_model"])


def _detect_provider_name(profile: dict[str, _facade().Any], env: dict[str, str]) -> bool:
    """判断当前环境是否匹配该 provider（用于 OpenAI 兼容的 b.ai/openai 区分）。"""
    detect = profile.get("detect")
    if detect:
        return bool(detect(env))
    return _facade()._provider_has_key(profile, env) is not None


async def tool_read_llm_env_config(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """读取 .env 中 LLM 相关配置（API key 脱敏）。

    真实读取 FHD/.env 文件，提取所有 provider 的配置段，key 一律脱敏为 sk-***xxx。
    """
    env_path = _facade()._FHD_ROOT / ".env"
    env_map = _facade()._read_env_file(env_path)
    if not env_map:
        return _facade()._err(f".env 文件不存在或为空: {env_path}")
    llm_cfg: dict[str, str] = {}
    for k in _facade()._LLM_ENV_KEYS:
        if k in env_map:
            v = env_map[k]
            llm_cfg[k] = _facade()._mask_secret(v) if k in _facade()._LLM_SECRET_KEYS else v
    runtime_cfg: dict[str, str] = {}
    for k in _facade()._LLM_ENV_KEYS:
        runtime_value = _facade().os.environ.get(k)
        if runtime_value:
            runtime_cfg[k] = (
                _facade()._mask_secret(runtime_value)
                if k in _facade()._LLM_SECRET_KEYS
                else runtime_value
            )
    return _facade()._ok(
        f".env LLM 段读取完成（{len(llm_cfg)} 项），运行时环境变量 {len(runtime_cfg)} 项",
        env_file=str(env_path),
        env_config=llm_cfg,
        runtime_config=runtime_cfg,
        configured_provider=env_map.get("XCAGI_LLM_PROVIDER")
        or _facade().os.environ.get("XCAGI_LLM_PROVIDER")
        or "(未配置)",
        supported_providers=[p["name"] for p in _facade()._PROVIDER_PROFILES],
    )


async def tool_list_configured_providers(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """列出当前已配置的 LLM provider 及其状态（支持 10 家）。

    从 os.environ 实时读取，遍历所有 provider profile，标注 key 是否存在。
    """
    env = dict(_facade().os.environ)
    providers: list[dict[str, _facade().Any]] = []
    for profile in _facade()._PROVIDER_PROFILES:
        name = profile["name"]
        key = _facade()._provider_has_key(profile, env)
        no_auth = profile.get("no_auth", False)
        if not key and (not no_auth):
            continue
        base_url = _facade()._provider_base_url(profile, env)
        model = _facade()._provider_model(profile, env)
        entry: dict[str, _facade().Any] = {
            "provider": name,
            "api_key": _facade()._mask_secret(key) if key else "(无需)" if no_auth else "",
            "has_key": bool(key) or no_auth,
            "base_url": base_url,
            "model": model,
            "ping_model": profile["ping_model"],
            "has_billing_api": bool(profile.get("billing_endpoints")),
        }
        providers.append(entry)
    active = _facade().os.environ.get("XCAGI_LLM_PROVIDER", "(未配置，走 default path)")
    return _facade()._ok(
        f"已配置 {len(providers)} 个 provider（共支持 {len(_facade()._PROVIDER_PROFILES)} 家），当前激活: {active}",
        providers=providers,
        active_provider=active,
        employee_llm_model=_facade().os.environ.get("XCAGI_EMPLOYEE_LLM_MODEL", "(未配置)"),
        supported_count=len(_facade()._PROVIDER_PROFILES),
    )


async def tool_test_llm_key_health(
    params: dict[str, _facade().Any], ctx: dict[str, _facade().Any]
) -> dict[str, _facade().Any]:
    """对已配置的 provider 发 ping 请求，测延迟和可用性（支持 10 家）。

    真实 HTTP 调用 /chat/completions（max_tokens=1），返回每个 provider 的健康状态。
    可用 params.provider 指定单个 provider，或留空测全部。
    """
    if _facade().httpx is None:
        return _facade()._err("httpx 未安装，无法测试")
    target = str(params.get("provider") or "").strip().lower()
    env = dict(_facade().os.environ)
    results: list[dict[str, _facade().Any]] = []

    async def _ping(
        name: str, base_url: str, api_key: str, model: str, no_auth: bool = False
    ) -> dict[str, _facade().Any]:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if not no_auth and api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        t0 = _facade().asyncio.get_event_loop().time()
        try:
            async with _facade().httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                )
                elapsed = round((_facade().asyncio.get_event_loop().time() - t0) * 1000, 1)
                body: _facade().Any
                try:
                    body = resp.json()
                except _facade().RECOVERABLE_ERRORS:
                    body = resp.text[:200]
                return {
                    "provider": name,
                    "ok": resp.is_success,
                    "status": resp.status_code,
                    "latency_ms": elapsed,
                    "model": model,
                    "error": "" if resp.is_success else str(body)[:300],
                }
        except _facade().RECOVERABLE_ERRORS as exc:
            elapsed = round((_facade().asyncio.get_event_loop().time() - t0) * 1000, 1)
            return {
                "provider": name,
                "ok": False,
                "status": 0,
                "latency_ms": elapsed,
                "model": model,
                "error": repr(exc)[:300],
            }

    for profile in _facade()._PROVIDER_PROFILES:
        name = profile["name"]
        if target and target != "all" and (target != name):
            continue
        key = _facade()._provider_has_key(profile, env)
        no_auth = profile.get("no_auth", False)
        if not key and (not no_auth):
            continue
        base_url = _facade()._provider_base_url(profile, env)
        ping_model = profile["ping_model"]
        results.append(await _ping(name, base_url, key or "", ping_model, no_auth))
    if not results:
        return _facade()._err(
            f"未找到已配置 API key 的 provider（已检查 {len(_facade()._PROVIDER_PROFILES)} 家）"
        )
    healthy = sum(1 for r in results if r["ok"])
    return _facade()._ok(
        f"测试 {len(results)} 个 provider，{healthy} 个健康",
        results=results,
        healthy_count=healthy,
        total_count=len(results),
    )
