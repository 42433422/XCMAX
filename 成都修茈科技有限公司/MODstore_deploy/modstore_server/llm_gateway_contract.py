"""Thin controls for metered calls through the existing LiteLLM proxy.

The local Router's retry settings do not constrain a second proxy hop. These
controls belong to the trusted transport, and the receipt must come from the
native HTTP response headers before any local Router normalization.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

MAX_STREAM_BYTES = 16_777_216
MAX_STREAM_EVENTS = 65_536


class StreamLimitError(ValueError):
    """The original model response exceeded the host's resource budget."""


class StreamReceiptBudget:
    """Bound SDK-decoded receipts before forwarding or retaining tool arguments."""

    def __init__(self) -> None:
        self._events = 0
        self._bytes = 0

    def consume(self, data: Mapping[str, Any]) -> None:
        self._events += 1
        if self._events > MAX_STREAM_EVENTS:
            raise StreamLimitError("model stream event limit exceeded")
        try:
            self._bytes += len(
                json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
        except ValueError:
            raise StreamLimitError("model stream contains invalid JSON text") from None
        if self._bytes > MAX_STREAM_BYTES:
            raise StreamLimitError("model stream byte limit exceeded")


def codex_deployment_identity(info: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, str]:
    """Project an explicit gateway deployment, without exposing its credentials.

    This is an expected identity for qualification, never evidence that a model
    request has passed. OpenAI-compatible transport names alone do not identify
    a non-OpenAI upstream; those deployments must declare their actual vendor.
    """
    from urllib.parse import urlsplit

    resolved = params.get("model")
    prefix, _, native = resolved.partition("/") if isinstance(resolved, str) else ("", "", "")
    vendor = info.get("upstream_vendor") or (prefix if prefix not in {"openai", "azure"} else "")
    response_model = info.get("response_model") or native
    host = (urlsplit(str(params.get("api_base") or "")).hostname or "").lower().rstrip(".")
    if (
        not isinstance(vendor, str)
        or not vendor.strip()
        or vendor.lower() in {"openai", "azure", "azure-openai", "azure_openai", "litellm"}
        or not isinstance(response_model, str)
        or not 0 < len(response_model) <= 256
        or any(char.isspace() or ord(char) < 32 for char in response_model)
        or any(
            host == domain or host.endswith("." + domain)
            for domain in ("openai.com", "chatgpt.com", "openai.azure.com")
        )
    ):
        return {}
    return {"upstream_vendor": vendor.strip(), "response_model": response_model}


def codex_route_contract(
    provider: str, model: str, capabilities: Mapping[str, Any]
) -> dict[str, Any]:
    """Describe only routes that can be independently qualified by the host."""
    from fastapi import HTTPException

    from modstore_server.llm_billed_chat import _chat_total_deadline_s
    from modstore_server.llm_key_resolver import OAI_COMPAT_OPENAI_STYLE_PROVIDERS

    identity = {key: capabilities.get(key) for key in ("upstream_vendor", "response_model")}
    if provider != "litellm":
        if provider not in OAI_COMPAT_OPENAI_STYLE_PROVIDERS or provider in {
            "openai",
            "openrouter",
        }:
            raise HTTPException(
                409,
                {
                    "code": "CODEX_MODEL_UNSUPPORTED",
                    "message": "当前所选模型没有已支持的独立 Responses 路由，请在模型设置中选择兼容模型。",
                    "recovery": "choose_compatible_runtime_model",
                },
            )
        identity = {"upstream_vendor": provider, "response_model": model}
    elif capabilities.get("source") != "litellm_model_info" or not all(identity.values()):
        raise HTTPException(
            409,
            {
                "code": "CODEX_MODEL_METADATA_REQUIRED",
                "message": "当前模型未提供独立运行时所需的 Responses 路由信息，请管理员在现有 LiteLLM 模型配置中确认上游厂商和响应模型。",
                "recovery": "configure_gateway_model_metadata",
            },
        )
    if (
        any(
            type(capabilities.get(key)) is not int or capabilities[key] <= 0
            for key in ("context_window", "max_output_tokens")
        )
        or capabilities["max_output_tokens"] >= capabilities["context_window"]
        or (
            "max_input_tokens" in capabilities
            and (
                type(capabilities["max_input_tokens"]) is not int
                or capabilities["max_input_tokens"] <= 0
            )
        )
    ):
        raise HTTPException(
            409,
            {
                "code": "CODEX_MODEL_CAPACITY_REQUIRED",
                "message": "当前模型缺少有效上下文和输出容量，请管理员补齐现有模型配置。",
                "recovery": "configure_gateway_model_capabilities",
            },
        )
    return {
        "schema": "xcmax.codex-route.v1",
        "codex_version": "0.171.0",
        **identity,
        "gateway_kind": "market",
        "failover_policy": "disabled",
        "max_model_calls": 24,
        "max_request_bytes": 4_194_304,
        "request_timeout_seconds": _chat_total_deadline_s(),
        "qualification": {"state": "requires_local_qualification"},
    }


def gateway_body(provider: str) -> dict[str, Any]:
    """Return server-owned per-request proxy controls, never worker input."""
    return {"num_retries": 0, "disable_fallbacks": True} if provider == "litellm" else {}


def codex_catalog_support(
    provider: str, row: Mapping[str, Any], api_key: str | None, base_url: str | None
) -> dict[str, Any]:
    """Project the save-time guards; chat capability is not executor compatibility."""
    from fastapi import HTTPException

    from modstore_server.llm_key_resolver import chat_route_snapshot
    from modstore_server.llm_model_taxonomy import model_context_capabilities
    from modstore_server.llm_responses_transport import validate_responses_route

    if row.get("runtime_selectable") is not True:
        return {
            "selectable": False,
            "code": "MODEL_NOT_CHAT",
            "message": "此模型不用于对话任务。",
        }
    try:
        route = chat_route_snapshot(
            provider, str(row["id"]), api_key, base_url, "catalog", "catalog"
        )
        validate_responses_route(route)
        codex_route_contract(
            provider, route.model, model_context_capabilities(provider, route.model, row)
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return {
            "selectable": False,
            "code": detail.get("code", "CODEX_ROUTE_UNAVAILABLE"),
            "message": detail.get("message", "当前账号尚未配置可用的执行器路线。"),
        }
    return {
        "selectable": True,
        "code": "REQUIRES_QUALIFICATION",
        "message": "需通过本机运行验收。",
        "protocol": "responses" if provider == "litellm" else "chat_completions",
    }


def gateway_single_attempt(headers: Mapping[str, object]) -> bool:
    """Require both native proxy counters to prove no hidden paid attempts.

    Missing, duplicated, malformed, or positive counters are unknown usage, not
    evidence of zero retries. A response's final usage alone cannot settle it.
    """
    for name in ("x-litellm-attempted-retries", "x-litellm-attempted-fallbacks"):
        values = [value for key, value in headers.items() if key.lower() == name]
        if len(values) != 1:
            return False
        value = values[0]
        if type(value) is int and value == 0:
            continue
        if not isinstance(value, str):
            return False
        value = value.strip()
        if not value or not value.isascii() or not value.isdecimal():
            return False
        if any(character != "0" for character in value):
            return False
    return True
