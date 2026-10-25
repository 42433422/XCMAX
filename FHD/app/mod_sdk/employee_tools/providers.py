"""Provider health and billing probes with explicit transport and catalog dependencies."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

from .configuration import (
    _provider_base_url,
    _provider_has_key,
)
from .employee_tool_ports import Payload, ProviderPorts
from .results import _err, _ok


async def test_llm_key_health(ports: ProviderPorts, params: Payload, ctx: Payload) -> Payload:
    """对已配置的 provider 发 ping 请求，测延迟和可用性（支持 10 家）。

    真实 HTTP 调用 /chat/completions（max_tokens=1），返回每个 provider 的健康状态。
    可用 params.provider 指定单个 provider，或留空测全部。
    """
    client_factory = ports.client
    if client_factory is None:
        return _err("httpx 未安装，无法测试")
    target = str(params.get("provider") or "").strip().lower()
    env = dict(os.environ)
    results: list[Payload] = []

    async def _ping(
        name: str, base_url: str, api_key: str, model: str, no_auth: bool = False
    ) -> Payload:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if not no_auth and api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        t0 = asyncio.get_event_loop().time()
        try:
            async with client_factory(timeout=20) as client:
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
                except RECOVERABLE_ERRORS:
                    body = resp.text[:200]
                return {
                    "provider": name,
                    "ok": resp.is_success,
                    "status": resp.status_code,
                    "latency_ms": elapsed,
                    "model": model,
                    "error": "" if resp.is_success else str(body)[:300],
                }
        except RECOVERABLE_ERRORS as exc:
            elapsed = round((asyncio.get_event_loop().time() - t0) * 1000, 1)
            return {
                "provider": name,
                "ok": False,
                "status": 0,
                "latency_ms": elapsed,
                "model": model,
                "error": repr(exc)[:300],
            }

    for profile in ports.profiles:
        name = profile["name"]
        if target and target != "all" and (target != name):
            continue
        key = _provider_has_key(profile, env)
        no_auth = profile.get("no_auth", False)
        if not key and (not no_auth):
            continue
        base_url = _provider_base_url(profile, env)
        ping_model = profile["ping_model"]
        results.append(await _ping(name, base_url, key or "", ping_model, no_auth))
    if not results:
        return _err(f"未找到已配置 API key 的 provider（已检查 {len(ports.profiles)} 家）")
    healthy = sum(1 for r in results if r["ok"])
    return _ok(
        f"测试 {len(results)} 个 provider，{healthy} 个健康",
        results=results,
        healthy_count=healthy,
        total_count=len(results),
    )


async def query_provider_usage(ports: ProviderPorts, params: Payload, ctx: Payload) -> Payload:
    """查询 provider 账户余额与用量（通用化，支持多家 billing API）。

    真实探测 provider 的 billing endpoint，返回余额/用量。
    可用 params.provider 指定单个 provider，或留空查全部已配置的。
    """
    if ports.client is None:
        return _err("httpx 未安装")
    target = str(params.get("provider") or "").strip().lower()
    env = dict(os.environ)
    all_findings: list[Payload] = []
    checked = 0
    supported = 0
    async with ports.client(timeout=15) as client:
        for profile in ports.profiles:
            name = profile["name"]
            if target and target != "all" and (target != name):
                continue
            key = _provider_has_key(profile, env)
            no_auth = profile.get("no_auth", False)
            if not key and (not no_auth):
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
                url = (
                    ep
                    if str(ep).startswith(("https://", "http://"))
                    else f"{base_url.rstrip('/')}{ep}"
                )
                try:
                    resp = await client.get(url, headers=headers)
                    body: Any
                    try:
                        body = resp.json()
                    except RECOVERABLE_ERRORS:
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
                except RECOVERABLE_ERRORS as exc:
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
