"""Provider configuration parsing and secret-safe presentation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

from .employee_tool_ports import Configuration, Payload
from .results import _err, _ok


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


def _provider_has_key(profile: Payload, env: dict[str, str]) -> str | None:
    """检查 provider 是否配了 key，返回第一个非空 key（不脱敏）。"""
    for k in profile["env_keys"]:
        v = env.get(k)
        if v:
            return v
    return None


def _provider_base_url(profile: Payload, env: dict[str, str]) -> str:
    """获取 provider 的 base_url（env 覆盖 default）。"""
    env_key = profile.get("base_url_env")
    if env_key:
        v = env.get(env_key)
        if v:
            return v
    return cast("str", profile["base_url_default"])


def _provider_model(profile: Payload, env: dict[str, str]) -> str:
    """获取 provider 的模型（env 覆盖 default）。"""
    env_key = profile.get("model_env")
    if env_key:
        v = env.get(env_key)
        if v:
            return v
    return cast("str", profile["default_model"])


def _detect_provider_name(profile: Payload, env: dict[str, str]) -> bool:
    """判断当前环境是否匹配该 provider（用于 OpenAI 兼容的 b.ai/openai 区分）。"""
    detect = profile.get("detect")
    if detect:
        return bool(detect(env))
    return _provider_has_key(profile, env) is not None


async def read_llm_env_config(ports: Configuration, params: Payload, ctx: Payload) -> Payload:
    """读取 .env 中 LLM 相关配置（API key 脱敏）。

    真实读取 FHD/.env 文件，提取所有 provider 的配置段，key 一律脱敏为 sk-***xxx。
    """
    env_path = ports.root / ".env"
    env_map = _read_env_file(env_path)
    if not env_map:
        return _err(f".env 文件不存在或为空: {env_path}")
    llm_cfg: dict[str, str] = {}
    for k in ports.env_keys:
        if k in env_map:
            v = env_map[k]
            llm_cfg[k] = _mask_secret(v) if k in ports.secret_keys else v
    runtime_cfg: dict[str, str] = {}
    for k in ports.env_keys:
        runtime_value = os.environ.get(k)
        if runtime_value:
            runtime_cfg[k] = (
                _mask_secret(runtime_value) if k in ports.secret_keys else runtime_value
            )
    return _ok(
        f".env LLM 段读取完成（{len(llm_cfg)} 项），运行时环境变量 {len(runtime_cfg)} 项",
        env_file=str(env_path),
        env_config=llm_cfg,
        runtime_config=runtime_cfg,
        configured_provider=env_map.get("XCAGI_LLM_PROVIDER")
        or os.environ.get("XCAGI_LLM_PROVIDER")
        or "(未配置)",
        supported_providers=[p["name"] for p in ports.profiles],
    )


async def list_configured_providers(ports: Configuration, params: Payload, ctx: Payload) -> Payload:
    """列出当前已配置的 LLM provider 及其状态（支持 10 家）。

    从 os.environ 实时读取，遍历所有 provider profile，标注 key 是否存在。
    """
    env = dict(os.environ)
    providers: list[Payload] = []
    for profile in ports.profiles:
        name = profile["name"]
        key = _provider_has_key(profile, env)
        no_auth = profile.get("no_auth", False)
        if not key and (not no_auth):
            continue
        base_url = _provider_base_url(profile, env)
        model = _provider_model(profile, env)
        entry: Payload = {
            "provider": name,
            "api_key": _mask_secret(key) if key else "(无需)" if no_auth else "",
            "has_key": bool(key) or no_auth,
            "base_url": base_url,
            "model": model,
            "ping_model": profile["ping_model"],
            "has_billing_api": bool(profile.get("billing_endpoints")),
        }
        providers.append(entry)
    active = os.environ.get("XCAGI_LLM_PROVIDER", "(未配置，走 default path)")
    return _ok(
        f"已配置 {len(providers)} 个 provider（共支持 {len(ports.profiles)} 家），当前激活: {active}",
        providers=providers,
        active_provider=active,
        employee_llm_model=os.environ.get("XCAGI_EMPLOYEE_LLM_MODEL", "(未配置)"),
        supported_count=len(ports.profiles),
    )
